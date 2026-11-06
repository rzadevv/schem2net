"""The desktop application, installed with the gui extra."""


def main() -> None:
    try:
        from schem2net.gui import app
    except ImportError as e:
        raise SystemExit(
            f"schem2net-gui: {e}. Install the desktop application with the gui extra: "
            "pip install 'schem2net[gui]'"
        ) from None
    app.main()
