"""Opt-in core REST rate-limit reporting (#27). The rate_limit endpoint does not consume the budget."""
from . import core

FIELDS = ('limit', 'remaining', 'used', 'reset')


def snapshot(client=None):
    try:
        data = core.require((client or core.GitHub()).request('rate_limit'), dict, 'rate limit')
        resource = core.require(core.require(data.get('resources'), dict, 'rate limit resources').get('core'),
                                dict, 'core rate limit')
        values = {name: resource.get(name) for name in FIELDS}
        if any(type(value) is not int or value < 0 for value in values.values()):
            raise core.ProtocolError('api_shape', 'Invalid GitHub core rate limit')
        return {**values, 'error': None}
    except core.ProtocolError as exc:
        return {**{name: None for name in FIELDS}, 'error': str(exc)}


def require_remaining(before, minimum):
    if before['error'] or before['remaining'] < minimum:
        raise core.ProtocolError('rate_limit_budget', 'Core API budget is unknown or below --min-remaining; '
                                                      'no command reads were made')


def report(before, client=None):
    after = snapshot(client)
    same_window = not before['error'] and not after['error'] and before['reset'] == after['reset']
    return {'before': before, 'after': after,
            'used_during_command': after['used'] - before['used'] if same_window else None,
            'note': 'Core REST budget of the authenticated token. Other processes may share it, so the difference '
                    'is an upper bound; it is null across a reset window or when a read failed.'}
