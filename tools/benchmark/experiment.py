"""Held-out ranking experiment: score candidate orderings on tuning, held-out and all snapshots.

    python tools/benchmark/experiment.py --tune A.json B.json --heldout C.json D.json \\
        --variants default signals recent help-wanted --k 5 10 [--raw-labels] [--json]

Primary metric: precision@k over the first k actual recommendations, with unjudged slots counted
as misses. A variant qualifies only when the 2.5th percentile of its conditional bootstrap lies
above the 97.5th percentile of a seeded random-permutation null on the same snapshots. Offline."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_contribute import core  # noqa: E402
import benchlib  # noqa: E402


def load(paths):
    return [benchlib.validate(core.strict_json(pathlib.Path(path).read_text('utf-8'))) for path in paths]


def evaluate(splits, variants, ks, reps=2000, seed=0, raw_labels=False):
    rows = []
    for split, snapshots in splits.items():
        labels = [benchlib.labels(snap, claimed_at_cutoff=raw_labels) for snap in snapshots]
        population = {'snapshots': len(snapshots), 'issues': sum(len(label) for label in labels),
                      'judged': sum(sum(v != 'excluded' for v in label.values()) for label in labels),
                      'positives': sum(sum(v == 'positive' for v in label.values()) for label in labels)}
        for variant in variants:
            runs = [(benchlib.rank(snap, variant), label) for snap, label in zip(snapshots, labels)]
            for k in ks:
                ci = benchlib.bootstrap(runs, k, 'precision_lower', reps=reps, seed=seed)
                null = benchlib.permutation_null(runs, k, 'precision_lower', reps=reps, seed=seed)
                rows.append({'split': split, 'variant': variant, 'k': k, 'population': population,
                             'repositories': [snap['repository'] + '@' + snap['cutoff'][:10] for snap in snapshots],
                             **{metric: benchlib.pooled(runs, k, metric) for metric in
                                ('precision_lower', 'precision_upper', 'coverage', 'condensed_precision', 'recall')},
                             'precision_lower_ci': ci, 'null': null,
                             'qualifies': (ci['low'] is not None and null['high'] is not None and
                                           ci['low'] > null['high'])})
    return rows


def table(rows):
    def fmt(value):
        return '–' if value is None else f'{value:.2f}'
    out = ['| Split | Variant | k | P@k, unjudged as misses (95% sensitivity) | Upper bound | Coverage | '
           'Condensed P@k | Recall@k | Random null median (95%) | Qualifies |',
           '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in rows:
        ci, null = row['precision_lower_ci'], row['null']
        out.append(f"| {row['split']} | {row['variant']} | {row['k']} | {fmt(row['precision_lower'])} "
                   f"({fmt(ci['low'])}–{fmt(ci['high'])}) | {fmt(row['precision_upper'])} | {fmt(row['coverage'])} | "
                   f"{fmt(row['condensed_precision'])} | {fmt(row['recall'])} | {fmt(null['median'])} "
                   f"({fmt(null['low'])}–{fmt(null['high'])}) | {'yes' if row['qualifies'] else 'no'} |")
    seen = {}
    for row in rows:
        seen.setdefault(row['split'], row['population'])
    out.append('')
    out += [f"Population {split}: {p['snapshots']} snapshots, {p['issues']} issues, {p['judged']} judged, "
            f"{p['positives']} positive." for split, p in seen.items()]
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tune', nargs='+', required=True)
    parser.add_argument('--heldout', nargs='+', required=True)
    parser.add_argument('--variants', nargs='+', default=['default', 'signals', 'recent', 'help-wanted'])
    parser.add_argument('--k', type=int, nargs='+', default=[5, 10])
    parser.add_argument('--reps', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--raw-labels', action='store_true', help='Keep fixes already in flight at T as positive')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    splits = {'tune': load(args.tune), 'held-out': load(args.heldout), 'all': load(args.tune + args.heldout)}
    rows = evaluate(splits, args.variants, args.k, args.reps, args.seed, args.raw_labels)
    print(json.dumps(rows, indent=1) if args.json else table(rows))


if __name__ == '__main__':
    main()
