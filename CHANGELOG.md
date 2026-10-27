# Changelog

## Unreleased

- A file of more than 1,000 pages is refused, and a page past 1.5 million drawing
  objects or twenty minutes of reading is reported as failed; dense pages read faster.
- A profile with a section, key or colour role it does not know is an error.
- An Eagle part named by what it does, such as HDMI, keeps that name over its part
  number printed nearer, where the designator model finds the name likelier.
- EasyEDA net labels marked by a dot are paired with their dots as a whole, so rows of
  labels set close together no longer shift by one onto their neighbours' wires.
- The benchmark forgives swapped ends of a resistor or capacitor whose neighbours are
  swapped too, as in a chain of them, as its rules say.

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
- Eagle and EasyEDA parts drawn touching, such as a supply sign on a pin, are told
  apart by a learned model.
- A part drawn over itself with a name for each copy, as alternatives for one place,
  is read as one part per name.
- A list of sheets written after a net name without brackets is no part of the name.
- Test results in the README are on new splits that keep revisions of a board
  together, with 95% intervals.

## 0.1.0

First release. Reads KiCad, Altium, Eagle, EasyEDA and OrCAD Capture schematic
PDFs, including pages printed in black, into a netlist with a confidence for every
net and a list of things to check. Writes JSON, a KiCad netlist or project, a bill
of materials, SPICE, an HTML report, and serves a design over MCP. Results on six
benchmark corpora are in the README.
