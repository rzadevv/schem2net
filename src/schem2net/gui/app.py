"""The schem2net desktop application: a schematic PDF, the nets extracted from it, and
what to check. Extraction runs `schem2net.gui.worker` in a process of its own; the nets
are shown in the page `schem2net report` writes, driven through `view.js`."""

import json
import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QLibraryInfo,
    QPointF,
    QProcess,
    Qt,
    QTemporaryDir,
    QTimer,
    QUrl,
    qFormatLogMessage,
    qInstallMessageHandler,
)
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from schem2net import __version__, export, library, report
from schem2net.cli import _stem, _write
from schem2net.ir import LOW_CONFIDENCE, Design, Net

WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld  # view.js, apart from the page's
KEY = Qt.ItemDataRole.UserRole  # an item's id, or a group's kind
SORT = Qt.ItemDataRole.UserRole + 1  # an item's sort key, where its text sorts badly
ZOOM_STEP = 1.25
HOW = {  # how a pin's number was found, as the IR records it
    "read": "printed",
    "row": "printed",
    "library": "part library",
    "unnumbered": "not shown",
}
SEVERITY = {"error": 2, "warn": 1, "info": 0}
SEVERITY_TEXT = {"error": "Error", "warn": "Warning", "info": "Note"}
GENERATORS = {"kicad": "KiCad", "altium": "Altium", "eagle": "Eagle", "easyeda": "EasyEDA"}
GENERATORS["orcad"] = "OrCAD Capture"
EXPORTS = [  # menu entry, file type, pattern, suffix, write(window, path)
    (
        "&KiCad Netlist…",
        "KiCad netlist",
        "*.net",
        ".net",
        lambda w, p: _write(p, export.kicad_netlist(w.design)),
    ),
    ("&JSON…", "schem2net JSON", "*.json", ".ir.json", lambda w, p: w.design.save(p)),
    (
        "&Bill of Materials…",
        "Bill of materials",
        "*.csv",
        ".bom.csv",
        lambda w, p: _write(p, export.bom_csv(w.design)),
    ),
    (
        "&SPICE Netlist…",
        "SPICE netlist",
        "*.cir",
        ".cir",
        lambda w, p: _write(p, export.spice_netlist(w.design)),
    ),
    (
        "&HTML Report…",
        "HTML report",
        "*.html",
        ".html",
        lambda w, p: _write(p, w._output("report.html").read_text()),
    ),
]


class Item(QTreeWidgetItem):
    """A row that sorts by its SORT data where it has some."""

    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        mine, theirs = self.data(column, SORT), other.data(column, SORT)
        if mine is not None and theirs is not None:
            return mine < theirs
        return self.text(column).lower() < other.text(column).lower()


