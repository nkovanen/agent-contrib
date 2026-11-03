"""Deterministic, inert SVG cards from validated local receipt observations."""
import unicodedata
import xml.etree.ElementTree as ET

from . import core, receipts

NOTICE = ('Local editable observation, not authenticated. Agent involvement is self-reported; '
          'no claim of tests, quality, acceptance, benefit or permission. Share manually.')
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def _text(value):
    # XML 1.0 forbids some scalars; format controls can disguise identity/state visually.
    return ' '.join(''.join(c if unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Cn')
                            else ' ' for c in value).split())


def _units(value):
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') or c in 'MW@%' else 1
               for c in value)


def _fit(value, limit):
    if _units(value) <= limit:
        return value
    out = ''
    for char in value:
        if _units(out + char) > limit - 1:
            break
        out += char
    return out.rstrip() + '…'


def _lines(value, limit=43, count=3):
    remaining, lines = value, []
    for index in range(count):
        if _units(remaining) <= limit or index == count - 1:
            lines.append(_fit(remaining, limit))
            break
        part = _fit(remaining, limit + 1)[:-1]
        split = part.rfind(' ')
        if split >= len(part) // 2:
            part = part[:split]
        lines.append(part)
        remaining = remaining[len(part):].lstrip()
    return lines


def render(path, *, caption=None):
    """Read once through the receipt trust boundary; no remote reads or inferred achievements."""
    receipt = receipts.load(path)
    pr, repo = receipt['pull_request'], receipt['repository']['full_name']
    if caption is not None and (not isinstance(caption, str) or not 1 <= len(caption) <= 4096
                                or not _text(caption)):
        raise core.ProtocolError('invalid_caption', 'Personal caption must contain 1–4096 characters of readable text')
    title = _text(caption) if caption is not None else f"Pull request #{pr['number']} · title not recorded"
    context = 'Personal caption · not a GitHub title' if caption is not None else 'Receipt 0.1 · GitHub title not recorded'
    svg = ET.Element(f'{{{NS}}}svg', {'viewBox': '0 0 1200 800', 'width': '1200', 'height': '800',
                                    'role': 'img', 'aria-labelledby': 'card-title card-desc'})

    def node(tag, parent=svg, text=None, **attrs):
        element = ET.SubElement(parent, f'{{{NS}}}{tag}', {k.replace('_', '-'): str(v) for k, v in attrs.items()})
        element.text = text
        return element

    node('title', id='card-title', text=f'Agent work gift · {repo} #{pr["number"]}: {title}')
    node('desc', id='card-desc', text=f'{context}: {title}. Observed {pr["state"]} at {receipt["observed_at"]}. {NOTICE}')
    node('rect', width=1200, height=800, rx=28, fill='#f7f3e9')
    node('rect', x=20, y=20, width=1160, height=760, rx=18, fill='none', stroke='#d8d8c9')
    group = node('g', fill='#26291f', font_family='Arial, sans-serif')

    def text(x, y, value, size=24, **attrs):
        return node('text', parent=group, x=x, y=y, text=value, font_size=size, **attrs)

    text(64, 90, 'tipjar', 38, font_weight=800, letter_spacing='-1.5')
    text(64, 139, 'GIVE YOUR AGENT A GOOD CAUSE.', 17, letter_spacing=2, fill='#66695b')
    text(64, 232, 'Agent work,', 64, font_family='Georgia, serif')
    text(64, 300, 'given forward.', 64, font_family='Georgia, serif', font_style='italic', fill='#b44621')
    text(65, 347, 'A gift of agent work to open source · self-reported', 23, fill='#66695b')

    node('circle', cx=1012, cy=244, r=119, fill='#e9eddf')
    jar = node('g', transform='translate(924 124) scale(1.1)', fill='none', stroke='#25281f', stroke_width=6)
    node('path', parent=jar, d='M38 27h84v19l13 19v91c0 13-10 23-23 23H48c-13 0-23-10-23-23V65l13-19V27Z', fill='#ed693a')
    node('rect', parent=jar, x=32, y=13, width=96, height=20, rx=6, fill='#f6eddb')
    node('path', parent=jar, d='M43 46h74M43 60v19M43 91v49M43 159h72', stroke_width=5, stroke_linecap='round')
    node('path', parent=jar, d='m63 103-15 15 15 15m34-30 15 15-15 15m-13-35-10 41', stroke='#fff6e4', stroke_width=7, stroke_linecap='round', stroke_linejoin='round')

    node('rect', x=56, y=390, width=1088, height=261, rx=14, fill='#fffcf4', stroke='#d8d8c9')
    text(80, 430, _fit(repo, 52), 24, font_weight=700, font_family='monospace', aria_label=repo)
    node('rect', x=902, y=407, width=218, height=40, rx=20, fill='#e9eddf')
    text(1011, 434, f'Observed {pr["state"]}', 21, text_anchor='middle')
    text(80, 464, context, 18, fill='#66695b')
    for index, line in enumerate(_lines(title)):
        text(80, 502 + 39 * index, line, 32, font_weight=600)
    link = node('a', parent=group, href=pr['url'], aria_label=f'View pull request {repo} #{pr["number"]}')
    node('text', parent=link, x=80, y=625, text=f'GitHub · pull request #{pr["number"]} ↗', font_size=23, fill='#9e3c1b', text_decoration='underline')
    text(1120, 625, f'Observed {receipt["observed_at"][:10]} UTC', 21, text_anchor='end', fill='#66695b')
    text(64, 706, 'Local editable observation · not authenticated', 23, font_weight=600)
    text(64, 742, 'No claim of tests, quality, acceptance, benefit or permission.', 21, fill='#66695b')
    svg.remove(group)
    svg.append(group)  # Paint readable content above the panel and badge backgrounds.
    return ET.tostring(svg, encoding='unicode', xml_declaration=False) + '\n', receipt
