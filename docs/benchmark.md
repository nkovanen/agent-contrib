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

## Results: expanded corpus (format 2, scored 2026-11-03 under the amended protocol)

**Collection.**
- All 20 planned snapshots were collected (3369 reads, read-only), with nothing
  skipped or replaced.
- The run paused once for the hourly rate-limit reset, because other users of
  the token had pulled the shared limit to the 1000 floor.
- 7 of the 16 test snapshots, and hono and black in the tuning set, hit the
  150-issue cap. They keep the most recently created issues, which is recorded
  in each snapshot's notes.

**Where the data is.** The 4 tuning snapshots (0.5 MB) are committed under
`tools/benchmark/data/`. The 16 test snapshots (2.07 MB) would exceed the size
limit, so they are kept in the validation run (`benchmark/expanded/`), named
`owner__repo__cutoff.json`.

| Split | Snapshots | Issues | Judged | Positive (raw) |
| --- | --- | --- | --- | --- |
| tune (click, ripgrep, hono, black @ 2026-03-01) | 4 | 518 | 462 | 21 (31) |
| test (8 repositories × 2 cutoffs) | 16 | 2123 | 1952 | 41 (60) |

Primary metric: test-set precision, with unjudged slots counted as misses.

| Variant | k | Precision (95% bootstrap) | Upper bound | Coverage | Recall@k | Random null median (95%) | Qualifies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| (a) default | 5 | 0.01 (0.00–0.03) | 0.09 | 0.93 | 0.01 | 0.01 (0.00–0.05) | no |
| (a) default | 10 | 0.01 (0.00–0.02) | 0.06 | 0.95 | 0.01 | 0.02 (0.00–0.04) | no |
| (b) signals | 5 | 0.00 (0.00–0.03) | 0.05 | 0.95 | 0.00 | 0.01 (0.00–0.05) | no |
| (b) signals | 10 | 0.01 (0.00–0.03) | 0.07 | 0.94 | 0.06 | 0.02 (0.00–0.04) | no |
| (d) recent activity | 5 | 0.05 (0.01–0.10) | 0.18 | 0.88 | 0.19 | 0.01 (0.00–0.05) | no |
| (d) recent activity | 10 | **0.03 (0.01–0.06)** | 0.13 | 0.90 | 0.20 | 0.02 (0.00–0.04) | **no** |

**Decision: no ranking change.** Under the pre-registered rule, (d) needed the
2.5th percentile of its test precision@10 (0.01) to lie above the null's 97.5th
percentile (0.04). It does not.

The raw-label sensitivity run agrees: (d) scores 0.06 (0.03–0.10) against a
null of 0.03 (0.01–0.05), which still overlaps, and no variant qualifies on any
split. Full tables, including tuning, raw labels and all splits, are in the
validation run (`benchmark/expanded-results*.md`).

**What the results do and do not say.**

- (d) has the best point estimates on every split, and finds about 20% of test
  positives in its top 10, against 0–6% for (a) and (b). That is a consistent
  direction, but not the pre-registered evidence, so this candidate stays open.
  Deciding it would need a larger or longer-horizon corpus, or a paired test
  against default.
- Default and `--signals` cannot be told apart from random ordering here. Their
  intervals sit at or below the null median. This is not a claim that they are
  equivalent to random.
- Positives are rare: 41 among 2123 test issues, and 6 of 16 test snapshots have
  none. Every interval reflects that.

## Reproduce

```sh
D=tools/benchmark/data                   # tuning snapshots (committed)
E=/path/to/validation-run/benchmark/expanded   # test snapshots (not committed)
python tools/benchmark/score.py $D/*.json --k 5 10
python tools/benchmark/experiment.py --tune $D/*.json \
  --heldout $(ls $E/*.json | grep -v -e pallets__ -e BurntSushi__ -e honojs__ -e psf__) \
  --variants default signals recent --k 5 10 [--raw-labels]
```
