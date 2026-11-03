# Task-selection benchmark results

This page tracks how well `discover` ranks the issues an outside contributor
then lands. Method, label definitions and limits are in the
[harness README](../tools/benchmark/README.md). Rankings are heuristics and never
approval; these numbers measure them, not the protocol's safety gates.

## Withdrawn first results (format 1 harness)

The baseline and the first held-out experiment published on 2026-11-02 and
2026-11-03 used the format 1 harness. They are **withdrawn**: a hostile
methodology review (BM-01 to BM-06) found flaws that could bias them. The
flaws were:

- positives that included fixes already in flight at T;
- PR membership at T not reconstructed;
- missing close reasons and unknown authorship treated as known;
- references made after the horizon counted;
- a condensed top-k that removed outcome-excluded slots;
- a mislabelled bootstrap;
- replays that could silently shrink the issue set.

One stated claim was also wrong. `--signals` precision@20 (0.02, interval
0.00–0.05) did not overlap the 0.06 random mean, contrary to the text, and
overlap would not have shown equivalence to random anyway.

Their qualitative finding was that default ranking's oldest-first tie-break put
no later-positive issue in its top 20. That finding is re-tested below under the
corrected harness; it is not carried over.

## Pre-registered protocol: expanded corpus (registered 2026-11-03, before collection)

This was written and committed before the new snapshots were collected or any
variant was scored on them. Nothing below changes after results are seen.

- **Question.** Does variant (d), the most-recent-activity tie-break, beat random
  on repositories it was not tuned on?
- **Tuning set.** The four original snapshots above (cutoff 2026-03-01). They are
  already known and are not used for the decision.
- **Test set.** Eight new repositories at two cutoffs each, 2025-09-01 and
  2026-03-01, 90-day horizon, giving 16 snapshots. They are counted as they
  come, whatever their positive counts.
  - Python: `encode/httpx`, `pydantic/pydantic`
  - JavaScript: `expressjs/express`, `axios/axios`
  - Rust: `clap-rs/clap`, `sharkdp/bat`
  - Go: `spf13/cobra`, `junegunn/fzf`

  A snapshot that cannot be collected within the read budget is reported as
  missing, not replaced.
- **Collection.**
  - Read-only, through `collect.py`: `--max-issues 150` (most recently created
    first), `--max-search-pages 5`, `--horizon-days 90`.
  - Total budget about 3000 reads. Collection stops early rather than let the
    core rate limit fall below 1000.
  - Snapshots go into `tools/benchmark/data/` while the committed total stays
    under about 2 MB; the rest are kept under the validation-runs directory and
    listed here.
- **Labels.** The scoring labels above, with fixes already in flight at T
  excluded. The raw labels are reported as a secondary result.
- **Variants.** (a) default, (b) `--signals`, (d) recent-activity tie-break.
- **Metric.** Pooled precision@k: the mean over test snapshots that have at least
  one positive, each snapshot one unit. Intervals are 95% percentile bootstraps,
  2000 replicates, seed 0, with the random reference resampled the same way.
- **Decision rule.** (d) qualifies only if its test-set precision@10 interval
  lies wholly above the random interval. Precision@5 is reported, but it is
  secondary and cannot qualify (d) on its own. If (d) does not qualify, no
  ranking change is made.
- **Known dependence.** Two cutoffs of the same repository share maintainers and
  habits, so the intervals are optimistic about independence.

## Amendment to the pre-registration (2026-11-03, before any collection or scoring)

The hostile review (BM-01 to BM-06) arrived after registration and before any
test snapshot was collected or scored. These changes make the protocol more
conservative; none was chosen with any result in view.

- **Labels.**
  - Unknown close reasons and unknown authorship can never make an issue
    positive.
  - Only references made by the horizon count.
  - A fix already linked or open at T is excluded (primary labels).
  - `--raw-labels` is a secondary sensitivity check.
- **PR membership at T.** Every PR that can create an overlap is checked against
  its events: PRs closed at T are dropped and their renames reversed.
- **Primary metric.** Precision@10 over the first 10 actual recommendations,
  with unjudged slots counted as misses. It is averaged over **all** test
  snapshots, including those without positives. Secondary results: precision@5,
  the upper bound, judged coverage, condensed P@k and recall.
- **Uncertainty.**
  - The interval is a conditional issue-population bootstrap with fixed
    snapshot support (2000 replicates, seed 0). It is not a label-noise or
    between-repository interval.
  - The random reference is a seeded random-permutation null (2000
    permutations, seed 0) on the same snapshots.
- **Decision rule.** (d) qualifies only if the 2.5th percentile of its
  test-set precision@10 bootstrap lies above the 97.5th percentile of the
  permutation null. If it does not, no ranking change is made.
- **Replay integrity.** Any incomplete replay, or one that changes the issue
  set, stops the run with an error. Each run reports its population: snapshots,
  issues, judged issues and positives.
- **Tuning set.** The four original repositories are re-collected in format 2
  at cutoff 2026-03-01, and are still not used for the decision.
- **Collection order and budget.** The 16 test snapshots are collected first,
  then the four tuning snapshots if the budget allows (about 900 extra reads).
  The floor of 1000 remaining core reads still applies; a missing snapshot is
  reported, not replaced.
- **Data.** Snapshots are no longer included in the source distribution. They
  are committed under `tools/benchmark/data/` only while the total stays under
  about 2 MB.

## Reproduce

```sh
D=tools/benchmark/data
python tools/benchmark/score.py $D/*.json --k 5 10 20
python tools/benchmark/experiment.py \
  --tune $D/pallets__click__2026-03-01.json $D/BurntSushi__ripgrep__2026-03-01.json \
  --heldout $D/psf__black__2026-03-01.json $D/honojs__hono__2026-03-01.json \
  --variants default signals recent help-wanted --k 5 10
```

Variant (c) needs the `209d480` tree on the import path, for example in an
archive of that commit with this `tools/benchmark` copied in.
