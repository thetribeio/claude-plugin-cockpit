"""Tests: `install.py plan` shows the PM what each item costs a day before the go (2026-11-09, blocker 2 of the
publication review): python3 -m unittest discover -s tests

Each item comes with its tokens a day and its part of the week, dated and marked as measured on the author's seat;
then the total against the maintainer's thresholds. The foreman is retired: no cost line names it."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
ITEMS = ('la page Mon Studio et le connecteur', 'les règles, au démarrage de chaque session',
         'la ligne de rappel, à chaque message', "Point du matin » (Sonnet, effort par défaut de l'app (élevé))",
         "Point du matin · vérification » (Haiku, effort par défaut de l'app (élevé))", '/cockpit:point',
         'le registre des questions, au démarrage', 'le registre des questions, par question')


class PlanCosts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = pathlib.Path(self.tmp.name)
        with mock.patch.dict(os.environ, {'HOME': str(home)}):
            os.environ.pop('MON_STUDIO', None)
            spec = importlib.util.spec_from_file_location('install_plan_costs', SCRIPTS / 'install.py')
            self.i = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.i)
        self.i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(self.i.sys, 'platform', 'darwin'):
            self.lines = self.i.plan()

    def test_every_item_has_its_tokens_and_part_of_the_week_a_day(self):
        for item in ITEMS:
            line = next((l for l in self.lines if item in l), None)
            self.assertIsNotNone(line, item)
            self.assertRegex(line, r'[\d ,M]+ tokens écrits, [\d ,M]+ en sortie et [\d ,M]+ relus en cache par jour, '
                                   r'\d+,\d+ \$, \d+,\d+ % de la semaine par jour, \d+,\d+ % par semaine')

    def test_dated_measured_on_the_author_seat_with_total_and_thresholds(self):
        text = '\n'.join(self.lines)
        self.assertIn(f'mesuré le {self.i.COSTS_DATE} sur la place de l\'auteur', text)
        total = next(l for l in self.lines if l.strip().startswith('total :'))
        self.assertRegex(total, r'\d+,\d+ % par semaine \(seuil : 2 %\)')
        self.assertIn('(seuil : 0,5 %)', total)
        self.assertNotRegex(text.lower(), r'contremaître|cockpit:suivre')

    def test_the_morning_tasks_are_priced_at_their_model(self):
        prices = {c[0]: self.i.cost_usd(c) for c in self.i.COSTS}
        self.assertAlmostEqual(prices["la tâche « Point du matin » (Sonnet, effort par défaut de l'app (élevé))"], 0.45, delta=0.01)
        self.assertAlmostEqual(prices["« Point du matin · vérification » (Haiku, effort par défaut de l'app (élevé))"], 0.44,
                               delta=0.01)
        self.assertLess(100 * sum(prices.values()) / self.i.WEEK_USD * self.i.ACTIVE_DAYS, 2.0)

    def test_the_readme_table_is_the_plan_recomputed_from_its_tokens(self):
        # A reader recomputes each $ from the tokens with the stated list prices: the README says what plan says.
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        rows = [l for l in readme.splitlines() if l.startswith('| ') and l.count('|') == 9][1:]
        self.assertEqual(len(rows), len(self.i.COSTS) + 1)
        for row, c in zip(rows, self.i.COSTS):
            cells = [x.strip() for x in row.strip('|').split('|')]
            self.assertEqual(cells[5], self.i.fr(self.i.cost_usd(c), 2) if c[2] else '0', row)
        total = sum(self.i.cost_usd(c) for c in self.i.COSTS)
        self.assertIn(f'**{self.i.fr(total, 2)}**', rows[-1])
        self.assertIn(f'{self.i.fr(total, 2)} $ par jour', readme)

class MorningEstimates(PlanCosts):
    def test_the_morning_tasks_say_high_effort_and_only_the_morning_one_is_an_estimate(self):
        for c in self.i.COSTS[3:5]:
            self.assertIn("effort par défaut de l'app (élevé)", c[0])
        self.assertIn('estimation à remesurer', self.i.COSTS[3][1])
        self.assertIn('mesuré le 2026-11-18', self.i.COSTS[4][1])
        self.assertNotIn('estimation', self.i.COSTS[4][1])
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        doc = (ROOT / 'docs' / 'consigne-point-du-matin.md').read_text(encoding='utf-8')
        skill = (ROOT / 'skills' / 'mon-studio' / 'SKILL.md').read_text(encoding='utf-8')
        for text in (readme, doc, skill):
            self.assertIn('à remesurer', text)
        self.assertEqual(readme.count("effort par défaut de l'app (élevé)"), 2)
        self.assertNotIn('effort low', (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8').split('## 0.2.1')[0])


class VerificationOnSonnet(PlanCosts):
    def test_the_sonnet_option_is_priced_at_its_real_order_of_magnitude_and_marked_unmeasured(self):
        line = next(l for l in self.lines if l.strip().startswith('option Sonnet pour la vérification'))
        self.assertIn('estimation, non mesurée', line)
        self.assertRegex(line, r'environ 2,4 à 2,7 \$ par passage, 7,7 \$ par jour pour trois passages, \d,\d+ % de la semaine par jour, '
                               r'2,7 % par semaine, au-dessus à elle seule du seuil de 2 %')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('2,4 à 2,7 dollars par passage, 7,7 dollars par jour', readme)
        self.assertEqual(self.i.TASK_MODELS['point-du-matin-verif'], 'haiku')
        self.assertEqual(self.i.ALSO_MODELS['point-du-matin-verif'], ['sonnet'])

    def test_no_dollar_sign_before_punctuation_in_the_readme(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'\$[^\w\s]|\$ [,.;:)]', readme))


class PasteBlock(PlanCosts):
    def test_plan_ends_with_a_short_block_to_paste_unchanged(self):
        start = self.lines.index(self.i.PASTE_START)
        end = self.lines.index(self.i.PASTE_END)
        self.assertEqual(end, len(self.lines) - 1)
        block = self.lines[start + 1:end]
        self.assertEqual(len(block), len(self.i.COSTS) + 4, 'a header, one line per item, the total, the first relevé, the seat')
        for line, c in zip(block[1:], self.i.COSTS):
            self.assertTrue(line.startswith(f'- {c[0]} : '), line)
            if sum(c[2:5]):
                self.assertRegex(line, r'[\d ,M]+ tokens \(dont [\d ,M]+ relus en cache\), \d+,\d+ \$, \d+,\d+ % de la semaine')
        self.assertIn('sur une offre plus petite, les mêmes dollars pèsent plus', block[-1])
        self.assertRegex(block[-3], r'^- Total : [\d ,M]+ tokens, \d+,\d+ \$ par jour, \d+,\d+ % de la semaine par semaine')
        # Once per Studio, outside the daily total: the first relevé of the conflicts, as measured (2026-11-18).
        self.assertRegex(block[-2], r'^- Une fois par Studio, le premier relevé des conflits .* [\d ,M]+ tokens \(dont [\d ,M]+ relus '
                                    r'en cache\), 5,23 \$, 0,36 % de la semaine')

    def test_the_skill_says_to_paste_it_unchanged(self):
        skill = (ROOT / 'skills' / 'mon-studio' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn(self.i.PASTE_START, skill)
        self.assertIn(self.i.PASTE_END, skill)
        self.assertIn('sans rien y changer : ni retirer les tokens', skill)


if __name__ == '__main__':
    unittest.main()
