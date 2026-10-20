"""Set only the independent Majiro TITLEBAR field to an ASCII work title.

Majiro environment tokens use | for a space; literal spaces begin comments.
Registry locations, save descriptions, script text and native code are untouched.
"""
import re


TITLES = {
    'narci_onetwo': 'Narcissu 1 & 2',
    'narci_himeko': "Narcissu - Himeko's Epilogue",
    'narci_iris': 'Narcissu : A Little Iris',
    'narci_sumire': 'Narcissu : Sumire',
    'narci_zero': 'Narcissu : Zero',
}

_ORIGINALS = {
    'narci_onetwo': ('ナルキッソス1+2', 'Narcissu 1 & 2'),
    'narci_himeko': ('雨のマージナル', "Narcissu - Himeko's Epilgoue"),
    'narci_iris': ('ナルキッソス外伝－小さなイリス－', 'Narcissu : A Little Iris'),
    'narci_sumire': ('ナルキッソス－スミレ－', 'Narcissu : Sumire'),
    'narci_zero': ('ナルキッソス０－ZERO－', 'Narcissu : Zero'),
}
_DECLARATION = re.compile(rb'(?m)^[\t ]*TITLEBAR(?:[\t ]|\r?$)')
_FIELD = re.compile(rb'(?m)^(TITLEBAR[\t ]+)([^\r\n]*)(\r?)$')


def patch_titlebar(game, env_bytes):
    """Return (environment bytes, report), rejecting missing/unknown fields.

    The recognized input check in the installer remains separate. This helper
    requires a known field value as well, and never silently skips a missing env.
    """
    if game not in TITLES:
        raise ValueError('Unsupported window-title module')
    if not isinstance(env_bytes, bytes):
        raise ValueError('majiro.env must be bytes')
    declarations = list(_DECLARATION.finditer(env_bytes))
    fields = list(_FIELD.finditer(env_bytes))
    if len(declarations) != 1 or len(fields) != 1:
        raise ValueError('majiro.env requires exactly one standalone TITLEBAR field')
    field = fields[0]
    title = TITLES[game]
    token = title.replace(' ', '|').encode('ascii')
    known = {value.encode('cp932') for value in _ORIGINALS[game]}
    known.update((title.encode('ascii'), token))
    original = field[2]
    if original not in known:
        raise ValueError('Unsupported or modified TITLEBAR value')
    result = env_bytes[:field.start(2)] + token + env_bytes[field.end(2):]
    return result, {'field': 'majiro.env:TITLEBAR', 'title_ascii': title,
                    'token': token.decode('ascii'), 'changed': original != token}
