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
        if values['used'] + values['remaining'] != values['limit']:
            raise core.ProtocolError('api_shape', 'Inconsistent GitHub core rate limit counters')
        return {**values, 'error': None}
    except core.ProtocolError as exc:
        return {**{name: None for name in FIELDS}, 'error': str(exc)}


def require_remaining(before, minimum):
    if before['error'] or before['remaining'] < minimum:
        raise core.ProtocolError('rate_limit_budget', 'Core API budget is unknown or below --min-remaining; '
                                                      'no command reads were made')


def report(before, client=None):
    after = snapshot(client)
    if before['error'] or after['error']:
        reason = 'a snapshot failed or was inconsistent'
    elif before['reset'] != after['reset']:
        reason = 'the reset window changed'
    elif before['limit'] != after['limit']:
        reason = 'the limit changed'
    elif after['used'] < before['used']:
        reason = 'the used counter decreased'
    else:
        reason = None
    return {'before': before, 'after': after,
            'used_during_command': None if reason else after['used'] - before['used'],
            'delta_unknown_reason': reason,
            'note': 'Core REST budget of the authenticated token. Other processes may share it, so the difference '
                    'is an upper bound; it is null with a reason when the snapshots cannot be compared.'}
