"""Strict shape checks for remote fields the report commands consume. Wrong types raise; nothing becomes empty."""
import re

from .core import MAX_PAGES, ProtocolError, parse_repository, require

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


def counted_pages(client, endpoint, key, parse, *, page, count, noun, oversize, malformed='', check_page=None):
    """Read pages that carry total_count (check runs, commit statuses): object pages with an inner list of at most
    100 items, unique IDs, a stable count the final page must match, and a 40-page cap. parse returns (id, record).
    A malformed item ends the read: nothing after it is trusted. Returns (records, errors, finished)."""
    records, errors, seen, total = [], [], set(), None
    for number in range(1, MAX_PAGES + 1):
        try:
            data = require(client.request(f'{endpoint}?per_page=100&page={number}'), dict, page)
            if check_page is not None:
                check_page(data, errors)
            value = data.get('total_count')
            if type(value) is not int or value < 0:
                bad(count.lower())
            if total is not None and value != total:
                errors.append(count + ' changed during pagination')
            total = value
            batch = require(data.get(key), list, key.replace('_', ' '))
            if len(batch) > 100:
                raise ProtocolError('api_shape', oversize)
            for item in batch:
                try:
                    identity, record = parse(require(item, dict, noun))
                except ProtocolError as exc:
                    raise ProtocolError(exc.code, malformed + str(exc)) from None
                if identity in seen:
                    errors.append(f'Pagination repeated a {noun}; results may have moved')
                    continue
                seen.add(identity)
                records.append(record)
            if len(batch) < 100:
                if len(seen) != total:
                    errors.append(count + ' does not match total_count')
                return records, errors, True
        except ProtocolError as exc:
            return records, errors + [str(exc)], False
    return records, errors + ['Pagination reached the 40-page limit'], False
