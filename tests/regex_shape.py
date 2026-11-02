"""Deterministic linear-scan check: no quantifier inside another quantifier, the shape behind catastrophic backtracking."""
try:
    from re import _constants as constants, _parser as parser
except ImportError:  # Python 3.10
    import sre_constants as constants
    import sre_parse as parser

REPEATS = {getattr(constants, name) for name in ('MAX_REPEAT', 'MIN_REPEAT', 'POSSESSIVE_REPEAT') if hasattr(constants, name)}


def _children(av):
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
