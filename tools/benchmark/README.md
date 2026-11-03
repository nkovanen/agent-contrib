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

Snapshots store raw evidence: close and reopen events with their recorded
reason, timestamped PR references with merge time, author association and user
type, and the issue's current state. Labels are derived from that evidence when
scoring (`benchlib.classify`), so a definition change never needs a new
collection.

The window is (T, T + horizon]. Every positive needs explicit evidence;
anything unknown is excluded, never assumed.

| Label | Definition |
| --- | --- |
| positive | Closed at the horizon, by a PR in the same repository that was merged inside the window within 24 hours of the close and referenced from the issue **by the horizon**. Its author association must be one of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, `FIRST_TIMER` or `NONE`, and its user type must be `User`. The PR must not already be linked or open at T. The close reason must be `completed` or unknown, and is reported as `reason_known`. |
| negative | Still open at the horizon (including closed then reopened), or closed with an explicit `not_planned` or `duplicate` reason. |
| excluded | Every other close: a maintainer's or bot's fix, unknown authorship, an unlinked close, an unknown reason without a qualifying PR, and a fix already in flight at T (an available task for nobody new). |

A close event's reason is often missing. It is taken from the issue's current
`state_reason` only when the issue is still closed and its `closed_at` is that
same close event; otherwise it is unknown. `--raw-labels` keeps fixes already in
flight at T as positive, as a sensitivity check.

## Metrics

The primary metric is top-k precision over the first k recommendations the agent
would actually see, the full ranking with no slots removed:

- **precision** counts an unjudged (excluded) slot as a miss, so it is a lower
  bound;
- **upper bound** counts an unjudged slot as a hit;
- **coverage** is the judged share of the top k.

Two secondary metrics are reported:

- **condensed P@k** is the older conditional metric: the first k *judged*
  issues. It uses outcomes to choose the slots and is not what an agent sees.
- **recall@k** is the share of a snapshot's positives found in its top k.

Pooled values are macro means over snapshots. Top-k precision, upper bound and
coverage use **every** snapshot, including those with no positives (precision
0). Condensed P@k and recall use only snapshots with positives, a support fixed
from the original labels.

**Intervals.** The interval is a *conditional issue-population bootstrap*. Each
snapshot's issues are resampled with replacement, keeping their rank positions
and labels, with the snapshot support fixed (2000 replicates, seeded). It shows
sensitivity to which issues happened to be open. It does **not** model label
noise or repository-to-repository variation.

**Random reference.** A seeded permutation null: uniformly random orderings of
each snapshot's full issue set, scored the same way. A ranking is said to beat
random only when its bootstrap 2.5th percentile exceeds the null's 97.5th
percentile. Overlapping intervals do not show equivalence to random.

**Fail loudly.** The scorer refuses:
- an unknown snapshot format;
- duplicate issues, or a body field;
- an outcome window that had not ended at collection time;
- an incomplete `discover` replay;
- a replay that does not return exactly the snapshot's issues;
- a ranking that is not a permutation of the labelled issues.

## What the snapshot can and cannot reconstruct at T

The collector reads each issue's timeline once and rolls fields back to T. It
never stores information from after T, except as recorded below.

| Field | At T? | How |
| --- | --- | --- |
| Open at T | yes | Search gives issues created at or before T that are open now or were closed after T. The timeline then drops any that were closed at T and reopened only later. |
| Title | yes | Current title with `renamed` events after T reversed. |
| Labels | yes | Current labels with `labeled`/`unlabeled` events after T reversed. This matters because exclusion labels such as `wontfix` are often added after T. |
| Comment count, last activity | yes | `commented` and other timeline events at or before T. |
| Default-branch tree | approximately | The tree of the last commit at or before T on the **current** default branch (`commits?until=T`). Branch renames, rewritten history or backdated commits can differ from what the branch held at T. |
| Open PRs at T | partly | Candidates come from search: created at or before T, and open now or closed after T. Every candidate whose title can create an overlap with a kept issue has its events read, which drops PRs closed at T (reopened later) and reverses later renames (`membership_verified: true`). The other candidates cannot change the ranking and stay unverified. Branch names and bodies are not stored, so overlap replay uses PR titles only. |
| Author association | no | The current value, for both issue authors (affects `--signals` by one point) and PR authors (affects positives); a person may have joined the project since T. |
| Reactions, assignees | no | Not stored. Neither affects ranking order. |
| Issue body | no | REST has no edit history, and bodies are not committed. See below. |
| Instruction files, policy | no | Served empty. They do not affect ranking order. |

**Bodies.** The committed snapshots contain no issue or PR bodies, for licence
reasons and because a current body can carry post-T edits ("fixed in #123").
Without bodies, `discover` marks every issue vague (body shorter than 100
characters). Default ranking then reduces to exclusions, overlaps and issue
number, and `--signals` clarity is always low.

`collect.py --bodies-out` saves the current bodies to a local file outside the
checkout, and `score.py --bodies DIR` uses them. That is closer to real
discover, but not full fidelity: PR bodies and branch names are still missing,
and the current bodies may leak post-T edits. It is not reproducible from
committed artifacts.

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
- one timeline read (at most 5 pages) per kept issue;
- one events read (at most 2 pages) per candidate PR whose title can create an
  overlap.

## Data and provenance

`data/*.json` holds public GitHub metadata: issue and PR titles, label names,
timestamps, author associations, file paths and outcome evidence. Each record
keeps its source URL for attribution. No bodies or logins are stored as
structured data, though titles and paths are public text and can mention
people.

The content belongs to its authors under GitHub's Terms of Service. It is not
covered by this project's MIT licence, and no licence grant is implied. The
snapshots are kept in the repository for reproducibility but are not
redistributed in the source or wheel distributions. Format:
`agent-contrib-benchmark/2`.

The fresh-agent trial protocol requested in #28 (blind prompts, recorded
interventions) is not part of this harness; agent trials run externally.
