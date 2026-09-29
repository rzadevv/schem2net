"""Draw extracted primitives as SVG, for checking extraction by eye."""

from html import escape

from schem2net.primitives import Color, Page, Text


def render(page: Page) -> str:
    w, h = page.width, page.height
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {h:.2f}" '
        f'width="{w:.2f}mm" height="{h:.2f}mm">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for path in page.paths:
        stroke = _css(path.stroke) if path.stroke else "none"
        fill = _css(path.fill) if path.fill else "none"
        width = max(path.width, 0.05)
        for sub in path.subpaths:
            points = " ".join(f"{x:.3f},{y:.3f}" for x, y in sub)
            out.append(
                f'<polyline data-id="{path.id}" points="{points}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{width:.3f}"/>'
            )
    for text in page.texts:
        out.append(_text(text))
    out.append("</svg>")
    return "\n".join(out)


def _text(text: Text) -> str:
    x0, y0, x1, y1 = text.bbox
    baseline_start = {90: (x1, y1), 180: (x1, y0), 270: (x0, y0)}
    x, y = baseline_start.get(round(text.angle) % 360, (x0, y1))
    color = _css(text.color) if text.color else "black"
    rotate = f"rotate({-text.angle:.1f} {x:.3f} {y:.3f})"
    return (
        f'<text data-id="{text.id}" x="{x:.3f}" y="{y:.3f}" font-size="{text.size:.2f}" '
        f'font-family="sans-serif" fill="{color}" transform="{rotate}">{escape(text.text)}</text>'
    )


def _css(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)
