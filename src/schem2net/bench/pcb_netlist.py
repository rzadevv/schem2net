"""Write the netlist of a board file, as ground truth for its schematic PDF.

Runs under KiCad's own Python (inside the benchmark Docker image), which can
load Altium and other PCB formats. Every pad knows its part, number and net,
so the board gives the same connectivity as the schematic it was built from.

    python3 pcb_netlist.py board.PcbDoc truth.net
"""

import sys

import pcbnew


def quote(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def main(board_path, out_path):
    kind = pcbnew.PCB_IO_MGR.FindPluginTypeFromBoardPath(board_path)
    board = pcbnew.PCB_IO_MGR.FindPlugin(kind).LoadBoard(board_path, None)

    components, nets = [], {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        pads = sorted({pad.GetNumber() for pad in fp.Pads() if pad.GetNumber()})
        if not ref or not pads:
            continue
        pins = " ".join(f"(pin (num {quote(p)}))" for p in pads)
        part = fp.GetFPID().GetLibItemName()
        components.append(
            f"(comp (ref {quote(ref)}) (value {quote(fp.GetValue())}) "
            f'(libsource (lib "pcb") (part {quote(part)})) (units (unit (pins {pins}))))'
        )
        for pad in fp.Pads():
            if pad.GetNetname() and pad.GetNumber():
                nets.setdefault(pad.GetNetname(), set()).add((ref, pad.GetNumber()))

    lines = ['(export (version "E")', "(components"] + components + [")", "(nets"]
    for code, (name, nodes) in enumerate(sorted(nets.items()), 1):
        body = " ".join(f"(node (ref {quote(r)}) (pin {quote(p)}))" for r, p in sorted(nodes))
        lines.append(f'(net (code "{code}") (name {quote(name)}) {body})')
    lines += [")", ")"]
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
