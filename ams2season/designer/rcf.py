"""Read and edit a Madness .rcf (REPLACEMENT_SYSTEM) livery table with minimal text diffs.

Edits work on the raw text so comments, CRLF line endings and the author's formatting survive.
"""
import re
from html import escape
import xml.etree.ElementTree as ET


# Some mods ship a typo like <CONDITION LIVERY="63> (closing quote missing). The game copes; XML parsers don't.
_UNCLOSED = re.compile(r'(<[A-Za-z_]+\s+[A-Za-z_]+=")(\d+)(\s*/?>)')


def repair(text):
    """The same text with known typos fixed (see _UNCLOSED); unchanged if there are none."""
    return _UNCLOSED.sub(r'\1\2"\3', text)


def repairs(text):
    """Line numbers repair() would change."""
    return [text.count('\n', 0, m.start()) + 1 for m in _UNCLOSED.finditer(text)]


def _root(text):
    if not text.strip():
        raise ValueError("the car's livery list (.rcf) is empty")
    try:
        return ET.fromstring(repair(text).encode('utf-8'))
    except ET.ParseError as e:
        raise ValueError(f"the car's livery list (.rcf) isn't valid XML ({e})") from None


def check(text):
    """Raise ValueError with a readable message if the livery list can't be read (empty or broken XML)."""
    _root(text)


def liveries(text):
    """{livery id: {'name': str, 'texture': game-relative path of the common_paint replacement or None}}"""
    root = _root(text)
    names = {int(n.get('LIVERY')): n.get('NAME') for n in root.iter('NAME') if n.get('LIVERY')}
    out = {i: {'name': n, 'texture': None} for i, n in names.items()}
    for c in root.iter('CONDITION'):
        if c.get('LIVERY') is None:
            continue
        lid = int(c.get('LIVERY'))
        for r in c.iter('REPLACE'):
            if (r.get('TEXTURE') or '').lower().endswith('common_paint.dds'):
                out.setdefault(lid, {'name': names.get(lid, f'Livery {lid}'), 'texture': None})['texture'] = r.get('NEWTEXTURE')
    return dict(sorted(out.items()))


def _condition(text, livery):
    m = re.search(r'([ \t]*)<CONDITION LIVERY="%d">.*?</CONDITION>' % livery, text, re.S)
    if not m:
        raise KeyError(f'no CONDITION block for livery {livery}')
    return m


LIVERY_SPECIFIC = ('banner', 'common_paint_spec', 'common_paint_fresnel')   # lines that belong to one livery's own design


def add_slot(text, new_id, name, texture, template_id, drop=LIVERY_SPECIFIC, spec=None):
    """Clone template_id's CONDITION block as new_id with common_paint.dds pointing at `texture`.

    spec: optional (texture the paint material uses, our finish map) to add a finish-map replacement.
    """
    text = repair(text)
    nl = '\r\n' if '\r\n' in text else '\n'
    have = liveries(text)
    if new_id in have:
        raise ValueError(f'livery {new_id} already exists ({have[new_id]["name"]})')
    name = escape(name, quote=True)
    m = re.search(r'(<INPUT NAME="LIVERY" OPTIONS=")(\d+)(")', text)
    text = text[:m.start(2)] + str(int(m.group(2)) + 1) + text[m.end(2):]
    last = max(have)
    m = re.search(r'([ \t]*)<NAME LIVERY="%d"[^>]*/>[^\r\n]*' % last, text)
    text = text[:m.end()] + f'{nl}{m.group(1)}<NAME LIVERY="{new_id}" NAME="{name}" />' + text[m.end():]
    tpl = _condition(text, template_id).group(0)
    block = nl.join(l for l in tpl.splitlines() if not any(d in l.lower() for d in drop))
    block = block.replace(f'<CONDITION LIVERY="{template_id}">', f'<CONDITION LIVERY="{new_id}">')
    block = re.sub(r'(REPLACE TEXTURE="[^"]*common_paint\.dds" NEWTEXTURE=")[^"]+(")',
                   lambda mm: mm.group(1) + texture + mm.group(2), block, flags=re.I)
    if spec:
        block = _with_spec(block, spec, nl)
    anchor = _condition(text, last)
    text = text[:anchor.end()] + nl + nl + block + text[anchor.end():]
    after = liveries(text)
    assert set(after) == set(have) | {new_id} and after[new_id]['texture'] == texture
    return text


