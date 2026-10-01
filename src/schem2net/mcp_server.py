"""MCP server exposing one extracted design to agents, read only.

Needs the optional dependency: pip install "schem2net[mcp]".
"""

from mcp.server.mcpserver import MCPServer

from schem2net.ir import Design
from schem2net.query import Query

INSTRUCTIONS = """\
Answers questions about a schematic whose netlist was extracted from its PDF.
Pins are written as REF.NUMBER, for example U3.14. Every net carries a
confidence between 0 and 1; nets below 0.8 were joined by a guess and are
worth checking against the drawing.
"""


def build(design: Design) -> MCPServer:
    query = Query(design)
    server = MCPServer("schem2net", instructions=INSTRUCTIONS)

    @server.tool()
    def list_components(prefix: str = "") -> list[dict]:
        """List parts, optionally only those whose designator starts with a prefix such as "U"."""
        return query.components_list(prefix)

    @server.tool()
    def get_net(name_or_pin: str) -> dict | None:
        """Get a net by name ("GND") or by one of its pins ("U3.14")."""
        return query.net(name_or_pin)

    @server.tool()
    def pins_of(ref: str) -> list[dict] | None:
        """List a part's pins and the net each one is on."""
        return query.pins_of(ref)

    @server.tool()
    def trace(pin: str, depth: int = 2) -> list[dict] | None:
        """Follow a pin's net through series resistors, capacitors and inductors."""
        return query.trace(pin, depth)

    @server.tool()
    def low_confidence() -> list[dict]:
        """Nets that were joined by a guess and should be checked against the drawing."""
        return query.low_confidence()

    @server.tool()
    def issues(kind: str = "") -> list[dict]:
        """Problems the checks found, such as two power nets joined or a pin on no net.
        Pass a kind, such as "power_nets_merged", to see only those."""
        return query.issues(kind)

    @server.tool()
    def bom() -> list[dict]:
        """Parts grouped by value."""
        return query.bom()

    return server
