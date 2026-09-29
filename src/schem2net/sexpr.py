"""Minimal S-expression reader for KiCad files."""

import re

Node = list  # a node is [head, *children]; leaves are strings

_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))')
_ESCAPE = re.compile(r"\\(.)")


def parse(text: str) -> Node:
    stack: list[Node] = [[]]
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise ValueError(f"unexpected input at offset {pos}")
        pos = match.end()
        opening, closing, quoted, atom = match.groups()
        if opening:
            stack.append([])
        elif closing:
            if len(stack) < 2:
                raise ValueError(f"unbalanced ')' at offset {match.start(2)}")
            node = stack.pop()
            stack[-1].append(node)
        elif quoted is not None:
            stack[-1].append(_ESCAPE.sub(r"\1", quoted))
        else:
            stack[-1].append(atom)
    if len(stack) != 1 or len(stack[0]) != 1:
        raise ValueError("expected exactly one top-level expression")
    return stack[0][0]


def children(node: Node, head: str) -> list[Node]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def child(node: Node, head: str) -> Node | None:
    found = children(node, head)
    return found[0] if found else None


def value(node: Node, head: str, default: str | None = None) -> str | None:
    found = child(node, head)
    if found is None or len(found) < 2 or isinstance(found[1], list):
        return default
    return found[1]
