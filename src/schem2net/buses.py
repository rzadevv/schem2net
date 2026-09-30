"""Bus names and the member nets they stand for.

A vector bus `D[0..7]` carries the nets D0 to D7, matched by position when
it crosses into another sheet. A group bus `I2C{SCL SDA}` carries I2C.SCL and
I2C.SDA, matched by member name. A group can also name an alias, `I2C{BUS}`,
whose members are defined outside the drawing; its members are then taken
from the labels that use its prefix.
"""

import re
from dataclasses import dataclass

from schem2net.scene import name_key

VECTOR = re.compile(r"^(.*?)\[(\d+)\.\.(\d+)\]$")
GROUP = re.compile(r"^(.*?)\{(.*)\}$")


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
        first, last = int(m[2]), int(m[3])
        step = 1 if last >= first else -1
        return Bus(name_key(m[1]), tuple(str(i) for i in range(first, last + step, step)), True)
    if m := GROUP.match(name):
        inner = m[2].split()
        members = tuple(name_key(n) for n in inner) if len(inner) > 1 else None
        return Bus(name_key(m[1]), members, False)
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
