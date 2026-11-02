# Task-selection benchmark results

This page tracks how well `discover` ranks the issues an outside contributor
then lands. Method, label definitions and limits are in the
[harness README](../tools/benchmark/README.md). Rankings are heuristics and never
approval; these numbers measure them, not the protocol's safety gates.

## Snapshots: cutoff 2026-03-01, 90-day horizon

Positive counts use the scoring labels: a fix whose PR was already open at T
is excluded, because that task had already been taken. The raw collected
positives are shown in brackets.

| Repository | Issues open at T | Positive | Negative | Excluded |
| --- | --- | --- | --- | --- |
| BurntSushi/ripgrep | 94 | 0 (0) | 94 | 0 |
| honojs/hono | 270 | 4 (6) | 248 | 18 |
| pallets/click | 124 | 4 (9) | 85 | 35 |
| psf/black | 298 | 16 (21) | 271 | 11 |

ripgrep had no positives in the window, so it is left out of pooled values.
pallets/flask was also tried: it had no issues open at T, so it has no
snapshot.

## Baseline (v0.3.0 candidate, committed body-free snapshots)

| Variant | k | Precision@k (95% CI) | Recall@k (95% CI) |
| --- | --- | --- | --- |
| default | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| default | 10 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| default | 20 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| signals | 5 | 0.00 (0.00–0.07) | 0.00 (0.00–0.07) |
| signals | 10 | 0.03 (0.00–0.10) | 0.08 (0.00–0.22) |
| signals | 20 | 0.02 (0.00–0.07) | 0.08 (0.00–0.33) |

Random-order expected precision (mean positive rate): **0.04**.

With raw labels (`--raw-labels`), default is still 0.00 at every k and random
is 0.06. With current bodies (local only; they may leak post-T edits),
`--signals` is 0.00 / 0.00 / 0.03 at k = 5 / 10 / 20.

## Held-out ranking experiment

The protocol was fixed before any variant was scored:

- **Splits.** Tune on click and ripgrep; report on black and hono (held out),
  then on all four. Because ripgrep has no positives, the tuning pool is
  effectively click alone.
- **Rule.** A change is recommended only if its held-out precision interval lies
  wholly above the random interval (both 95%, seeded, 2000 replicates).
- **Variants:**
  - (a) default discover;
  - (b) current `--signals`;
  - (c) `--signals` from `rsi/ranking-quality` at `209d480` (label and meta
    demotions), scored from an archive of that tree;
  - (d) default with the final tie-break changed from oldest issue number to
    most recent activity at T;
  - (e) default with issues labelled `help wanted` or `good first issue` at T
    promoted after the exclusion, overlap and likelihood keys. These labels are
    the project's own statement that outside contributions are welcome. This
    was chosen on that principle, not from the data.

Held-out results, black and hono:

| Variant | k | Precision@k (95% CI) | Recall@k (95% CI) | Random (95% CI) | Beats random |
| --- | --- | --- | --- | --- | --- |
| (a) default | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |
| (a) default | 10 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |
| (b) signals | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |
| (b) signals | 10 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |
| (c) signals @209d480 | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |
| (c) signals @209d480 | 10 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |
| (d) recent activity | 5 | 0.10 (0.00–0.20) | 0.03 (0.00–0.08) | 0.04 (0.02–0.05) | no |
| (d) recent activity | 10 | 0.05 (0.00–0.15) | 0.03 (0.00–0.11) | 0.04 (0.02–0.05) | no |
| (e) help-wanted first | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |
| (e) help-wanted first | 10 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) | 0.04 (0.02–0.05) | no |

All four repositories:

| Variant | k | Precision@k (95% CI) | Random (95% CI) | Beats random |
| --- | --- | --- | --- | --- |
| (a) default | 5 / 10 | 0.00 / 0.00 | 0.04 (0.02–0.06) | no |
| (b) signals | 5 / 10 | 0.00 (0.00–0.07) / 0.03 (0.00–0.10) | 0.04 (0.02–0.06) | no |
| (c) signals @209d480 | 5 / 10 | 0.00 (0.00–0.10) / 0.03 (0.00–0.10) | 0.04 (0.02–0.06) | no |
| (d) recent activity | 5 / 10 | 0.13 (0.00–0.27) / 0.07 (0.00–0.17) | 0.04 (0.02–0.06) | no |
| (e) help-wanted first | 5 / 10 | 0.00 / 0.00 | 0.04 (0.02–0.06) | no |

The raw-label rerun, which keeps fixes already in flight at T as positives,
reaches the same verdict for every variant.

**Recommendation: no ranking change.**
- No candidate beats random with non-overlapping intervals on the held-out
  repositories.
- (d) has the highest point estimates on every split, but its intervals include
  both zero and the random rate.
- (e) never lifted a positive into the top k: few issues carry those labels at T
  (0 in hono, 7 in black).

What the data does support is a negative finding. Default's held-out interval
(0.00–0.00) lies below the random interval, so its oldest-first tie-break is
measurably worse than chance on this corpus. Before changing the ranking,
re-measure with more repositories and cutoffs, so that a real effect of the
size (d) suggests could be detected.

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
