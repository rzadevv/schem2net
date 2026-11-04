# Independent release evaluation: registered protocol

Registered before any extraction or scoring of the new panel. The extractor is
frozen at `5d2417c3bd93559255ccf40aee803411f841af24`; subsequent commits may add
evaluation tools and reports, but cannot change that candidate. No accuracy
changes are authorized by this experiment. Preserve every outcome and require a
fresh panel for any revised candidate's independent release claim.

## Implementations and configuration

Compare the pre-improvement audit baseline
`152c85a229be37fba9822fc2bbb6ee163b596749`, recent development baseline
`1934cda524831556ac42b570914274abe1e51660`, and frozen candidate. Use Python
3.13.15 and the same locked dependencies, one isolated subprocess per design.
Use the built installed candidate wheel; historical implementations come from
immutable Git archives in the same dependency environment. All five bundled
learned assets are byte-identical across these commits.

`profile.use_learned(None)` **restores the bundled models**, rather than disabling
learning. Their loaders cache by asset path. Confirm installed paths and hashes
before extraction; never use development fold models or retrain anything.

Primary extraction is `pipeline.extract(pdf, embedded=False, library_dir=None)`.
Secondary extraction uses the same two frozen KiCad/Eagle library indexes from
the initial audit, for every implementation and eligible design. It must be
reported separately. No library built from new panel sources may be supplied to
the predictor. Record exact hashes in the freeze manifest. Clear
`SCHEM2NET_LIBRARY` and other local overrides in subprocesses. Do not crop pages,
change confidence thresholds, repair predictions, or use carried PDF netlists
as predictions. Default confidence cutoff is 0.8, an evidence weight rather than
a calibrated probability.

Use **candidate** `schem2net.bench.score` for all predictions, including historical
ones; the older scorer had reconciliation bugs. Truth is parsed with the frozen
KiCad netlist reader. Count connected truth nets of at least two distinct pins;
retain singletons and component pin lists for extra-pad checks. Include hidden
and visible unpopulated terminals when connected in the source truth. Do not
remove difficult nets, power nets, or missing components. The existing scorer
excludes named power nets from connection-pair F1, but includes them in overall
pin accuracy and exact nets. Symmetric passive ends and unique pin-name aliases
are reconciled as the frozen scorer specifies. Report this scope explicitly.

## Panel and pairing

Aim for at least 60 verified designs and 40 independent source groups across
KiCad, Eagle, Altium, EasyEDA and OrCAD. Discover public sources without observing
extractor outputs. Exclude every repository in all seven old corpus manifests
and every prior benchmark cache remote, their forks, ports and known circuit
families. Conservatively group by source owner and merge known related families.
Exclude owners already represented in that exclusion ledger. Inspect source
provenance for copied boards even if GitHub does not label the repository a fork.

Record all attempted sources and inclusion/quarantine reasons before extraction.
Within repositories, consider root schematics in lexical path order, at most two
distinct circuits per repository. Child sheets, templates, software fixtures,
library examples, and source ports of excluded designs do not count as designs.
Near-identical revisions share a group and do not inflate circuit diversity.
Truth-only duplicate checks may exclude exact copies before panel sealing.

Preferred pairing proof is PDF and netlist freshly exported from the **same
unchanged root source**, pinned revision and pinned KiCad image. This proves
pairing, but only measures that generated export style; it does not establish
coverage of original historical native PDFs. Archive export logs and reject
missing sheets/symbols or incomplete exports. Published native PDFs require
source correspondence beyond co-location: exact revision/variant plus matching
reference/pin/net or geometric evidence. PDF-carried source netlists may verify
truth, with board cross-check where available, while embedded prediction stays
disabled. Quarantine any unresolved mismatch, missing source, incomplete CAD
import, or ambiguous variant **before accuracy inspection**. Never replace missing
coverage with unverifiable pairs. Existing OpenLog files and scores stay intact.

