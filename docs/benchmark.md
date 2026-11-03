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

## Results: expanded corpus (format 2, scored 2026-11-03)

**Collection.**
- All 20 planned snapshots were collected (3369 reads, read-only), with nothing
  skipped or replaced.
- The run paused once for the hourly rate-limit reset, because other users of
  the token had pulled the shared limit to the 1000 floor.
- 12 of the 16 test snapshots (both cutoffs of axios, clap, fzf, pydantic, bat
  and cobra), and hono and black in the tuning set, hit the 150-issue cap. They
  keep the most recently created issues, which is recorded in each snapshot's
  notes. Axios at 2026-03-01 hit the cap and then kept 148, after dropping two
  issues that were closed at T.

**Where the data is.** The 4 tuning snapshots (0.5 MB) are committed under
`tools/benchmark/data/`. The 16 test snapshots (2.07 MB) would exceed the size
limit, so they are kept in the validation run (`benchmark/expanded/`), named
`owner__repo__cutoff.json`.

### Registration discrepancy (review BM-07)

The amendment above says an unknown close reason can never make an issue
positive. The labelling code committed before collection (b4098af) did
something weaker: a qualifying new external merged PR made an issue positive
even when the close reason was unknown. The first version of this page
(5e77096) reported that weaker labelling as the primary result without noting
the difference. Neither the registration nor the code changed after results
were seen; they disagreed from the start.

The registration text above stands as written (`--raw-labels` there is now
`--labels raw`). The results are now separated:

- **registered** (`--labels registered`, the default): the amendment applied
  literally. This is the primary, pre-registered analysis.
- **weak-reason** (`--labels weak-reason`): an unknown close reason with a
  qualifying PR still counts as positive. These are the numbers first published
  in 5e77096. Sensitivity analysis only.
- **raw** (`--labels raw`): weak-reason, and fixes already in flight at T also
  count as positive. Sensitivity analysis only.

All three were re-scored offline from the stored snapshots, with seed 0 and
2000 replicates. The weak-reason and raw tables reproduce the 5e77096 tables
row for row.

| Labels | Split | Snapshots | Issues | Judged | Positive | Snapshots without a positive |
| --- | --- | --- | --- | --- | --- | --- |
| registered | tune | 4 | 518 | 454 | 13 | |
| registered | test | 16 | 2123 | 1941 | 30 | 9 |
| weak-reason | tune | 4 | 518 | 462 | 21 | |
| weak-reason | test | 16 | 2123 | 1952 | 41 | 6 |
| raw | test | 16 | 2123 | 1971 | 60 | 4 |

The registered labels drop 11 test positives and 8 tuning positives, all of
them closes with no recorded reason. That missing reason is an unknown, not
evidence that the close was wrong.

### Registered analysis (primary)

Test-set precision over the first k recommendations, with unjudged slots
counted as misses.

| Variant | k | Precision (95% bootstrap) | Upper bound | Coverage | Recall@k | Random null median (95%) | Qualifies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| (a) default | 5 | 0.013 (0.000–0.025) | 0.09 | 0.93 | 0.02 | 0.013 (0.000–0.038) | no |
| (a) default | 10 | 0.006 (0.000–0.019) | 0.06 | 0.95 | 0.02 | 0.013 (0.000–0.031) | no |
| (b) signals | 5 | 0.000 (0.000–0.025) | 0.05 | 0.95 | 0.00 | 0.013 (0.000–0.038) | no |
| (b) signals | 10 | 0.013 (0.000–0.025) | 0.07 | 0.94 | 0.16 | 0.013 (0.000–0.031) | no |
| (d) recent activity | 5 | 0.038 (0.000–0.088) | 0.18 | 0.86 | 0.13 | 0.013 (0.000–0.038) | no |
| (d) recent activity | 10 | **0.025 (0.006–0.050)** | 0.13 | 0.89 | 0.15 | 0.013 (0.000–0.031) | **no** |

**Decision: no ranking change.** Under the pre-registered rule, (d) needed the
2.5th percentile of its test precision@10 (0.006) to lie above the null's 97.5th
percentile (0.031). It does not. No variant qualifies on any split or k.

### Sensitivity analyses (not the registered result)

Test-set precision@10 for (d) recent activity; full tables for every variant,
split and k are in the validation run (`benchmark/bm-round2/results-*.md`).

| Labels | Precision@10 (95% bootstrap) | Random null median (95%) | Qualifies |
| --- | --- | --- | --- |
| weak-reason (published in 5e77096) | 0.031 (0.006–0.063) | 0.019 (0.000–0.038) | no |
| raw | 0.056 (0.025–0.100) | 0.025 (0.006–0.050) | no |

No variant qualifies under either sensitivity labelling, so the decision does
not depend on the labelling choice.

### What the results do and do not say

- (d) has the best precision@10 point estimate on every split under every
  labelling. That is a direction, not the pre-registered evidence, so this
  candidate stays open. (Recall@10 is a mean over only the 7 test snapshots
  with a registered positive, so it is noisy and not compared here.) Deciding it would need a larger or longer-horizon
  corpus, or a paired test against default.
- Default and `--signals` cannot be told apart from random ordering here. Their
  point estimates are at or below the null median; their intervals are wide and
  reach above it. This is not a claim that they are equivalent to random.
- Positives are rare: 30 among 2123 test issues under registered labels, and 9
  of 16 test snapshots have none. Every interval reflects that.

### Unresolved limitation: PR history hidden by renames (review BM-02)

The collector reads a PR's events only when its **current** title overlaps a
kept issue. For those PRs it drops any that were closed at T and reverses later
renames. The other candidates keep their current titles, unverified. In this
corpus that is 636 of 1066 test candidates and 88 of 178 tuning candidates. A
PR that overlapped an issue at T but was renamed afterwards to an unrelated
title was never selected, so its old title is not reconstructed. Fixing this
needs the events of every candidate, about 724 to 1448 more reads, which have
not been made.

What this can and cannot change:

- **Labels: no change in this corpus.** Unverified PRs enter only through the
  in-flight exclusion. Re-labelling with only verified PRs as open at T changes
  no label under the registered or weak-reason scheme, on either split. Raw
  labels do not use PR membership.
- **Ranking: possible missed overlaps.** An unverified PR's current title
  overlaps no kept issue, so the replay never gets a false overlap from one.
  It can miss an overlap that a since-renamed title caused at T. The replay
  then ranks such an issue higher than `discover` would have at T. Default,
  `--signals` and (d) all apply the same overlap key before their own ordering,
  so all three shift together. The permutation null does not use overlaps.
- **Direction.** It depends on what happened to the hidden issues. If an
  external contributor later landed one, the replay overstates the precision of
  all three variants against the null; otherwise it understates it. The
  incidence is unknown, because the skipped event histories were not read, so
  either sign could move a variant towards or away from qualifying. It is
  recorded as an open limitation, not a resolved one.

## Reproduce

```sh
D=tools/benchmark/data                   # tuning snapshots (committed)
E=/path/to/validation-run/benchmark/expanded   # test snapshots (not committed)
python tools/benchmark/score.py $D/*.json --k 5 10
python tools/benchmark/experiment.py --tune $D/*.json \
  --heldout $(ls $E/*.json | grep -v -e pallets__ -e BurntSushi__ -e honojs__ -e psf__) \
  --variants default signals recent --k 5 10 [--labels registered|weak-reason|raw]
```
