# Changelog

## 0.2.0

- Part libraries are read only from a folder given with `--library` or
  `SCHEM2NET_LIBRARY`; `index-library` writes to a folder named with `-o`.
- A run that finds no part exits with 3 and writes nothing; `--strict` does the
  same when a page cannot be read.
- A pin known only by a name drawn beside it, or by a transistor's role, is kept
  unnumbered with that name, so the KiCad netlist no longer gives it a pad such as G.
- Eagle buses are read, so wires ending on them are no longer reported dangling.
- Text turned upside down is read; dashed lines are never wires.
- Pin numbers are paired with pins as a whole, and rows filled from how they count.
- Test results in the README are on new splits that keep revisions of a board
  together, with 95% intervals.

## 0.1.0

First release. Reads KiCad, Altium, Eagle, EasyEDA and OrCAD Capture schematic
PDFs, including pages printed in black, into a netlist with a confidence for every
net and a list of things to check. Writes JSON, a KiCad netlist or project, a bill
of materials, SPICE, an HTML report, and serves a design over MCP. Results on six
benchmark corpora are in the README.