Seal a manifest with source revision, original paths, source/download hashes,
PDF/truth hashes, generator, group, verification evidence and inclusion decision.
Record actual sample and generator coverage. Fewer than 60 designs/40 groups or
missing generator coverage makes broad release evidence incomplete, even if
observed scores look good. The panel is a purposive public-source sample, not a
random sample of all schematics.

## Outcomes and uncertainty

Save complete predictions, issues, raw Counts, per-design and per-generator
metrics, and pooled and macro summaries. Report pin accuracy, missing/wrong/
silent-wrong/extra pin rates, exact nets, signal-pair weighted and macro F1,
component precision/recall, value accuracy, net and pin flagging recall, review
precision and items per 100 truth pins, page failures and whole-design failures.
Wrong-pin rate is `pins_wrong / pins`; silent wrong excludes issue-named or
low-confidence wrong pins as the frozen scorer defines. Extras count numbered
pins on known true references, so separately enumerate unsupported references
and raw numbered pins on unknown components.

Use paired **source-group** bootstrap with 2,000 resamples, seed 0, and 95%
percentile intervals via frozen `compare`/`intervals`. Keep all designs in a group
together. Provide candidate absolute intervals and candidate-minus-baseline
intervals for both baselines, primary and secondary, aggregate and by generator
where defined. One-group generator intervals are descriptive and uninformative.
Do not treat an interval crossing a margin as proof of equivalence.

For every candidate high-confidence wrong connection or extra physical identity,
save raw/aligned pin and net evidence. Adjudicate newly introduced cases against
the PDF and CAD after scoring. Distinguish physical shorts, unsupported reference
or pad identities, missing fragments, and Hungarian/symmetric-alignment effects.
Do not silently relabel scorer errors as proven physical shorts. Unresolved
high-confidence identity cases prevent a positive gate claim.

## Acceptance gates (unchanged from reliability plan)

Apply to the primary comparison against both baselines:

* Zero failed pages and zero whole-design extraction failures.
* Pin-accuracy change: paired 95% lower bound at least zero.
* Silent-error-rate and extra-pin-rate changes: upper bounds at most zero.
* No newly introduced unsupported high-confidence physical identity after review.
* Median paired CPU and wall time ratios at most 1.05 against the recent baseline.
* No increase exceeding 1 review item per 100 truth pins unless pin flagging
  recall improves by at least 1 percentage point. Report intervals for both;
  uncertainty spanning the permitted tradeoff is inconclusive.

F1, exact nets, components and missing pins are mandatory reported outcomes,
not substitute gates. Secondary library results cannot rescue failed primary
gates. A significant adverse change fails; intervals that cannot establish a
required bound are inconclusive. Failure of any gate or insufficient panel
coverage prevents claiming these criteria were met. Sample targets do not
guarantee statistical power. No claim of unattended production reliability.

## Execution and release checks

Run each implementation/configuration once per sealed design in a fresh process;
use identical deterministic order, rotate implementation order by design to
reduce warm-cache bias, and cap concurrent extraction at two. Archive wall time,
process CPU time and Linux peak RSS for every attempt. A 1,800-second outer
subprocess timeout and 4 GiB address-space ceiling apply equally; timeout, crash,
or memory failure remains in results as a failed design and all connected truth
pins missed. No retry or omission on account of poor output. Report these limits
alongside the application's separate 1,200-second soft per-stage page budgets.

After the accuracy experiment, use pre-existing synthetic fixtures for CLI,
export, MCP, malformed-input and determinism checks; repeat extraction only for
explicit non-accuracy determinism checks, not to select a better prediction.
Validate wheel/sdist installation and the Python 3.11/3.14 CI matrix. Native
Windows/macOS behavior remains unvalidated on this Linux host; POSIX signals
cannot interrupt an unreturned PDFium native call and do not protect worker
threads or platforms without interval timers. No hard in-process memory limit.

Investigate learned-asset source licenses and notices without assuming that
Apache metadata alone clears every asset, or that model measurements necessarily
inherit a source license. Unresolved redistribution rights must be stated as a
distribution blocker requiring review. Preserve useful assets and required
notices. Do not publish or push anything.
