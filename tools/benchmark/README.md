# Task-selection benchmark (#28)

An offline, reproducible yardstick for `discover` ranking. It is a development
tool, not part of the installed package: the wheel contains only
`agent_contribute`.

The question it answers is: of the issues open at a past cutoff T, does
`discover` (or `discover --signals`) put first the ones an outside contributor
then actually landed? Results and their limits are in
[docs/benchmark.md](../../docs/benchmark.md).

## Use

```sh
# Collect (read-only GitHub GETs through gh; bounded, see below)
python tools/benchmark/collect.py owner/repo --cutoff 2026-03-01T00:00:00Z \
  --horizon-days 90 --max-issues 300 \
  --output tools/benchmark/data/owner__repo__2026-03-01.json \
  [--bodies-out /outside/the/checkout/owner__repo__2026-03-01.bodies.json]

# Score (offline: replays the real discover code against the snapshots)
python tools/benchmark/score.py tools/benchmark/data/*.json --k 5 10 20 [--bodies DIR] [--json]

# Held-out experiment: candidate orderings on tuning, held-out and all snapshots
python tools/benchmark/experiment.py --tune A.json B.json --heldout C.json D.json \
  --variants default signals recent help-wanted --k 5 10
```

`experiment.py` adds a 95% interval for the random-order reference, using the
same resampling. A variant "beats random" only when its precision interval lies
wholly above the random interval.

The variants are:
- `default` and `signals`: discover itself.
- `recent`: discover's exclusion, overlap and likelihood keys, then the most
  recent activity at T first.
- `help-wanted`: the same keys, then issues labelled `help wanted` or `good first
  issue` at T first.

`score.py` patches the clock to T and serves `discover` only snapshot data
through a fake client. Any other request raises, so scoring cannot touch the
network. The bootstrap is seeded (`--seed`, default 0), so reruns give
identical numbers.

## Outcome labels

The window is (T, T + horizon], and a label is decided from the issue's state at
the end of the window.

| Label | Definition | Why |
| --- | --- | --- |
| positive | Closed as completed inside the window, by a PR in the same repository that was merged inside the window and within 24 hours of the close. The PR's author association must not be OWNER, MEMBER or COLLABORATOR, and its author must not be a bot. | Work an outside contributor demonstrably landed: what agent-contrib tries to find. |
| negative | Still open at the horizon (including closed, then reopened), or closed as `not_planned` or `duplicate`. | Nobody landed it in the window, or the project declined it. |
| excluded | Closed as completed without such a PR: a maintainer's PR, a direct commit, a bot, or an unlinked close. Also excluded at scoring time: a positive whose fixing PR was **already open at T**. | Ambiguous: maintainers may reserve work, or an outsider might have succeeded. A fix already in flight at T was not an available task, and discover deliberately demotes overlapping issues. Counting either way would bias the score. |

Snapshots store the outcome as collected. `benchlib.labels()` applies the
claimed-at-T exclusion when scoring; `--raw-labels` on `score.py` and
`experiment.py` keeps it as positive.

Excluded issues are removed before scoring. Precision@k counts positives among
the first k decidable issues; recall@k is the share of all positives found in
those k.

The pooled value is the mean over repositories. A repository with no positives
is listed but left out of the pool, because no ordering can score there.

The random-order reference is the mean positive rate. The 95% interval
resamples decidable issues within each repository (2000 replicates) while
keeping their rank positions. It captures label noise only, not the variance
from choosing repositories.

## What the snapshot can and cannot reconstruct at T

The collector reads each issue's timeline once and rolls fields back to T. It
never stores information from after T, except as recorded below.

| Field | At T? | How |
| --- | --- | --- |
| Open at T | yes | Search gives issues created at or before T that are open now or were closed after T. The timeline then drops any that were closed at T and reopened only later. |
| Title | yes | Current title with `renamed` events after T reversed. |
| Labels | yes | Current labels with `labeled`/`unlabeled` events after T reversed. This matters because exclusion labels such as `wontfix` are often added after T. |
| Comment count, last activity | yes | `commented` and other timeline events at or before T. |
| Default-branch tree | yes | The tree of the last commit at or before T (`commits?until=T`). |
| Open PRs at T | partly | Membership is exact, from search. Titles are current; PR renames are not reversed. Branch names and bodies are not stored, so overlap replay uses PR titles only. |
| Author association | no | The current value; an author may have joined the project since T. |
| Reactions, assignees | no | Not stored. Neither affects ranking order. |
| Issue body | no | REST has no edit history, and bodies are not committed. See below. |
| Instruction files, policy | no | Served empty. They do not affect ranking order. |

**Bodies.** The committed snapshots contain no issue or PR bodies, for licence
reasons and because a current body can carry post-T edits ("fixed in #123").
Without bodies, `discover` marks every issue vague (body shorter than 100
characters). Default ranking then reduces to exclusions, overlaps and issue
number, and `--signals` clarity is always low.

`collect.py --bodies-out` saves the current bodies to a local file outside the
checkout, and `score.py --bodies DIR` uses them. That gives a full-fidelity
replay, at the price of the leakage risk above. The two numbers are reported
separately.

## Other limitations

- **Survivorship and selection.** Repositories were chosen by hand from those an
  agent might be asked to help. Issues deleted or transferred before collection
  are missing.
- **Heuristic outcome links.** A cross-referenced merged PR closing within 24
  hours is taken as the fix. A PR that merely mentions the issue, or a manual
  close after an unrelated merge, can mislabel.
- **Truncation.** Search returns at most 1000 results per query, and the
  collector keeps at most `--max-issues` per repository (most recently created
  first) and 5 timeline pages per issue. Every truncation is recorded in the
  snapshot's `notes`.
- **Horizon.** 90 days misses slow but successful contributions.
- **Small sample.** A handful of repositories and a few dozen positives. The
  confidence intervals are wide; treat differences smaller than them as noise.

## Read budget

Per repository, the collector makes:
- 1 metadata read, 1 commit read and 1 tree read;
- at most 4 search queries × `--max-search-pages` pages (spaced 2.2 s apart, to
  stay within the search limit);
- one timeline read (at most 5 pages) per kept issue.

The baseline run used 134, 104, 280 and 307 reads for click, ripgrep, hono and
black.

## Data and licence

`data/*.json` holds public GitHub metadata: issue and PR titles, label names,
timestamps, author associations, file paths. Each record keeps its source URL
for attribution. No bodies are stored, and the total stays under 2 MB.
Snapshot format: `agent-contrib-benchmark/1`. A test checks that the data has no
bodies, has the expected outcome values and URLs, and stays under the size
limit.

The fresh-agent trial protocol requested in #28 (blind prompts, recorded
interventions) is not part of this harness; agent trials run externally.
