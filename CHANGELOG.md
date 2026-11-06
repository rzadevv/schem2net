# Changelog

## Unreleased

- Add an optional desktop application, `schem2net-gui`, installed with the `gui` extra.

- Consolidate usage, architecture and development documentation while preserving
  frozen evaluation records and historical comparisons.
- Test the installed wheel and optional MCP workflow in CI.
- Keep untracked files and local tool settings out of source distributions.
- Disable automatic package publication pending learned-asset clearance.

- Nearby component references stay with bodies whose device values had displaced them.
- Glyph matching reuses scaled queries and computes endpoint distances with a compiled kernel.
- Bus labels follow bus geometry independently of their printed label colour.
- KiCad's additional gray palette restores visible unpopulated parts. Capacitor plates
  touching a separate closed body remain body graphics.

- Weak glyph reads consider matching outlines with different curve decompositions.
- Numbered pins reserve their printed names from unnumbered neighbours. Independent
  bodies retain their references during overlaid-part recovery.
- Connector references can replace weak part values without shifting neighbouring
  reference assignments.
- Repeated net names can label short wires outside component and pin bounds.

- Complete stacks of related connector names recover the separate overlaid parts.
- Matching dashed body borders reunite connector sections under their external
  reference and restore their printed pin numbers.

- Separate bodies meeting through pin tips no longer borrow each other's reference.
- Numbered pin fragments can follow an unbranched path to a wire and stay together
  through symbol splitting.
- A wire split at a plain crossing no longer shorts to the wire passing through it;
  T contacts, junction dots and shared endpoints keep their connections.
- Section borders containing independent parts are removed before symbol grouping,
  so their drawing order cannot pull nearby component marks into one large part.
- Conflicting voltage labels, including labels without power symbols, are reported
  with their net and affected pins; equivalent voltage spellings remain aliases.
- Library pin names stay names, and numbered or missing units no longer borrow an
  ambiguous pinout from another unit.
- PDF ingestion has its own page time budget, checks object counts before reading
  text, counts nested and discarded objects, and reports excessive form nesting.
- Schematic wire-label placement uses spatial searches instead of all wire pairs.
- Benchmark issues follow the same pin-name and symmetric-end alignment as nets;
  historical confidence and review metrics need rescoring. Comparisons reject
  runs with different design sets.
- A file of more than 1,000 pages is refused, and a page past 1.5 million drawing
  objects or twenty minutes of reading is reported as failed; dense pages read faster.
- A profile with a section, key or colour role it does not know is an error.
- An Eagle part named by what it does, such as HDMI, keeps that name over its part
  number printed nearer, where the designator model finds the name likelier.
- EasyEDA net labels marked by a dot are paired with their dots as a whole, so rows of
  labels set close together no longer shift by one onto their neighbours' wires.
- A net label joins the power symbol or global label of its name on its page.
- In Eagle and EasyEDA, a ground's or flag's name printed over a wire passing beyond it
  names the sign instead of labelling that wire.
- Texts in a theme colour no profile knows are judged together, one kind of text to a
  colour, so a theme's net labels are no longer read in part as fields.
- OrCAD off-page connectors take the name drawn right after them, though it sits
  farther off than a name found by distance alone.
- KiCad hierarchical labels connect on their flag's centre line, which the text's box
  can miss by a fraction of a millimetre.
- A wire ending on KiCad's PWR_FLAG is no dangling wire.
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