class ReportPage(QWebEnginePage):
    """Shows the report it is given and goes nowhere else. Its settings keep a local
    page from reading other files or the network."""

    def __init__(self, parent):
        super().__init__(parent)  # Qt's default profile keeps nothing on disk
        self.allowed = QUrl()
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )

    def acceptNavigationRequest(self, url, kind, main_frame):
        return url == self.allowed or url.scheme() in ("data", "about")


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.file: Path | None = None
        self.design: Design | None = None
        self.pins, self.net_of, self.guessed = {}, {}, set()  # lookups into the design
        self.review: list[dict] = []
        self.out: QTemporaryDir | None = None  # the worker's output, kept while shown
        self.process: QProcess | None = None
        self.clock = QElapsedTimer()
        self.picked: tuple[str, str] | None = None  # (list, id) of what is highlighted
        self.fresh = None  # an item made current by the click being handled
        self.report_pages: list[int] = []  # numbers of the pages the report shows
        self.report_index: int | None = None  # which of them is in view
        self.folder = Path.cwd()
        default = os.environ.get("SCHEM2NET_LIBRARY")  # the command line's default too
        self.library: Path | None = Path(default) if default else None

        self.setWindowTitle("schem2net")
        self.setAcceptDrops(True)
        self._actions()
        self._center()
        self._docks()
        self._menus()
        self._status()
        self.stack.setFocus()
        # The report view draws with the GPU. Shown first after the window is, it would make
        # Qt create the window again, and a screen recorder following it would lose it; so
        # it is in view when the window is created, and the empty page is put back on show.
        self.stack.setCurrentWidget(self.tabs)
        self.tabs.setCurrentWidget(self.web)
        self.web.setHtml("")
        self.tabs.currentChanged.connect(self._update)
        self._update()

    # Layout

    def _action(self, text, slot, keys=None, icon=None, tip=None, low=False):
        action = QAction(text, self)
        action.triggered.connect(slot)
        if keys:
            action.setShortcuts(keys if isinstance(keys, list) else [QKeySequence(keys)])
        if icon:
            action.setIcon(_icon(*icon))
        if tip:
            action.setStatusTip(tip)
        if low:  # shown as an icon alone in the toolbar
            action.setPriority(QAction.Priority.LowPriority)
        return action

    def _actions(self):
        key = QKeySequence.StandardKey
        sp = QStyle.StandardPixmap
        self.open_action = self._action(
            "&Open…",
            self.choose,
            key.Open,
            ("document-open", sp.SP_DialogOpenButton),
            "Open a schematic PDF",
        )
        self.extract_action = self._action(
            "&Extract",
            self.extract,
            "Ctrl+E",
            ("system-run", sp.SP_MediaPlay),
            "Extract components and nets from the open PDF",
        )
        self.stop_action = self._action(
            "S&top",
            self.stop,
            None,
            ("process-stop", sp.SP_BrowserStop),
            "Stop the extraction; nothing is kept",
        )
        self.quit_action = self._action("&Quit", self.close, key.Quit)
        self.exports = [
            self._action(e[0], lambda _=False, e=e: self._export(*e[1:])) for e in EXPORTS
        ]
        self.exports[0].setShortcut(key.Save)
        self.schematic_action = self._action(
            "KiCad &Schematic Project…",
            self.export_schematic,
            tip="Write an editable KiCad project, one sheet per page",
        )
        self.zoom_in_action = self._action(
            "Zoom &In",
            lambda: self.zoom(ZOOM_STEP),
            [QKeySequence(key.ZoomIn), "Ctrl+="],
            ("zoom-in", None),
            low=True,
        )
        self.zoom_out_action = self._action(
            "Zoom &Out",
            lambda: self.zoom(1 / ZOOM_STEP),
            key.ZoomOut,
            ("zoom-out", None),
            low=True,
        )
        self.fit_action = self._action(
            "&Fit Page", self.fit, "Ctrl+0", ("zoom-fit-best", None), low=True
        )
        self.previous_action = self._action(
            "&Previous Page",
            lambda: self.turn(-1),
            "PgUp",
            ("go-up", sp.SP_ArrowUp),
            low=True,
        )
        self.next_action = self._action(
            "&Next Page",
            lambda: self.turn(1),
            "PgDown",
            ("go-down", sp.SP_ArrowDown),
            low=True,
        )
        self.library_action = self._action(
            "Part &Library…",
            self.choose_library,
            tip="Choose a folder made by schem2net index-library, to read pin numbers from",
        )
        self.no_library_action = self._action("&No Part Library", lambda: self._set_library(None))
        self.find_action = self._action("&Find…", self.find, key.Find)
        self.clear_action = self._action("&Clear Selection", self.clear, "Esc")
        for action in (self.previous_action, self.next_action):
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _center(self):
        self.drawing = QPdfView()
        self.drawing.setPageMode(QPdfView.PageMode.MultiPage)
        self.drawing.setZoomMode(QPdfView.ZoomMode.FitInView)
        self.drawing.pageNavigator().currentPageChanged.connect(self._page_shown)
        self.drawing.viewport().installEventFilter(self)
        self.document = QPdfDocument(self)

        self.web = QWebEngineView()
        page = self.report_page = ReportPage(self.web)
        script = QWebEngineScript()
        script.setName("schem2net")
        script.setSourceCode((Path(__file__).with_name("view.js")).read_text())
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(WORLD)
        page.scripts().insert(script)
        page.titleChanged.connect(self._report_title)
        page.renderProcessTerminated.connect(self._report_crashed)
        self.web.setPage(page)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web.setAcceptDrops(False)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.drawing, "Original")
        self.tabs.addTab(self.web, "Extracted Nets")
        for action in (self.previous_action, self.next_action):
            self.tabs.addAction(action)

        empty = QLabel("Open a schematic PDF with File › Open (Ctrl+O), or drop one here.")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setEnabled(False)
        self.stack = QStackedWidget()
        self.stack.addWidget(empty)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

    def _list(self, title, columns, hint):
        tree = QTreeWidget()
        tree.setHeaderLabels(columns)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.currentItemChanged.connect(lambda item: self._current(tree, item))
        tree.itemClicked.connect(lambda item: self._clicked(tree, item))
        tree.setProperty("kind", title.lower())
        search = QLineEdit()
        search.setPlaceholderText(hint)
        search.setClearButtonEnabled(True)
        search.textChanged.connect(lambda text: _filter(tree, text))
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(search)
        layout.addWidget(tree)
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(box)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        return dock, tree, search

    def _docks(self):
        self.nets_dock, self.nets, _ = self._list(
            "Nets", ["Net", "Pins", "Confidence"], "Filter nets"
        )
        self.parts_dock, self.parts, _ = self._list(
            "Components", ["Reference", "Value", "Pins"], "Filter components"
        )
        self.issues_dock, self.issues, _ = self._list("Issues", ["Issue"], "Filter issues")
        self.nets.headerItem().setToolTip(
            2, "Evidence weight, not a probability: a net above 0.8 may still have a wrong pad"
        )
        self.issues.setRootIsDecorated(True)
        self.issues.setHeaderHidden(True)
        for tree in (self.nets, self.parts):
            tree.setSortingEnabled(True)
            tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
            header = tree.header()
            header.setStretchLastSection(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self.properties = QTreeWidget()
        self.properties.setHeaderLabels(["Property", "Value"])
        self.properties.setAlternatingRowColors(True)
        self.properties.setColumnWidth(0, 130)
        self.properties.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.properties.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.properties_dock = QDockWidget("Properties", self)
        self.properties_dock.setObjectName("Properties")
        self.properties_dock.setWidget(self.properties)
        self.properties_dock.setFeatures(self.nets_dock.features())
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.properties_dock, Qt.Orientation.Vertical
        )
        self.tabifyDockWidget(self.nets_dock, self.parts_dock)
        self.tabifyDockWidget(self.parts_dock, self.issues_dock)
        self.setTabPosition(Qt.DockWidgetArea.LeftDockWidgetArea, QTabWidget.TabPosition.North)
        for dock in (self.nets_dock, self.parts_dock, self.issues_dock):
            dock.setTitleBarWidget(QWidget())  # their tabs name them
        self.nets_dock.raise_()
        QTimer.singleShot(0, self._size_docks)  # once shown: before, sizes do not hold

    def _size_docks(self):
        self.resizeDocks([self.nets_dock], [max(340, self.width() // 5)], Qt.Orientation.Horizontal)
        height = self.height()
        self.resizeDocks(
            [self.nets_dock, self.properties_dock],
            [height * 3 // 5, height * 2 // 5],
            Qt.Orientation.Vertical,
        )

    def _menus(self):
        bar = self.menuBar()
        file = bar.addMenu("&File")
        file.addAction(self.open_action)
        file.addSeparator()
        file.addAction(self.extract_action)
        file.addAction(self.stop_action)
        libraries = file.addMenu("Part Li&brary")
        libraries.addActions([self.library_action, self.no_library_action])
        file.addSeparator()
        exports = file.addMenu("E&xport")
        exports.addActions(self.exports)
        exports.addSeparator()
        exports.addAction(self.schematic_action)
        file.addSeparator()
        file.addAction(self.quit_action)

        edit = bar.addMenu("&Edit")
        edit.addAction(self.find_action)
        edit.addAction(self.clear_action)

        view = bar.addMenu("&View")
        view.addActions([self.zoom_in_action, self.zoom_out_action, self.fit_action])
        view.addSeparator()
        view.addActions([self.previous_action, self.next_action])
        view.addSeparator()
        panels = view.addMenu("&Panels")
        for dock in (self.nets_dock, self.parts_dock, self.issues_dock, self.properties_dock):
            panels.addAction(dock.toggleViewAction())

        help_ = bar.addMenu("&Help")
        help_.addAction(self._action("&About schem2net", self.about))
        help_.addAction(self._action("About &Qt", QApplication.aboutQt))

        tools = self.addToolBar("Main")
        tools.setObjectName("Main")
        tools.setMovable(False)
        tools.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tools.addActions([self.open_action, self.extract_action, self.stop_action])
        button = QToolButton()
        button.setText("Export")
        button.setIcon(_icon("document-save-as", QStyle.StandardPixmap.SP_DialogSaveButton))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setMenu(exports)
        tools.addWidget(button)
        self.export_button = button
        tools.addSeparator()
        tools.addActions([self.zoom_out_action, self.zoom_in_action, self.fit_action])
        tools.addSeparator()
        tools.addActions([self.previous_action, self.next_action])
        panels.addAction(tools.toggleViewAction())

    def _status(self):
        bar = self.statusBar()
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)  # the extractor reports no progress, so none is shown
        self.busy.setMaximumWidth(120)
        self.busy.setTextVisible(False)
        self.busy.hide()
        self.file_label = QLabel()
        self.page_label = QLabel()
        self.counts_label = QLabel()
        self.state_label = QLabel()
        for widget in (
            self.busy,
            self.file_label,
            self.page_label,
            self.counts_label,
            self.state_label,
        ):
            if isinstance(widget, QLabel):
                widget.setTextFormat(Qt.TextFormat.PlainText)
                widget.setContentsMargins(6, 0, 6, 0)
            bar.addPermanentWidget(widget)

    # Files

    def choose(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "Open Schematic PDF", str(self.folder), "PDF files (*.pdf *.PDF);;All files (*)"
        )
        if file:
            self.open(Path(file))

    def open(self, file: Path) -> bool:
        """Show a PDF, leaving the one open as it was if it cannot be read."""
        file = file.expanduser().absolute()
        if not file.is_file():
            self._error("Cannot open file", f"{file}: no such file.")
            return False
        document = QPdfDocument(self)
        error = document.load(str(file))
        if error != QPdfDocument.Error.None_:
            why = {
                QPdfDocument.Error.InvalidFileFormat: "not a PDF that can be read",
                QPdfDocument.Error.IncorrectPassword: "protected by a password",
                QPdfDocument.Error.UnsupportedSecurityScheme: "encrypted in a way not supported",
                QPdfDocument.Error.FileNotFound: "no such file",
            }.get(error, "could not be read")
            document.deleteLater()
            self._error("Cannot open file", f"{file.name}: {why}.")
            return False
        self.stop()
        self._forget()
        self.document.deleteLater()
        self.document = document
        self.drawing.setDocument(document)
        self.drawing.setZoomMode(QPdfView.ZoomMode.FitInView)
        self.file = file
        self.folder = file.parent
        self.setWindowTitle(f"{file.name} — schem2net")
        self.file_label.setText(file.name)
        self.file_label.setToolTip(str(file))
        self.state_label.setText("Not extracted")
        self.stack.setCurrentWidget(self.tabs)
        self.tabs.setCurrentWidget(self.drawing)
        self._page_shown(0)
        self._update()
        self._summary()
        return True

    def dragEnterEvent(self, event):
        if _dropped_pdf(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        file = _dropped_pdf(event)
        if file:
            event.acceptProposedAction()
            self.open(file)

    # Extraction

    def extract(self):
        if not self.file or self.process:
            return
        self._forget()
        self.out = QTemporaryDir()
        process = QProcess(self)
        process.setProgram(sys.executable)
        # -P: a folder named schem2net in the working directory is not imported
        arguments = ["-P", "-m", "schem2net.gui.worker", str(self.file), self.out.path()]
        process.setArguments(arguments + ([str(self.library)] if self.library else []))
        process.setWorkingDirectory(self.out.path())
        process.setStandardOutputFile(QProcess.nullDevice())
        process.finished.connect(self._extracted)
        process.errorOccurred.connect(self._failed_to_start)
        self.process = process
        self.clock.start()
        process.start()
        self.busy.show()
        self.state_label.setText("Extracting…")
        self.statusBar().showMessage(f"Extracting {self.file.name}…")
        self._update()
        self._summary()

    def stop(self):
        """Stop an extraction under way; what it wrote so far is deleted with its folder."""
        process, self.process = self.process, None
        if process is None:
            return
        process.finished.disconnect()
        process.errorOccurred.disconnect()
        process.kill()
        process.waitForFinished(3000)
        process.deleteLater()
        self._forget()
        self.statusBar().showMessage("Extraction stopped; nothing was kept.", 5000)

    def _failed_to_start(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.process:
            self.process.deleteLater()
            self.process = None
            self._fail(f"{sys.executable}: {self.sender().errorString()}")

    def _extracted(self, code, status):
        process, self.process = self.process, None
        if process is None:
            return
        process.deleteLater()
        self.busy.hide()
        done = self.out and os.path.exists(self._output("design.ir.json"))
        if status != QProcess.ExitStatus.NormalExit or code != 0 or not done:
            lines = bytes(process.readAllStandardError()).decode(errors="replace").split("\n")
            why = next((line for line in reversed(lines) if line.strip()), "")
            self._fail(why.strip() or f"the extractor stopped with code {code}")
            return
        self.design = Design.load(self._output("design.ir.json"))
        self.review = json.loads(self._output("review.json").read_text())
        self._fill()
        self._summary()
        seconds = self.clock.elapsed() / 1000
        self.state_label.setText("Extracted")
        unknown = next((i for i in self.design.issues if i.kind == "no_profile"), None)
        if unknown or not self.design.components:
            why = (
                f"The PDF was not drawn by a tool schem2net reads (it says: {unknown.detail})."
                if unknown
                else "No component was found on any page."
            )
            self._error("Nothing extracted", f"{why} There is nothing to export.")
        else:
            self.statusBar().showMessage(
                f"Extracted in {seconds:.1f} s: check the issues and pin numbers."
            )
        self.report_page.allowed = QUrl.fromLocalFile(str(self._output("report.html")))
        self.web.load(self.report_page.allowed)
        self._update()

    def _fail(self, why):
        self._forget()
        self.state_label.setText("Extraction failed")
        self._error("Extraction failed", why)

    def _output(self, name) -> Path:
        return Path(self.out.path()) / name

    def _forget(self):
        """Drop the results shown, with the folder they were read from."""
        self.design, self.review, self.picked = None, [], None
        self.report_pages, self.report_index = [], None
        self.report_page.allowed = QUrl()
        self.web.setHtml("")
        for tree in (self.nets, self.parts, self.issues, self.properties):
            tree.clear()
        self.counts_label.clear()
        self.busy.hide()
        if self.out:
            self.out.remove()
            self.out = None
        if self.file:
            self.state_label.setText("Not extracted")
            if self.tabs.currentWidget() is self.web:
                self.tabs.setCurrentWidget(self.drawing)
        self._update()
        self._summary()

    def _fill(self):
        design = self.design
        self.pins = {(c.ref, p.num): p for c in design.components for p in c.pins}
        self.net_of = {tuple(pin): net for net in design.nets for pin in net.pins}
        self.guessed = {
            tuple(pin) for i in design.issues if i.kind == "pin_number_guessed" for pin in i.pins
        }
        for net in design.nets:
            item = Item([_net_name(net), str(len(net.pins)), f"{net.confidence:.2f}"])
            item.setData(0, KEY, net.id)
            item.setData(0, SORT, export._natural(_net_name(net)))
            item.setData(1, SORT, len(net.pins))
            item.setData(2, SORT, net.confidence)
            item.setIcon(0, _swatch(report.hue(net.id)))
            if net.confidence < LOW_CONFIDENCE:
                item.setForeground(2, QColor("#c62828"))
                item.setToolTip(2, "Joined on weak evidence: check this net")
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
            self.nets.addTopLevelItem(item)
        for k, part in enumerate(design.components):  # by index: a designator may repeat
            item = Item([part.ref, part.value or "", str(len(part.pins))])
            item.setData(0, KEY, str(k))
            item.setData(0, SORT, export._natural(part.ref))
            item.setData(2, SORT, len(part.pins))
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
            self.parts.addTopLevelItem(item)
        groups: dict[str, QTreeWidgetItem] = {}
        worst: dict[str, str] = {}
        for k, entry in enumerate(self.review):
            group = groups.get(entry["kind"])
            if group is None:
                group = QTreeWidgetItem([report.ISSUE_TEXT.get(entry["kind"], entry["kind"])])
                group.setData(0, KEY, None)
                group.setFirstColumnSpanned(True)
                groups[entry["kind"]] = group
                self.issues.addTopLevelItem(group)
                group.setExpanded(len(groups) <= report.OPEN_GROUPS)
            child = QTreeWidgetItem([entry["what"]])
            child.setData(0, KEY, str(k))
            child.setIcon(0, _severity_icon(entry["severity"]))
            child.setToolTip(0, entry["what"])
            group.addChild(child)
            if SEVERITY[entry["severity"]] >= SEVERITY[worst.get(entry["kind"], "info")]:
                worst[entry["kind"]] = entry["severity"]
        for kind, group in groups.items():
            group.setIcon(0, _severity_icon(worst[kind]))
            group.setText(0, f"{group.text(0)} ({group.childCount()})")
        self.counts_label.setText(
            f"{len(design.components)} components · {len(design.nets)} nets · "
            f"{len(design.issues)} issues"
        )
        self.nets_dock.setWindowTitle(f"Nets ({len(design.nets)})")
        self.parts_dock.setWindowTitle(f"Components ({len(design.components)})")
        self.issues_dock.setWindowTitle(f"Issues ({len(self.review)})")

    # Selection

    def _current(self, tree, item):
        if item is None or item.data(0, KEY) is None:
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self.fresh = item  # the click about to be reported made it current
        self._pick(tree, item.data(0, KEY))

    def _clicked(self, tree, item):
        """A second click on what is highlighted clears it."""
        fresh, self.fresh = self.fresh, None
        if item is fresh or item.data(0, KEY) is None:
            return
        if self.picked == (tree.property("kind"), item.data(0, KEY)):
            self.clear()
        else:
            self._pick(tree, item.data(0, KEY))

    def _pick(self, tree, key):
        kind = tree.property("kind")
        self.picked = (kind, key)
        for other in (self.nets, self.parts, self.issues):
            if other is not tree:
                other.blockSignals(True)
                other.setCurrentItem(None)
                other.clearSelection()
                other.blockSignals(False)
        if kind == "nets":
            net = next(n for n in self.design.nets if n.id == key)
            self._properties(self._net_properties(net))
            self._run(f"s2n.net({json.dumps(key)})")
        elif kind == "components":
            part = self.design.components[int(key)]
            self._properties(self._part_properties(part))
            if part.page and part.bbox:
                self._run(f"s2n.part({part.page}, {', '.join(f'{v:.3f}' for v in part.bbox)})")
            else:
                self._run("s2n.clear()")
                self.statusBar().showMessage(f"{part.ref}: where it is drawn is not known.", 5000)
        else:
            entry = self.review[int(key)]
            self._properties(self._issue_properties(entry))
            if entry["spots"]:
                self._run(f"s2n.mark({json.dumps(entry['id'])})")
            else:
                self._run("s2n.clear()")
        if self.report_pages:
            self.tabs.setCurrentWidget(self.web)

    def clear(self):
        self.picked = None
        for tree in (self.nets, self.parts, self.issues):
            tree.blockSignals(True)
            tree.setCurrentItem(None)
            tree.clearSelection()
            tree.blockSignals(False)
        self._summary()
        self._run("s2n.clear()")

    def find(self):
        for dock in (self.nets_dock, self.parts_dock, self.issues_dock):
            if dock.widget().isVisible():
                search = dock.widget().findChild(QLineEdit)
                search.setFocus()
                search.selectAll()
                return

    # Properties

    def _properties(self, rows):
        """Rows of (property, value) or (property, value, [(child, value)])."""
        self.properties.clear()
        for row in rows:
            item = QTreeWidgetItem([row[0], row[1]])
            item.setToolTip(1, row[1])
            for child in row[2] if len(row) > 2 else []:
                sub = QTreeWidgetItem(list(child))
                sub.setToolTip(1, child[1])
                item.addChild(sub)
            self.properties.addTopLevelItem(item)
            item.setExpanded(True)

    def _pin_text(self, ref, num, with_net=False) -> tuple[str, str]:
        pin = self.pins.get((ref, num))
        how = pin.how if pin else None
        text = HOW.get(how, f"inferred ({how})") if how else "not recorded"
        if (ref, num) in self.guessed:
            text = f"guessed ({how})" if how else "guessed"
        name = f"{pin.name} · " if pin and pin.name else ""
        net = ""
        if with_net:
            found = self.net_of.get((ref, num))
            net = f" · {_net_name(found)}" if found else " · no net"
        return f"{ref}.{num}", f"{name}{text}{net}"

    def _issues_of(self, pins) -> list[tuple[str, str]]:
        pins = {tuple(p) for p in pins}
        return [
            (report.ISSUE_TEXT.get(e["kind"], e["kind"]), e["what"])
            for e in self.review
            if pins & {tuple(p) for p in e["pins"]}
        ]

    def _net_properties(self, net: Net):
        evidence = [
            (e.type.replace("_", " "), f"{e.count}" + (f" ({e.label})" if e.label else ""))
            for e in sorted(net.evidence, key=lambda e: -e.count)
        ]
        confidence = f"{net.confidence:.2f}" + (
            " (low: check this net)" if net.confidence < LOW_CONFIDENCE else ""
        )
        rows = [
            ("Net", _net_name(net)),
            ("Confidence", confidence),
            ("Evidence", "" if evidence else "none", evidence),
        ]
        others = [n for n in net.names_seen if n != net.name]
        if others:
            rows.append(("Also named", ", ".join(others)))
        rows.append(("Pages", ", ".join(map(str, net.pages)) or "unknown"))
        rows.append((f"Pins ({len(net.pins)})", "", [self._pin_text(r, n) for r, n in net.pins]))
        issues = self._issues_of(net.pins)
        if issues:
            rows.append((f"Issues ({len(issues)})", "", issues))
        return rows

    def _part_properties(self, part):
        rows = [("Reference", part.ref), ("Value", part.value or "none read")]
        if part.symbol:
            rows.append(("Symbol", part.symbol))
        page = str(part.page) if part.page else "unknown"
        if len(part.units) > 1:  # the IR places a part by its first unit
            page += f" (first of units {', '.join(part.units)})"
        rows.append(("Page", page))
        pins = [self._pin_text(part.ref, p.num, with_net=True) for p in part.pins]
        rows.append((f"Pins ({len(pins)})", "", pins))
        issues = self._issues_of([(part.ref, p.num) for p in part.pins])
        if issues:
            rows.append((f"Issues ({len(issues)})", "", issues))
        return rows

    def _summary(self):
        """What is open and how it was read, shown while nothing is selected."""
        if not self.file:
            self.properties.clear()
            return
        rows = [("File", self.file.name), ("Pages", str(self.document.pageCount()))]
        design = self.design
        if design is None:
            rows.append(("Extraction", "running" if self.process else "not run"))
            self._properties(rows)
            return
        generator = design.source.generator
        rows.append(("Drawn with", GENERATORS.get(generator, generator)))
        if self.report_index is not None:
            pages = self.report_pages
            rows.append(
                (
                    "Nets read from",
                    f"the drawing, {len(pages)} of {design.source.pages} pages"
                    if pages
                    else "the netlist the PDF carries; not shown on the drawing"
                    if design.components
                    else "nothing",
                )
            )
        rows.append(("Part library", design.source.library or "none"))
        low = sum(n.confidence < LOW_CONFIDENCE for n in design.nets)
        rows += [
            ("Components", str(len(design.components))),
            ("Nets", f"{len(design.nets)}, {low} of low confidence"),
            ("To check", str(len(self.review))),
        ]
        self._properties(rows)

    def _issue_properties(self, entry):
        pages = sorted({page for page, _ in entry["spots"]})
        rows = [
            ("Issue", report.ISSUE_TEXT.get(entry["kind"], entry["kind"])),
            ("Severity", SEVERITY_TEXT.get(entry["severity"], entry["severity"])),
            ("About", entry["what"]),
            ("Where", ", ".join(f"page {p}" for p in pages) or "not marked on the drawing"),
        ]
        if entry["pins"]:
            pins = [self._pin_text(r, n, with_net=True) for r, n in entry["pins"]]
            rows.append((f"Pins ({len(pins)})", "", pins))
        return rows

    # Viewing

    def _run(self, code):
        if self.report_pages:
            self.web.page().runJavaScript(code, WORLD)

    def _report_title(self, title):
        """view.js names the page in view in the title: "s2n 2 of 1,2,5" for the third of
        the pages numbered 1, 2 and 5. Unlike a script result, nothing waits on it."""
        words = title.split()
        if len(words) != 4 or words[0] != "s2n" or not self.design:
            return
        loaded = self.report_index is None
        self.report_index = int(words[1])
        self.report_pages = [int(n) for n in words[3].split(",") if n.isdigit()]
        if loaded and not self.picked:
            self._summary()
        if loaded and self.report_pages:
            self.tabs.setCurrentWidget(self.web)
        elif loaded and self.design.components:  # parts found, yet no page read
            self.statusBar().showMessage(
                "The nets were read from the netlist this PDF carries, not from its drawing, "
                "so they cannot be shown on it."
            )
        self._update()

    def _report_crashed(self, status, code):
        if status == QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
            return
        self.statusBar().showMessage(f"The report view stopped (code {code}); reloading it.")
        self.picked, self.report_index = None, None
        self.web.reload()

    def _page_shown(self, index):
        if self.tabs.currentWidget() is self.drawing:
            self._show_page(index + 1)

    def _show_page(self, number):
        self.page_label.setText(f"Page {number} of {self.document.pageCount()}")

    def zoom(self, factor):
        if self.tabs.currentWidget() is self.web:
            self._run(f"s2n.zoomBy({factor})")
            return
        view = self.drawing
        bars = view.horizontalScrollBar(), view.verticalScrollBar()
        middle = [bar.pageStep() / 2 for bar in bars]
        spots = [bar.value() + m for bar, m in zip(bars, middle, strict=True)]
        self._zoom_drawing(factor, middle, spots)

    def _zoom_drawing(self, factor, at, spots):
        """Zoom the PDF, keeping the point at `at` in the view where it is."""
        view = self.drawing
        before = self._drawing_zoom()
        after = min(32.0, max(0.1, before * factor))
        view.setZoomMode(QPdfView.ZoomMode.Custom)
        view.setZoomFactor(after)
        k = after / before
        for bar, a, spot in zip(
            (view.horizontalScrollBar(), view.verticalScrollBar()), at, spots, strict=True
        ):
            bar.setValue(round(spot * k - a))

    def _drawing_zoom(self) -> float:
        """The zoom shown, which a fitting mode does not keep in zoomFactor."""
        view = self.drawing
        if view.zoomMode() == QPdfView.ZoomMode.Custom:
            return view.zoomFactor()
        page = self.document.pagePointSize(view.pageNavigator().currentPage())
        if page.isEmpty():
            return 1.0
        dpi = view.logicalDpiX() / 72
        margins = view.documentMargins()
        width = (view.viewport().width() - margins.left() - margins.right()) / (page.width() * dpi)
        height = (view.viewport().height() - margins.top() - margins.bottom()) / (
            page.height() * dpi
        )
        return min(width, height) if view.zoomMode() == QPdfView.ZoomMode.FitInView else width

    def fit(self):
        if self.tabs.currentWidget() is self.web:
            self._run("s2n.fit()")
        else:
            self.drawing.setZoomMode(QPdfView.ZoomMode.FitInView)

    def turn(self, step):
        if self.tabs.currentWidget() is self.web:
            self._run(f"s2n.page(s2n.current() + {step})")
            return
        navigator = self.drawing.pageNavigator()
        page = min(max(navigator.currentPage() + step, 0), self.document.pageCount() - 1)
        navigator.jump(page, QPointF(), navigator.currentZoom())

    def eventFilter(self, watched, event):
        # Ctrl and the wheel zoom the PDF about the pointer, as they do the nets.
        if (
            event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and watched is self.drawing.viewport()
        ):
            delta = event.angleDelta().y()
            if delta:
                at = event.position()
                bars = self.drawing.horizontalScrollBar(), self.drawing.verticalScrollBar()
                spots = [bars[0].value() + at.x(), bars[1].value() + at.y()]
                self._zoom_drawing(2 ** (delta / 480), [at.x(), at.y()], spots)
            return True
        return super().eventFilter(watched, event)

    # Exports

    def _export(self, label, pattern, suffix, write):
        if not self._exportable():
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {label}",
            str(self.folder / (_stem(self.file) + suffix)),
            f"{label} ({pattern});;All files (*)",
        )  # the dialog asks before replacing a file
        if not path:
            return
        if not Path(path).suffix:  # a name typed without one gets the format's
            path += suffix
            if Path(path).exists() and not self._replace(f"{path} already exists."):
                return
        try:
            write(self, Path(path))
        except OSError as e:
            self._error("Export failed", f"{path}: {e.strerror or e}")
            return
        self.folder = Path(path).parent
        self.statusBar().showMessage(f"Wrote {path}", 10000)

    def export_schematic(self):
        if not self._exportable():
            return
        source = self._output("kicad")
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a Folder for the KiCad Project", str(self.folder)
        )
        if not folder:
            return
        names = sorted(p.name for p in source.iterdir())
        existing = [n for n in names if (Path(folder) / n).exists()]
        if existing and not self._replace(
            f"{len(existing)} of the project's files are already in {folder}: "
            f"{', '.join(existing)}."
        ):
            return
        try:
            for name in names:
                part = Path(folder) / f".{name}.part"
                shutil.copyfile(source / name, part)
                os.replace(part, Path(folder) / name)
        except OSError as e:
            self._error("Export failed", f"{e.filename or folder}: {e.strerror or e}")
            return
        self.folder = Path(folder)
        self.statusBar().showMessage(
            f"Wrote {Path(folder) / (self.file.stem + '.kicad_pro')}", 10000
        )

    def choose_library(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a Part Library Index", str(self.library or self.folder)
        )
        if not folder:
            return
        if not any(library.path(Path(folder), kind).is_file() for kind in ("kicad", "eagle")):
            self._error(
                "Not a part library index",
                f"{folder} holds no index. Make one with: schem2net index-library LIBRARIES -o "
                "FOLDER",
            )
            return
        self._set_library(Path(folder))

    def _set_library(self, folder: Path | None):
        self.library = folder
        self.statusBar().showMessage(
            f"Part library {folder}: used from the next extraction."
            if folder
            else "No part library: used from the next extraction.",
            10000,
        )
        self._update()

    def _replace(self, why) -> bool:
        answer = QMessageBox.question(
            self,
            "Replace Files",
            f"{why} Replace?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _exportable(self) -> bool:
        design = self.design
        return bool(
            design
            and self.out
            and design.components
            and not any(i.kind == "no_profile" for i in design.issues)
        )

    # State

    def _update(self, *_):
        opened = self.file is not None
        running = self.process is not None
        for action in (self.zoom_in_action, self.zoom_out_action, self.fit_action):
            action.setEnabled(opened)
        pages = (
            self.document.pageCount()
            if self.tabs.currentWidget() is self.drawing
            else len(self.report_pages)
        )
        self.previous_action.setEnabled(opened and pages > 1)
        self.next_action.setEnabled(opened and pages > 1)
        self.extract_action.setEnabled(opened and not running)
        self.stop_action.setEnabled(running)
        exportable = self._exportable()
        for action in self.exports:
            action.setEnabled(exportable)
        self.schematic_action.setEnabled(exportable and self._output("kicad").is_dir())
        self.export_button.setEnabled(exportable)
        self.tabs.setTabEnabled(1, bool(self.report_pages) or self.tabs.currentWidget() is self.web)
        self.find_action.setEnabled(self.design is not None)
        carried = (
            self.design is not None and self.report_index is not None and not self.report_pages
        )
        self.tabs.setTabToolTip(
            1,
            "The nets came from the netlist this PDF carries; its drawing was not read."
            if carried
            else "",
        )
        self.no_library_action.setEnabled(self.library is not None)
        if not opened:
            self.page_label.clear()
        elif self.tabs.currentWidget() is self.drawing:
            self._show_page(self.drawing.pageNavigator().currentPage() + 1)
        elif self.report_pages:
            self._show_page(self.report_pages[min(self.report_index, len(self.report_pages) - 1)])

    def _error(self, title, text):
        box = QMessageBox(QMessageBox.Icon.Warning, title, text, parent=self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.exec()

    def about(self):
        box = QMessageBox(self)
        box.setWindowTitle("About schem2net")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(
            f"schem2net {__version__}\n\n"
            "Recovers netlists from vector schematic PDFs. An extracted netlist is a reading "
            "of the drawing: check it, and its pin numbers above all, before using it.\n\n"
            "Apache License 2.0\nhttps://github.com/rzadevv/schem2net"
        )
        box.exec()

    def showEvent(self, event):
        super().showEvent(event)
        if self.file is None:
            self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        self.stop()
        if self.out:  # the results shown; not left to object teardown at exit
            self.out.remove()
        super().closeEvent(event)


def _net_name(net: Net) -> str:
    return net.name or ", ".join(f"{r}.{p}" for r, p in net.pins[:3])


def _filter(tree: QTreeWidget, text: str):
    """Hide rows not containing the text; a group shows while any of its rows does."""
    text = text.strip().lower()
    for k in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(k)
        shown = 0
        group = item.childCount() and text in item.text(0).lower()
        for c in range(item.childCount()):
            child = item.child(c)
            hide = bool(text) and not group and text not in child.text(0).lower()
            child.setHidden(hide)
            shown += not hide
        texts = " ".join(item.text(c) for c in range(tree.columnCount())).lower()
        item.setHidden(bool(text) and (shown == 0 if item.childCount() else text not in texts))


def _dropped_pdf(event) -> Path | None:
    urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
    if len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith(".pdf"):
        return Path(urls[0].toLocalFile())
    return None


def _icon(name, fallback):
    icon = QIcon.fromTheme(name)
    if icon.isNull() and fallback is not None:
        icon = QApplication.style().standardIcon(fallback)
    return icon


def _swatch(hue: float) -> QIcon:
    pixmap = QPixmap(10, 10)
    pixmap.fill(QColor.fromHslF(hue / 360, 0.7, 0.42))
    return QIcon(pixmap)


def _severity_icon(severity: str) -> QIcon:
    sp = QStyle.StandardPixmap
    pixmap = {
        "error": sp.SP_MessageBoxCritical,
        "warn": sp.SP_MessageBoxWarning,
    }.get(severity, sp.SP_MessageBoxInformation)
    return QApplication.style().standardIcon(pixmap)


# Qt messages that say nothing about this application: the portal finding no
# schem2net.desktop when installed with pip, links in a PDF that QtPdf cannot follow,
# and focus changes Qt's Wayland text input reports. Everything else is printed.
HARMLESS = (
    "Failed to register with host portal",
    "link with invalid location",
    "skipping link with invalid page number",
    "QWaylandTextInputv3::",
)


def _qt_message(mode, context, message):
    if not any(known in message for known in HARMLESS):
        sys.stderr.write(qFormatLogMessage(mode, context, message) + "\n")


def application(argv: list[str]) -> QApplication:
    # PySide6 from PyPI carries its own Qt, without the desktop's theme plugins such as
    # KDE's; its portal theme still follows the desktop's choice of light or dark.
    themes = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "platformthemes"
    wanted = os.environ.get("QT_QPA_PLATFORMTHEME")
    if wanted and not any(themes.glob(f"*{wanted}*")):
        os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
    QApplication.setApplicationName("schem2net")
    QApplication.setApplicationVersion(__version__)
    QApplication.setDesktopFileName("schem2net")  # the Wayland app id
    qInstallMessageHandler(_qt_message)  # first, to cover startup
    app = QApplication(argv)
    if QIcon.themeName() in ("", "hicolor"):  # no icon theme found: use a common one
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        QIcon.setFallbackThemeName("breeze-dark" if dark else "breeze")
    return app


def main() -> None:
    app = application(sys.argv)
    window = Window()
    screen = app.primaryScreen().availableGeometry()
    window.resize(min(1600, int(screen.width() * 0.9)), min(1000, int(screen.height() * 0.9)))
    window.show()
    if len(sys.argv) > 1:
        window.open(Path(sys.argv[1]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
