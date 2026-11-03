"""Deterministic nesting check: does any quantifier sit inside another quantifier?

This is one common catastrophic-backtracking shape, not a linear-time proof: overlapping alternation such as
(a|aa)+b and adjacent repeats such as a+a+b pass it. Lookarounds, atomic groups and branches are traversed.
"""
try:
    from re import _constants as constants, _parser as parser
except ImportError:  # Python 3.10
    import sre_constants as constants
    import sre_parse as parser

REPEATS = {getattr(constants, name) for name in ('MAX_REPEAT', 'MIN_REPEAT', 'POSSESSIVE_REPEAT') if hasattr(constants, name)}


def _children(av):
    if isinstance(av, parser.SubPattern):  # atomic groups carry their body directly
        yield av
        return
    for item in av if isinstance(av, (tuple, list)) else ():
        if isinstance(item, parser.SubPattern):
            yield item
        elif isinstance(item, list):
            yield from (sub for sub in item if isinstance(sub, parser.SubPattern))


def nested_repeats(pattern):
    def walk(items, inside):
        for op, av in items:
            if op in REPEATS:
                if inside or walk(av[2], True):
                    return True
            elif any(walk(sub, inside) for sub in _children(av)):
                return True
        return False
    return walk(parser.parse(pattern.pattern, pattern.flags), False)
