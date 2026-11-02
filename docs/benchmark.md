# Task-selection benchmark results

This page tracks how well `discover` ranks the issues an outside contributor
then lands. Method, label definitions and limits are in the
[harness README](../tools/benchmark/README.md). Rankings are heuristics and never
approval; these numbers measure them, not the protocol's safety gates.

## Baseline: v0.3.0 candidate, cutoff 2026-03-01, 90-day horizon

| Repository | Issues open at T | Positive | Negative | Excluded |
| --- | --- | --- | --- | --- |
| BurntSushi/ripgrep | 94 | 0 | 94 | 0 |
| honojs/hono | 270 | 6 | 248 | 16 |
| pallets/click | 124 | 9 | 85 | 30 |
| psf/black | 298 | 21 | 271 | 6 |

ripgrep had no positives in the window, so it is left out of the pooled values.
pallets/flask was also tried: it had no issues open at T, so it has no
snapshot.

Committed snapshots (no bodies):

| Variant | k | Precision@k (95% CI) | Recall@k (95% CI) |
| --- | --- | --- | --- |
| default | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| default | 10 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| default | 20 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| signals | 5 | 0.00 (0.00–0.07) | 0.00 (0.00–0.03) |
| signals | 10 | 0.03 (0.00–0.10) | 0.04 (0.00–0.10) |
| signals | 20 | 0.02 (0.00–0.05) | 0.04 (0.00–0.12) |

With current bodies (local only; may leak post-T edits):

| Variant | k | Precision@k (95% CI) | Recall@k (95% CI) |
| --- | --- | --- | --- |
| default | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| default | 10 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| default | 20 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| signals | 5 | 0.00 (0.00–0.00) | 0.00 (0.00–0.00) |
| signals | 10 | 0.00 (0.00–0.03) | 0.00 (0.00–0.03) |
| signals | 20 | 0.03 (0.00–0.08) | 0.07 (0.00–0.17) |

Random-order expected precision (mean positive rate): **0.06**.

## Reading the baseline

- **Default ranking is below random.** Once exclusions and overlaps are sorted
  out, almost every issue ties on "low likelihood". The tie-break is the issue
  number, so the oldest issues come first. Old open issues are the ones
  contributors have already passed over. Not one positive reached the top 20 in
  any repository.
- **`--signals` is roughly random.** Its score rewards maintainer-authored issues
  and clear acceptance sections. It moves a few positives up, but its intervals
  overlap zero and the 0.06 random rate.
- **Bodies do not change the picture.** With bodies, more issues stop being
  "vague", but the tie-break and score still decide the top of the list.
- **This matches the dogfood judgement** (0–1 of 5 in the top 5 on click, ripgrep
  and hono, model-judged). The harness now measures it reproducibly.

These are candidate observations from a small sample, not a ranking redesign.
Any ranking change should be measured here first, on the committed snapshots,
before claiming an improvement.

Reproduce:

```sh
python tools/benchmark/score.py tools/benchmark/data/*.json --k 5 10 20
```
