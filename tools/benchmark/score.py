"""Score discover's ranking against benchmark snapshots. Offline: no network.

    python tools/benchmark/score.py tools/benchmark/data/*.json [--k 5 10] [--bodies DIR] [--json]

--bodies DIR reads <snapshot-name>.bodies.json files written by collect.py --bodies-out (current
bodies, kept outside the checkout; see the README for the leakage caveat)."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_contribute import core  # noqa: E402
import benchlib  # noqa: E402


def score(paths, ks, bodies_dir=None, reps=2000, seed=0):
    snapshots = [core.strict_json(pathlib.Path(path).read_text('utf-8')) for path in paths]
    report = {'snapshots': [], 'variants': {}}
    variants = {'default': {}, 'signals': {'signals': True}}
    runs = {name: [] for name in variants}
    for path, snapshot in zip(paths, snapshots):
        bodies = None
        if bodies_dir:
            source = pathlib.Path(bodies_dir) / (pathlib.Path(path).stem + '.bodies.json')
            bodies = core.strict_json(source.read_text('utf-8'))
        labels = {issue['number']: issue['outcome'] for issue in snapshot['issues']}
        counts = {name: sum(value == name for value in labels.values()) for name in ('positive', 'negative', 'excluded')}
        report['snapshots'].append({'repository': snapshot['repository'], 'cutoff': snapshot['cutoff'],
                                    'horizon_days': snapshot['horizon_days'], **counts})
        for name, options in variants.items():
            runs[name].append((benchlib.replay(snapshot, bodies=bodies, **options), labels))
    for name, variant_runs in runs.items():
        report['variants'][name] = {f'@{k}': {
            'precision': benchlib.pooled(variant_runs, k, 'precision'),
            'precision_ci': benchlib.bootstrap(variant_runs, k, 'precision', reps=reps, seed=seed),
            'recall': benchlib.pooled(variant_runs, k, 'recall'),
            'recall_ci': benchlib.bootstrap(variant_runs, k, 'recall', reps=reps, seed=seed),
            'per_repository': [benchlib.at_k(ranking, labels, k) for ranking, labels in variant_runs]} for k in ks}
    report['random_precision'] = benchlib.base_rate(runs['default'])
    return report


def table(report):
    def fmt(value):
        return '–' if value is None else f'{value:.2f}'
    lines = ['| Variant | k | Precision@k (95% CI) | Recall@k (95% CI) |', '| --- | --- | --- | --- |']
    for name, results in report['variants'].items():
        for k, result in results.items():
            p, r = result['precision_ci'], result['recall_ci']
            lines.append(f'| {name} | {k[1:]} | {fmt(result["precision"])} ({fmt(p["low"])}–{fmt(p["high"])}) | '
                         f'{fmt(result["recall"])} ({fmt(r["low"])}–{fmt(r["high"])}) |')
    lines.append(f'\nRandom-order expected precision (mean positive rate): {fmt(report["random_precision"])}')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('snapshots', nargs='+')
    parser.add_argument('--k', type=int, nargs='+', default=[5, 10])
    parser.add_argument('--bodies')
    parser.add_argument('--reps', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    report = score(args.snapshots, args.k, args.bodies, args.reps, args.seed)
    print(json.dumps(report, indent=1) if args.json else table(report))


if __name__ == '__main__':
    main()
