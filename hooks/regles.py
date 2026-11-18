#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session-start hook: puts the PM's working rules (regles/*.md) into the session's context.

Optional rules (regles/optionnelles/*.md, the publication hours since the adoption test of 2026-11-02) are given only
when the PM asked for them: `"regles_optionnelles": ["heures-publication"]` in cockpit.json, set by
`install.py switch regle heures-publication on`.

The plugin brings the rules without touching the PM's ~/.claude/CLAUDE.md: they come with the plugin and go with
it, nothing to clean up. A rule the PM already imports in his CLAUDE.md (any `@…` line, whatever its folder) is not
given twice: it is recognised by its file name, with a plural or singular word counted as the same name
(`@modeles-effort.md` covers `modele-effort.md`). When every rule is already imported, nothing is printed.

Silent unless Mon Studio is installed (~/Mon Studio/.parc/cockpit.json, or $MON_STUDIO), and never fails a session.

    python3 regles.py            # what the hook prints
    python3 regles.py --liste    # which rules would be printed and which are already imported, for whoever maintains
"""
import os
import pathlib
import re
import sys

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
RULES = PLUGIN_ROOT / 'regles'
OPTIONAL = RULES / 'optionnelles'
IMPORT = re.compile(r'(?:^|\s)@(\S+\.md)\b')


def mon_studio(env=None):
    env = os.environ if env is None else env
    return pathlib.Path(env.get('MON_STUDIO') or (pathlib.Path.home() / 'Mon Studio'))


def claude_md_files(env=None):
    """The PM's own memory files that may already import the rules."""
    env = os.environ if env is None else env
    config = pathlib.Path(env['CLAUDE_CONFIG_DIR']) if env.get('CLAUDE_CONFIG_DIR') else pathlib.Path.home() / '.claude'
    return [config / 'CLAUDE.md']


def key(name):
    """A rule's name for comparison: its stem, each word without a final s (modeles-effort == modele-effort)."""
    stem = pathlib.PurePath(name).name
    stem = stem[:-3] if stem.lower().endswith('.md') else stem
    return '-'.join(w[:-1] if w.endswith('s') and len(w) > 2 else w for w in stem.lower().split('-'))


def imported(files):
    found = set()
    for f in files:
        try:
            text = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for line in text.splitlines():
            for m in IMPORT.finditer(line):
                found.add(key(m.group(1)))
    return found


def optional_wanted(env=None):
    """The optional rules the PM turned on (cockpit.json, regles_optionnelles), by name."""
    import json
    try:
        state = json.loads((mon_studio(env) / '.parc' / 'cockpit.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return set()
    wanted = state.get('regles_optionnelles') if isinstance(state, dict) else None
    return {key(str(n)) for n in wanted} if isinstance(wanted, list) else set()

def all_rules(env=None):
    """The rules given by default, and the optional ones the PM turned on."""
    wanted = optional_wanted(env)
    return sorted(RULES.glob('*.md')) + sorted(r for r in OPTIONAL.glob('*.md') if key(r.name) in wanted)

def rules_to_print(env=None):
    already = imported(claude_md_files(env))
    rules = all_rules(env)
    return [r for r in rules if key(r.name) not in already], [r for r in rules if key(r.name) in already]


def main(argv):
    try:
        if not (mon_studio() / '.parc' / 'cockpit.json').is_file():
            return 0
        todo, skipped = rules_to_print()
        if '--liste' in argv:
            print('données : ' + (', '.join(r.name for r in todo) or 'aucune'))
            print('déjà importées par le PM : ' + (', '.join(r.name for r in skipped) or 'aucune'))
            return 0
        if not todo:
            return 0
        parts = ['Règles de travail du PM (plugin cockpit), valables dans toute la session :']
        for r in todo:
            parts.append(r.read_text(encoding='utf-8').strip())
        print('\n\n'.join(parts))
    except Exception:  # a hook never stops a session from starting
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