def _with_spec(block, spec, nl):
    """Drop any finish-map line from a CONDITION block, then add ours (if any) after the common_paint line.

    spec = (source texture, new texture[, material swap lines]) - the swap lines make the paint use a
    material that reads a finish map (borrowed from the car's own liveries that do the same).
    """
    lines = [l for l in block.split(nl) if 'common_paint_spec' not in l.lower()]
    if spec:
        src, new, *rest = spec
        swaps = rest[0] if rest else []
        swapped = {re.search(r'MATERIAL="([^"]+)"', s).group(1).lower() for s in swaps}
        lines = [l for l in lines if not (re.search(r'REPLACE MATERIAL="([^"]+)"', l) and
                                           re.search(r'REPLACE MATERIAL="([^"]+)"', l).group(1).lower() in swapped)]
        for i, l in enumerate(lines):
            if re.search(r'REPLACE TEXTURE="[^"]*common_paint\.dds"', l, re.I):
                indent = re.match(r'[ \t]*', l).group(0)
                lines[i:i] = [indent + s.strip() for s in swaps]
                lines.insert(i + len(swaps) + 1, f'{indent}<REPLACE TEXTURE="{src}" NEWTEXTURE="{new}" />')
                break
        else:
            raise ValueError('no common_paint replacement in this livery block')
    return nl.join(lines)


def set_spec(text, livery, spec):
    """Point a livery's finish map at spec=(source texture, new texture), or remove it (spec=None)."""
    text = repair(text)
    nl = '\r\n' if '\r\n' in text else '\n'
    m = _condition(text, livery)
    return text[:m.start()] + _with_spec(m.group(0), spec, nl) + text[m.end():]


def spec_of(text, livery):
    """The finish-map texture a livery uses, or None."""
    m = re.search(r'REPLACE TEXTURE="[^"]*common_paint_spec\.dds" NEWTEXTURE="([^"]+)"', _condition(repair(text), livery).group(0), re.I)
    return m.group(1) if m else None


def condition_text(text, livery):
    return _condition(repair(text), livery).group(0)


def conditions(text):
    """{livery id: CONDITION block text}"""
    return {int(m.group(1)): m.group(0) for m in re.finditer(r'<CONDITION LIVERY="(\d+)">.*?</CONDITION>', repair(text), re.S)}


def rename_slot(text, livery, name):
    text = repair(text)
    name = escape(name, quote=True)
    new, n = re.subn(r'(<NAME LIVERY="%d" NAME=")[^"]*(")' % livery, lambda m: m.group(1) + name + m.group(2), text)
    if n != 1:
        raise KeyError(f'no NAME entry for livery {livery}')
    return new


def remove_slot(text, livery):
    """Remove a livery's NAME + CONDITION and decrement OPTIONS (the inverse of add_slot)."""
    text = repair(text)
    have = liveries(text)
    if livery not in have:
        raise KeyError(f'livery {livery} not found')
    text = re.sub(r'\r?\n[ \t]*<NAME LIVERY="%d"[^>]*/>[^\r\n]*' % livery, '', text, count=1)
    m = _condition(text, livery)
    start = m.start()
    pre = re.search(r'(\r?\n){1,2}$', text[:start])            # also eat the blank line we inserted before it
    if pre:
        start = pre.start()
    text = text[:start] + text[m.end():]
    m = re.search(r'(<INPUT NAME="LIVERY" OPTIONS=")(\d+)(")', text)
    text = text[:m.start(2)] + str(int(m.group(2)) - 1) + text[m.end(2):]
    after = liveries(text)
    assert set(after) == set(have) - {livery}
    return text
