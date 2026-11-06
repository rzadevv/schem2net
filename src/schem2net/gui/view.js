// Run by the desktop application in its own script world over the page `schem2net
// report` writes. It relies on that page's markup only: net entries `aside
// li[data-net]`, review entries `li[data-mark]` and one `main section` holding an svg
// per page read. Selection itself is left to the page's own click handlers.
"use strict";

const css = document.createElement("style");
css.textContent = `
  body { display: block; height: auto; }
  aside { display: none; }
  main { overflow: visible; padding: 8px 12px; }
  section { margin-bottom: 12px; }
  h2 { margin: 0 0 6px; font-size: 12px; }
  main svg { display: block; margin: 0 auto; }
  .s2n-part { fill: none; stroke: var(--fg); stroke-width: 0.4; }
`;
document.head.append(css);

const s2n = {
  zoom: 1,

  svgs: () => [...document.querySelectorAll("main section svg")],

  // Page numbers of the pages shown, in order.
  pages() {
    return s2n.svgs().map((svg) => +svg.getAttribute("aria-label").split(" ")[1]);
  },

  // Size each page to fit the window, times the zoom.
  layout() {
    const across = innerWidth - 24;
    const down = innerHeight - 40;
    for (const svg of s2n.svgs()) {
      const [, , w, h] = svg.getAttribute("viewBox").split(" ").map(Number);
      const fit = Math.min(across / w, down / h) * s2n.zoom;
      svg.style.width = `${w * fit}px`;
      svg.style.height = `${h * fit}px`;
    }
  },

  // Zoom by a factor, keeping the point at (x, y) in the window where it is.
  zoomBy(factor, x = innerWidth / 2, y = innerHeight / 2) {
    const before = s2n.zoom;
    s2n.zoom = Math.min(32, Math.max(0.25, before * factor));
    const k = s2n.zoom / before;
    const left = scrollX + x;
    const top = scrollY + y;
    s2n.layout();
tell();
    scrollTo(left * k - x, top * k - y);
  },

  // Whole pages at the window's size.
  fit() {
    const page = s2n.current();
    s2n.unzoom();
    s2n.zoom = 1;
    s2n.layout();
tell();
    s2n.page(page);
  },

  unzoom() {
    for (const svg of s2n.svgs()) {
      if (svg.dataset.full) svg.setAttribute("viewBox", svg.dataset.full);
    }
  },

  page(index) {
    const svgs = s2n.svgs();
    if (svgs.length) svgs[Math.max(0, Math.min(index, svgs.length - 1))].parentElement.scrollIntoView();
  },

  // Index of the page filling the middle of the window.
  current() {
    let index = 0;
    s2n.svgs().forEach((svg, k) => {
      if (svg.parentElement.getBoundingClientRect().top < innerHeight / 2) index = k;
    });
    return index;
  },

  // Back to no selection and whole pages; the page's own handler clears a net.
  clear() {
    document.querySelector("aside li[data-net].on")?.click();
    document.querySelectorAll(".mark.on, li[data-mark].on").forEach((e) => e.classList.remove("on"));
    document.querySelectorAll(".s2n-part").forEach((e) => e.remove());
    s2n.unzoom();
    s2n.layout();
tell();
  },

  net(id) {
    s2n.clear();
    document.querySelector(`aside li[data-net="${CSS.escape(id)}"]`)?.click();
  },

  // A review entry: the page's handler zooms its drawing to the spot.
  mark(id) {
    s2n.clear();
    document.querySelector(`li[data-mark="${CSS.escape(id)}"]`)?.click();
    s2n.zoom = 1;
    s2n.layout();
tell();
    document.getElementById(id)?.ownerSVGElement.scrollIntoView({ block: "center" });
  },

  // A part's outline, zoomed to as the page zooms to a review entry.
  part(page, x0, y0, x1, y1) {
    s2n.clear();
    const svg = document.querySelector(`main svg[aria-label="Page ${page}"]`);
    if (!svg) return;
    const box = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    box.setAttribute("class", "s2n-part");
    box.setAttribute("x", x0 - 1);
    box.setAttribute("y", y0 - 1);
    box.setAttribute("width", x1 - x0 + 2);
    box.setAttribute("height", y1 - y0 + 2);
    svg.append(box);
    const w = Math.max(80, 1.6 * (x1 - x0));
    const h = Math.max(55, 1.6 * (y1 - y0));
    svg.dataset.full = svg.dataset.full || svg.getAttribute("viewBox");
    svg.setAttribute("viewBox", `${(x0 + x1 - w) / 2} ${(y0 + y1 - h) / 2} ${w} ${h}`);
    s2n.zoom = 1;
    s2n.layout();
tell();
    svg.scrollIntoView({ block: "center" });
  },
};

// The application reads which page is in view from the title, "s2n 2 of 1,2,5", or
// "s2n 0 of -" when no page is shown.
const tell = () => {
  document.title = `s2n ${s2n.current()} of ${s2n.pages().join(",") || "-"}`;
};
addEventListener("scroll", tell, { passive: true });
addEventListener("resize", () => s2n.layout());
// The page restores a whole page on double-click; size it again after.
addEventListener("dblclick", () => s2n.layout());
addEventListener(
  "wheel",
  (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    s2n.zoomBy(Math.exp(-e.deltaY / 400), e.clientX, e.clientY);
  },
  { passive: false },
);
s2n.layout();
tell();
