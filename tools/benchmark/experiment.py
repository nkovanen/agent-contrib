"""Held-out ranking experiment: score candidate orderings on tuning, held-out and all snapshots.

    python tools/benchmark/experiment.py --tune A.json B.json --heldout C.json D.json \\
        --variants default signals recent help-wanted --k 5 10 [--json]

A variant qualifies only when its held-out precision interval lies wholly above the random-order
interval (non-overlapping 95% bootstrap intervals). Offline: replays snapshots only."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_contribute import core  # noqa: E402
import benchlib  # noqa: E402


def load(paths):
    return [core.strict_json(pathlib.Path(path).read_text('utf-8')) for path in paths]


def evaluate(splits, variants, ks, reps=2000, seed=0, raw_labels=False):
    rows = []
    for split, snapshots in splits.items():
        labels = [benchlib.labels(snap, claimed_at_cutoff=raw_labels) for snap in snapshots]
        random_runs = [(benchlib.rank(snap, 'default'), label) for snap, label in zip(snapshots, labels)]
        reference = {'value': benchlib.base_rate(random_runs),
                     **benchlib.bootstrap_base_rate(random_runs, reps=reps, seed=seed)}
        for variant in variants:
            runs = [(benchlib.rank(snap, variant), label) for snap, label in zip(snapshots, labels)]
            for k in ks:
                ci = benchlib.bootstrap(runs, k, 'precision', reps=reps, seed=seed)
                rows.append({'split': split, 'variant': variant, 'k': k,
                             'repositories': [snap['repository'] for snap in snapshots],
                             'precision': benchlib.pooled(runs, k, 'precision'), 'precision_ci': ci,
                             'recall': benchlib.pooled(runs, k, 'recall'),
                             'recall_ci': benchlib.bootstrap(runs, k, 'recall', reps=reps, seed=seed),
                             'random': reference,
                             'beats_random': (ci['low'] is not None and reference['high'] is not None and
                                              ci['low'] > reference['high'])})
    return rows


def table(rows):
    def fmt(value):
        return '–' if value is None else f'{value:.2f}'
    out = ['| Split | Variant | k | Precision@k (95% CI) | Recall@k (95% CI) | Random (95% CI) | Beats random |',
           '| --- | --- | --- | --- | --- | --- | --- |']
    for row in rows:
        p, r, rnd = row['precision_ci'], row['recall_ci'], row['random']
        out.append(f"| {row['split']} | {row['variant']} | {row['k']} | {fmt(row['precision'])} "
                   f"({fmt(p['low'])}–{fmt(p['high'])}) | {fmt(row['recall'])} ({fmt(r['low'])}–{fmt(r['high'])}) | "
                   f"{fmt(rnd['value'])} ({fmt(rnd['low'])}–{fmt(rnd['high'])}) | {'yes' if row['beats_random'] else 'no'} |")
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tune', nargs='+', required=True)
    parser.add_argument('--heldout', nargs='+', required=True)
    parser.add_argument('--variants', nargs='+', default=['default', 'signals', 'recent', 'help-wanted'])
    parser.add_argument('--k', type=int, nargs='+', default=[5, 10])
    parser.add_argument('--reps', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--raw-labels', action='store_true', help='Keep positives whose fixing PR was already open at T')
    args = parser.parse_args()
    splits = {'tune': load(args.tune), 'held-out': load(args.heldout), 'all': load(args.tune + args.heldout)}
    rows = evaluate(splits, args.variants, args.k, args.reps, args.seed, args.raw_labels)
    print(json.dumps(rows, indent=1) if args.json else table(rows))


if __name__ == '__main__':
    main()
