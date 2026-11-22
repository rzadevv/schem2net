"""Bus names and the member nets they stand for.

A vector bus `D[0..7]` carries the nets D0 to D7, matched by position when
it crosses into another sheet. A group bus `I2C{SCL SDA}` carries I2C.SCL and
I2C.SDA, matched by member name. A group can also name an alias, `I2C{BUS}`,
whose members are defined outside the drawing; its members are then taken
from the labels that use its prefix. A bare alias, `{BUS}`, takes the alias
name as its prefix: BUS.SCL.
"""

import re
from dataclasses import dataclass

from schem2net.scene import name_key

VECTOR = re.compile(r"^(.*?)\[(\d+)\.\.(\d+)\]$")
GROUP = re.compile(r"^(.*?)\{(.*)\}$")
MAX_VECTOR_MEMBERS = 10_000  # bound expansion of a short range declaration


class LimitError(ValueError):
    """A bus declaration cannot be expanded within the reader's limits."""


@dataclass(frozen=True)
class Bus:
    prefix: str
    members: tuple[str, ...] | None  # None for an alias
    vector: bool

    @property
    def separator(self) -> str:
        return "." if self.prefix and not self.vector else ""


def parse(name: str) -> Bus | None:
    """The bus a name stands for, or None for a plain net name."""
    if m := VECTOR.match(name):
        try:
            first, last = int(m[2]), int(m[3])
        except ValueError:
            raise LimitError("vector bus endpoints exceed integer conversion limits") from None
        first, last = sorted((first, last))
        if last - first + 1 > MAX_VECTOR_MEMBERS:
            raise LimitError(f"vector bus range exceeds {MAX_VECTOR_MEMBERS} members")
        return Bus(name_key(m[1]), tuple(str(i) for i in range(first, last + 1)), True)
    if m := GROUP.match(name):
        prefix, inner = name_key(m[1]), m[2].split()
        if len(inner) > 1:
            return Bus(prefix, tuple(name_key(n) for n in inner), False)
        return Bus(prefix or name_key(m[2]), None, False)
    return None


def member_nets(bus: Bus, page_names: set[str]) -> dict[str, str]:
    """Net name of each member, keyed by position for vectors and by name for groups."""
    if bus.vector:
        return {str(k): bus.prefix + m for k, m in enumerate(bus.members)}
    start = bus.prefix + bus.separator
    members = bus.members
    if members is None:
        members = [n[len(start) :] for n in page_names if start and n.startswith(start)]
    return {m: start + m for m in members}
