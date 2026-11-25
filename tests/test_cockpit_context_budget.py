"""Tests: what the plugin puts into every session stays under a ceiling (2026-11-17, token study of the week).

Every session starts with about 100,000 tokens before the PM's first word, reread at each call: 49 % of a week's
tokens. What the plugin adds is small (the rules, the skill descriptions, the line added to each message), and it must
not grow unnoticed. A change that goes over a ceiling fails here: shorten something else, or raise the ceiling in the
same commit and say why in the changelog. python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Bytes of UTF-8 text, about 3.7 per token in French.
RULES_TOTAL = 10_500         # regles/*.md, given at the start of every session (9,741 in 0.3.2; 9,906 in 0.3.10: rule 4 says the app's end-of-turn card starts with the same « Qn · titre »; 10,369 in 0.3.12: rule 6 of modele-effort, the session sets its own model and effort at its first message)
OPTIONAL_RULE = 1_500        # one rule of regles/optionnelles/, given only when the PM turned it on
SKILL_DESCRIPTIONS = 1_700   # the descriptions listed in every session, all skills together (1,516 on 2026-11-17)
EACH_MESSAGE = 240           # what a UserPromptSubmit hook echoes at every message of the PM, kept until the session ends


def size(path):
    return len(path.read_text(encoding='utf-8').strip().encode('utf-8'))


def description(skill):
    for line in skill.read_text(encoding='utf-8').splitlines()[1:]:
        if line.startswith('description:'):
            return line[len('description:'):].strip()
        if line.strip() == '---':
            break
    return ''


class ContextBudget(unittest.TestCase):
    def test_the_rules_given_to_every_session_stay_under_their_ceiling(self):
        sizes = {p.name: size(p) for p in sorted((ROOT / 'regles').glob('*.md'))}
        total = sum(sizes.values())
        self.assertLessEqual(total, RULES_TOTAL, f'regles/*.md : {total} octets pour un plafond de {RULES_TOTAL} ({sizes}). '
                             'Raccourcir une règle, ou relever le plafond dans le même commit en disant pourquoi.')

    def test_an_optional_rule_stays_short(self):
        for p in sorted((ROOT / 'regles' / 'optionnelles').glob('*.md')):
            self.assertLessEqual(size(p), OPTIONAL_RULE, p.name)

    def test_the_skill_descriptions_stay_under_their_ceiling(self):
        sizes = {p.parent.name: len(description(p).encode('utf-8')) for p in sorted(ROOT.glob('skills/*/SKILL.md'))}
        self.assertTrue(all(sizes.values()), f'un skill sans description : {sizes}')
        self.assertLessEqual(sum(sizes.values()), SKILL_DESCRIPTIONS, str(sizes))

    def test_the_line_added_to_each_message_stays_short(self):
        hooks = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))['hooks']
        echoed = [m.group(1) for group in hooks.get('UserPromptSubmit', []) for h in group['hooks']
                  for m in re.finditer(r'echo "((?:[^"\\]|\\.)*)"', h['command'])]
        self.assertTrue(echoed, 'la ligne de rappel a disparu de hooks.json : revoir ce test')
        for text in echoed:
            self.assertLessEqual(len(text.encode('utf-8')), EACH_MESSAGE, text)


if __name__ == '__main__':
    unittest.main()
