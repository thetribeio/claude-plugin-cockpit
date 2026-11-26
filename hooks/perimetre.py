#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where the PM's working rules apply: sessions opened in a Studio, not every session of the Mac.

    session_de_studio(cwd=None)      # True when the session's folder is a Studio (or inside one)
    python3 perimetre.py --garde     # for hooks.json: exits 0 in a Studio, 1 elsewhere (the session's folder is read
                                     # from the hook input on stdin, else CLAUDE_PROJECT_DIR, else the current folder)

A session is « de Studio » when its folder (the app's working copy `.claude/worktrees/<name>` counted as its
repository, as projets.py and question.py do) is, or is under:
  - a Studio listed in ~/Mon Studio/projets.json (`studios`, the list Mon Studio itself keeps), or
  - a folder that carries `.claude/.studio-manifest.json` (a Studio Mon Studio does not know yet), or
  - ~/Mon Studio itself, or
  - a folder of `regles_dossiers` in ~/Mon Studio/.parc/cockpit.json (the PM's own additions, e.g. the repository of a
    plugin he works on).
`"regles_partout": true` in cockpit.json brings back the old behaviour (rules in every session).

Any doubt keeps the rules: no folder given, projets.json or cockpit.json present but unreadable, anything unexpected:
the answer is True, as before this limit existed. The home folder alone is never a Studio.

Stdlib only and fast (a few small reads and stat calls): it runs at every message of the PM.
"""
import json
import os
import pathlib
import re
import sys
import unicodedata


def _mon_studio():
    return pathlib.Path(os.environ.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def _dossier(chemin):
    """A folder as projets.py names a Studio: NFC, normalised, the app's worktree brought back to its repository."""
    d = unicodedata.normalize('NFC', os.path.normpath(os.path.expanduser(str(chemin or ''))))
    m = re.match(r'^(.+?)/\.claude/worktrees/[^/]+(?:/.*)?$', d)
    return m.group(1) if m else d


def _sous(ici, base):
    return bool(base) and (ici == base or ici.startswith(base.rstrip(os.sep) + os.sep))


def _lire(chemin):
    """(found, data): found False when the file does not exist; data None when it exists but cannot be read."""
    try:
        texte = pathlib.Path(chemin).read_text(encoding='utf-8')
    except FileNotFoundError:
        return False, None
    except OSError:
        return True, None
    try:
        return True, json.loads(texte)
    except ValueError:
        return True, None


def session_de_studio(cwd=None):
    try:
        return _session_de_studio(cwd)
    except Exception:   # any doubt: the rules stay, as before
        return True


def _session_de_studio(cwd):
    racine = _mon_studio()
    trouve, etat = _lire(racine / '.parc' / 'cockpit.json')
    if trouve and not isinstance(etat, dict):
        return True
    etat = etat or {}
    if etat.get('regles_partout') is True:
        return True
    cwd = cwd or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    if not isinstance(cwd, str) or not cwd.strip():
        return True
    ici = _dossier(cwd)
    maison = os.path.normpath(str(pathlib.Path.home()))
    variantes = {ici, _dossier(os.path.realpath(ici))}

    def dedans(base):
        base = _dossier(base)
        if base == maison:
            return False
        return any(_sous(v, b) for v in variantes for b in {base, _dossier(os.path.realpath(base))})

    if dedans(racine):
        return True
    plus = etat.get('regles_dossiers')
    if isinstance(plus, list) and any(isinstance(p, str) and p.strip() and dedans(p) for p in plus):
        return True
    trouve, projets = _lire(racine / 'projets.json')
    if trouve:
        listes = projets.get('studios') if isinstance(projets, dict) else None
        if not isinstance(listes, list):
            return True   # projets.json present but unreadable: doubt
        for st in listes:
            d = st.get('dossier') if isinstance(st, dict) else None
            if isinstance(d, str) and d.strip() and dedans(d):
                return True
    # A Studio Mon Studio does not list: a manifest in the folder or above it (never the home folder or above).
    cur = ici
    while cur and cur != maison and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, '.claude', '.studio-manifest.json')):
            return True
        cur = os.path.dirname(cur)
    return False


def main(argv):
    cwd = None
    try:
        if not sys.stdin.isatty():
            donnees = json.loads(sys.stdin.read() or '{}')
            cwd = donnees.get('cwd') if isinstance(donnees, dict) else None
    except Exception:
        cwd = None
    if '--garde' in argv:
        return 0 if session_de_studio(cwd) else 1
    print('oui' if session_de_studio(cwd) else 'non')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
