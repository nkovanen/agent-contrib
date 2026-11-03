"""Score discover's ranking against benchmark snapshots. Offline: no network.

    python tools/benchmark/score.py tools/benchmark/data/*.json [--k 5 10] [--bodies DIR]
        [--labels registered|weak-reason|raw] [--json]

Every snapshot is validated and every replay must be complete and return exactly the snapshot's
issues, or scoring stops with an error. --bodies DIR reads <snapshot-name>.bodies.json files written
by collect.py --bodies-out (current bodies kept outside the checkout; see the README)."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_contribute import core  # noqa: E402
import benchlib  # noqa: E402

METRICS = ('precision_lower', 'precision_upper', 'coverage', 'condensed_precision', 'recall')


def summarize(runs, k, reps, seed):
    result = {metric: benchlib.pooled(runs, k, metric) for metric in METRICS}
    result['precision_lower_ci'] = benchlib.bootstrap(runs, k, 'precision_lower', reps=reps, seed=seed)
    result['null'] = benchlib.permutation_null(runs, k, 'precision_lower', reps=reps, seed=seed)
    return result


def score(paths, ks, bodies_dir=None, reps=2000, seed=0, scheme='registered'):
    report = {'labels': scheme, 'snapshots': [], 'variants': {}}
    runs = {'default': [], 'signals': []}
    for path in paths:
        snapshot = benchlib.validate(core.strict_json(pathlib.Path(path).read_text('utf-8')))
        bodies = None
        if bodies_dir:
            source = pathlib.Path(bodies_dir) / (pathlib.Path(path).stem + '.bodies.json')
            bodies = core.strict_json(source.read_text('utf-8'))
        labels = benchlib.labels(snapshot, scheme=scheme)
        counts = {name: sum(value == name for value in labels.values()) for name in ('positive', 'negative', 'excluded')}
        report['snapshots'].append({'repository': snapshot['repository'], 'cutoff': snapshot['cutoff'],
                                    'horizon_days': snapshot['horizon_days'], 'issues': len(labels), **counts})
        for name in runs:
            runs[name].append((benchlib.rank(snapshot, name, bodies), labels))
    for name, variant_runs in runs.items():
        report['variants'][name] = {f'@{k}': summarize(variant_runs, k, reps, seed) for k in ks}
    return report


def fmt(value):
    return '–' if value is None else f'{value:.2f}'


def table(report):
    lines = [benchlib.scheme_title(report['labels']), '', '| Variant | k | Precision@k, unjudged as misses (95% sensitivity) | Upper bound | Judged coverage | '
             'Condensed P@k | Recall@k | Random null median (95%) |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name, results in report['variants'].items():
        for k, r in results.items():
            ci, null = r['precision_lower_ci'], r['null']
            lines.append(f"| {name} | {k[1:]} | {fmt(r['precision_lower'])} ({fmt(ci['low'])}–{fmt(ci['high'])}) | "
                         f"{fmt(r['precision_upper'])} | {fmt(r['coverage'])} | {fmt(r['condensed_precision'])} | "
                         f"{fmt(r['recall'])} | {fmt(null['median'])} ({fmt(null['low'])}–{fmt(null['high'])}) |")
    totals = {key: sum(s[key] for s in report['snapshots']) for key in ('issues', 'positive', 'negative', 'excluded')}
    lines.append(f"\nPopulation: {len(report['snapshots'])} snapshots, {totals['issues']} issues "
                 f"({totals['positive']} positive, {totals['negative']} negative, {totals['excluded']} excluded).")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('snapshots', nargs='+')
    parser.add_argument('--k', type=int, nargs='+', default=[5, 10])
    parser.add_argument('--bodies')
    parser.add_argument('--reps', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--labels', choices=list(benchlib.LABEL_SCHEMES), default='registered',
                        help='registered is the primary analysis; the others are sensitivity analyses')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    report = score(args.snapshots, args.k, args.bodies, args.reps, args.seed, args.labels)
    print(json.dumps(report, indent=1) if args.json else table(report))


if __name__ == '__main__':
    main()
