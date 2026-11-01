"""Strict shape checks for remote fields the report commands consume. Wrong types raise; nothing becomes empty."""
import re

from .core import ProtocolError, parse_repository

ASSOCIATIONS = {'COLLABORATOR', 'CONTRIBUTOR', 'FIRST_TIMER', 'FIRST_TIME_CONTRIBUTOR', 'MANNEQUIN', 'MEMBER',
                'NONE', 'OWNER'}
SHA = re.compile('[0-9a-f]{40}')


def bad(what):
    raise ProtocolError('api_shape', 'Invalid GitHub ' + what)


def positive(value, what):
    return value if type(value) is int and value > 0 else bad(what)


def text(value, what, nullable=False):
    if value is None and nullable:
        return None
    return value if isinstance(value, str) else bad(what)


def choice(value, allowed, what, nullable=False):
    if value is None and nullable:
        return None
    return value if isinstance(value, str) and value in allowed else bad(what)


def flag(value, what):
    return value if type(value) is bool else bad(what)


def sha(value, what, nullable=False):
    if value is None and nullable:
        return None
    return value if isinstance(value, str) and SHA.fullmatch(value) else bad(what)


def user(value, what='user'):
    """GitHub returns null for deleted accounts; that is reported as ghost, not as malformed."""
    if value is None:
        return {'login': 'ghost', 'id': None, 'bot': False}
    if not isinstance(value, dict):
        bad(what)
    login = text(value.get('login'), what + ' login')
    kind = text(value.get('type'), what + ' type', nullable=True)
    return {'login': login, 'id': positive(value.get('id'), what + ' ID'),
            'bot': kind == 'Bot' or login.endswith('[bot]')}


def repository(value, what):
    if not isinstance(value, dict):
        bad(what)
    return parse_repository(text(value.get('full_name'), what + ' name')), positive(value.get('id'), what + ' ID')


def pull_url(value, repository_name, number):
    expected = f'https://github.com/{repository_name}/pull/{number}'
    if not isinstance(value, str) or value.casefold() != expected.casefold():
        bad('pull request URL')
    return value
