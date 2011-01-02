"""Internationalization module."""

from ConfigParser import SafeConfigParser, NoSectionError, NoOptionError
from os.path import join as j
from os import sep
from sys import prefix

COMMANDS = 'Commands'
DEFAULT = 'DEFAULT'
DISCO = 'Service discovery'
ROSTER = 'Roster interaction'

_paths = []
for dir in [j(prefix, 'share'), j(prefix, 'local', 'share'), j(sep, 'etc')]:
    _paths.append(j(dir, 'bitcoim', 'messages'))

fallbackLangs = ['en']
"""Fallback languages to try in turn, when a translation in a certain language
didn't work.
"""

_parsers = {}

def _(section, key, lang=None, fallback=fallbackLangs):
    '''Translate `key` (found in [`section`]) in `lang`. The translation is
       looked up in the paths given by `paths`.
       If the lookup fails, the translation is intented again with each
       language given in the `fallback` list, whose default value is that of
       `i18n.fallbackLangs`.
    '''
    nxt = list(fallback)
    if lang is None:
        try:
            lang = nxt.pop(0)
        except IndexError:
            return key
    if not lang in _parsers:
        _parsers[lang] = SafeConfigParser()
        _parsers[lang].read(map(lambda p: j(p, lang), _paths))
    try:
        return _parsers[lang].get(section, key)
    except NoSectionError, NoOptionError:
        return _(section, key, None, nxt)
