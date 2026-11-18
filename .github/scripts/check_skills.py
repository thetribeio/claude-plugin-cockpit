#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks the header of every skill of the plugin. Run on each pull request and on main.

    python3 .github/scripts/check_skills.py [plugin root]

Two rules, each born of a real case:
- A skill runs only when the PM types it: `disable-model-invocation: true`. The plugin installs as a whole and
  a PM may want only one of its skills; a skill nobody typed must stay inert. A skill that has to trigger on
  its own is listed, with its reason, in .github/auto-invocable-skills.
- No unknown header field. Claude Code ignores a misspelled field without a word: `disable_model_invocation`
  would leave the skill free to run on its own, and nobody would see it.

Messages are in French: they are read by the PM who opened the pull request.
"""
import pathlib
import re
import sys

# Frontmatter fields of a SKILL.md, from the Claude Code skills reference (code.claude.com/docs/en/skills).
KNOWN_FIELDS = {
    'name', 'description', 'when_to_use', 'argument-hint', 'arguments', 'disable-model-invocation',
    'user-invocable', 'allowed-tools', 'disallowed-tools', 'model', 'effort', 'context', 'agent', 'background',
    'hooks', 'paths', 'shell', 'metadata', 'license', 'compatibility',
}
TOP_LEVEL_KEY = re.compile(r'^([^\s#:][^:]*):')


def frontmatter(text):
    """The header's top-level keys and their raw values, or None when the file has no header."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return None
    fields = {}
    for line in lines[1:]:
        if line.strip() == '---':
            return fields
        m = TOP_LEVEL_KEY.match(line)
        if m:
            fields[m.group(1).strip()] = line[m.end():].strip()
    return None


def allowed_auto_invocation(root):
    path = root / '.github' / 'auto-invocable-skills'
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            names.add(line)
    return names


def check(root):
    root = pathlib.Path(root)
    errors = []
    allowed = allowed_auto_invocation(root)
    skills = sorted((root / 'skills').glob('*/SKILL.md'))
    if not skills:
        errors.append('aucun skill trouvé dans skills/*/SKILL.md')
    for skill in skills:
        name = skill.parent.name
        where = skill.relative_to(root)
        fields = frontmatter(skill.read_text(encoding='utf-8'))
        if fields is None:
            errors.append(f'{where} : pas d\'en-tête (il commence et finit par une ligne « --- »)')
            continue
        for key in sorted(set(fields) - KNOWN_FIELDS):
            errors.append(f'{where} : champ inconnu « {key} », Claude Code l\'ignorerait sans le dire '
                          f'(faute de frappe ? les champs s\'écrivent avec des tirets, ex. disable-model-invocation)')
        if name in allowed:
            continue
        value = fields.get('disable-model-invocation')
        if value is None:
            errors.append(f'{where} : il manque « disable-model-invocation: true » : sans cette ligne, Claude peut '
                          f'lancer le skill tout seul. Exception justifiée : ajouter « {name} » et sa raison à '
                          f'.github/auto-invocable-skills')
        elif value.strip('\'"').lower() != 'true':
            errors.append(f'{where} : « disable-model-invocation » vaut « {value} », il doit valoir « true »')
    return errors


def main(argv):
    root = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path(__file__).resolve().parents[2]
    errors = check(root)
    if errors:
        print('En-têtes de skills à corriger :\n- ' + '\n- '.join(errors))
        return 1
    print(f"ok : {len(list((root / 'skills').glob('*/SKILL.md')))} skill(s) vérifié(s)")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
