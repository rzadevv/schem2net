"""Netlists that a PDF carries in its bookmarks.

Altium's Smart PDF export can include net information: a "Components" list,
and a "Nets" list in which every net has a "Pins" entry listing pins as
REF-PIN, such as C1-2. When it is there it is exact, so it is used as is.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

from schem2net.ir import Component, Design, Evidence, Net, Pin, Source


@dataclass
class _Node:
    title: str
    children: list["_Node"] = field(default_factory=list)


def read(file: str | Path, source: Source) -> Design | None:
    """The netlist in the file's bookmarks, or None if it has none."""
    pdf = pdfium.PdfDocument(file)
    try:
        outline = [(item.level, item.get_title()) for item in pdf.get_toc(max_depth=32)]
    finally:
        pdf.close()
    return from_outline(outline, source)


def from_outline(outline: Iterable[tuple[int, str]], source: Source) -> Design | None:
    """The netlist in a bookmark outline given as (level, title) pairs."""
    tree = _tree(outline)
    refs = {c.title for node in _find(tree, "Components") for c in node.children}
    members: dict[str, set[tuple[str, str]]] = {}
    for nets in _find(tree, "Nets"):
        for net in nets.children:
            for pins in (c for c in net.children if c.title == "Pins"):
                for pin in pins.children:
                    split = _split(pin.title, refs)
                    if split:
                        members.setdefault(net.title, set()).add(split)
    if not members:
        return None

    parts: dict[str, list[str]] = {ref: [] for ref in refs}
    for pins in members.values():
        for ref, num in pins:
            parts.setdefault(ref, []).append(num)
    components = [
        Component(ref=ref, pins=[Pin(num=n) for n in sorted(set(nums))])
        for ref, nums in sorted(parts.items())
    ]
    nets = [
        Net(
            id=f"n{i}",
            name=name,
            names_seen=[name],
            pins=sorted(pins),
            evidence=[Evidence(type="bookmarks", count=len(pins))],
        )
        for i, (name, pins) in enumerate(sorted(members.items()), 1)
    ]
    return Design(source=source, components=components, nets=nets)


def _tree(outline: Iterable[tuple[int, str]]) -> _Node:
    root = _Node("")
    stack = [(-1, root)]
    for level, title in outline:
        node = _Node(title)
        while stack[-1][0] >= level:
            stack.pop()
        stack[-1][1].children.append(node)
        stack.append((level, node))
    return root


def _find(node: _Node, title: str):
    for child in node.children:
        if child.title == title:
            yield child
        else:
            yield from _find(child, title)


def _split(text: str, refs: set[str]) -> tuple[str, str] | None:
    """Split "C1-2" into designator and pin, preferring a known designator."""
    known = [r for r in refs if text.startswith(r + "-")]
    if known:
        ref = max(known, key=len)
        return ref, text[len(ref) + 1 :]
    ref, _, pin = text.partition("-")
    return (ref, pin) if ref and pin else None
