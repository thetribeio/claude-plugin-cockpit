"""Tests: Mon Studio reads any PM, not only the marks of the PM who wrote it: python3 -m unittest discover -s tests

The PM, 2026-10-28, for the pilote plugin: the sorter must not depend on one PM's writing rules. Each case below is
written twice, once with the marks of a PM whose sessions end with numbered questions (« À trancher », « Q1 · … »,
« Rien à faire de ton côté »), once in the natural style of a session without them. The screen must show a line in
both styles or in neither; in the natural style the verb is « Vérifier », never a guessed « Go ». One exception, by
design: a natural message with no ask shows « Vérifier » while it is unread, since nothing says it waits for nothing.

A PM's own marks go in a glossary outside the plugin (~/.claude/cockpit/marqueurs.md, MON_STUDIO_MARQUEURS in the
tests): an ask expression, a closing formula, a section heading. A mark never forces a line the sorter sets aside
(a negation, « À savoir », a condition), and a free closing (« Rien n'est attendu de toi. ») never erases an ask."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
from test_cockpit_nothing_forgotten import card, final, pm  # noqa: E402

NOW = time.time()
EXAMPLE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'marqueurs-exemple.md'

# name: (with the PM's marks, natural style or None, a line expected). Gestures (checkboxes, a block to paste, an
# imperative) are no longer guessed: only a question, a go or a decision asked makes a line in the natural style.
CASES = {
    'decision': ("Le plan est prêt.\n\n## À trancher\n\n**Q1 · Format du CR** : court ou long ? Je recommande court.",
                 "Le plan est prêt. Tu préfères un CR court ou long ? Je recommande court.", True),
    'go': ("Le mail est prêt.\n\n## À trancher\n\n**Q2 · Envoi** : j'envoie le mail au client ? Réponds « go ».",
           "Le mail est prêt. J'attends ton go pour l'envoyer.", True),
    'options': ("## À trancher\n\n**Q3 · Hébergement** : où héberger ?\n- A) chez le client\n- B) chez nous",
                "Deux options pour l'hébergement :\n\n- A) chez le client\n- B) chez nous\n\nLaquelle tu choisis ?",
                True),
    'your_call': ("## À trancher\n\n**Q6 · Arbitrage** : à toi de trancher entre les deux devis.",
                  "À toi de trancher entre les deux devis.", True),
    'want': ("## À trancher\n\n**Q7 · Relance** : veux-tu que je relance le client ?",
             "Veux-tu que je relance le client ?", True),
    'nothing': ("Le fichier est rangé.\n\nRien à faire de ton côté.", None, False),
}


def screen(text, unread):
    tmp = tempfile.mkdtemp()
    parc.CHANTIERS = pathlib.Path(tmp) / 'ch'
    parc.CHANTIERS.mkdir()
    path = pathlib.Path(tmp) / 'k.jsonl'
    path.write_text(json.dumps(pm(3, 'Alors ?')) + '\n' + json.dumps(final(2, text)) + '\n', encoding='utf-8')
    r = parc._analyser(str(path), NOW)
    s = dict(card('local_k', 'Kit'), chemin=str(path), derniere=r['depuis'], non_lue=unread, **r)
    s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
    return [l['verbe'] for l in parc.tableau([s], [card('local_k', 'Kit')], [], 3650, NOW, {})]


class Glossary(unittest.TestCase):
    """Each test gets its own glossary file; none is read unless the test writes one."""

    def setUp(self):
        self.saved = parc.MARQUEURS
        parc.MARQUEURS = pathlib.Path(tempfile.mkdtemp()) / 'cockpit' / 'marqueurs.md'
        parc._marqueurs['vu'] = 0.0

    def tearDown(self):
        parc.MARQUEURS = self.saved
        parc._marqueurs['vu'] = 0.0


class TwoStyles(Glossary):
    def test_a_line_in_both_styles_or_in_neither(self):
        for name, (marked, natural, expected) in CASES.items():
            for unread in (False, True):
                with self.subTest(name, unread=unread):
                    self.assertEqual(bool(screen(marked, unread)), expected)
                    if natural is not None:   # a free closing is no longer guessed: an unread one shows « Vérifier »
                        self.assertEqual(bool(screen(natural, unread)), expected)

    def test_the_natural_style_never_guesses_a_go(self):
        for name, (_, natural, expected) in CASES.items():
            if expected:
                with self.subTest(name):
                    self.assertEqual(screen(natural, False), ['Vérifier'])

    def test_an_unread_natural_message_without_ask_shows_check_until_read(self):
        text = "Le fichier est rangé dans le dossier projet."
        self.assertEqual(screen(text, True), ['Vérifier'])
        self.assertEqual(screen(text, False), [])

class FreeClosing(Glossary):
    def test_a_free_closing_never_erases_an_ask(self):
        text = "Tu valides le devis avant jeudi ?\n\nPour le reste, rien n'est attendu de toi."
        self.assertFalse(parc.rien_a_faire(text))
        self.assertEqual(screen(text, False), ['Vérifier'])

    def test_the_pm_formula_keeps_its_effect(self):
        self.assertTrue(parc.rien_a_faire("Le fichier est rangé.\n\nRien à faire de ton côté."))


class PmMarkers(Glossary):
    def test_no_glossary_no_marker(self):
        self.assertFalse(parc.MARQUEURS.exists())
        self.assertEqual(parc.marqueurs(), {'demande': [], 'rien': [], 'trancher': []})
        self.assertEqual(parc.signature_marqueurs(), '')
        self.assertIsNone(parc.classer("Le devis est prêt, point d'attention PM.", 'phrase', {})[0])

    def test_an_ask_marker_makes_a_line(self):
        self.assertTrue(parc.ajouter_marqueur('demande', "point d'attention PM"))
        self.assertEqual(parc.classer("Le devis est prêt, point d'attention PM.", 'phrase', {})[0], 2)
        self.assertEqual(screen("Le devis est prêt, point d'attention PM.", False), ['Vérifier'])

    def test_a_marker_never_forces_a_line_the_sorter_sets_aside(self):
        parc.ajouter_marqueur('demande', "point d'attention PM")
        for p, ctx in (("Pas besoin de point d'attention PM ici.", {}),
                       ("Si le lot glisse, point d'attention PM.", {}),
                       ("Le devis est prêt, point d'attention PM.", {'a_savoir': True})):
            with self.subTest(p):
                self.assertIsNone(parc.classer(p, 'phrase', ctx)[0])

    def test_a_closing_marker_says_nothing_is_expected(self):
        text = "Le fichier est rangé.\n\nTout roule de mon côté."
        self.assertFalse(parc.rien_a_faire(text))
        parc.ajouter_marqueur('rien', 'Tout roule de mon côté')
        self.assertTrue(parc.rien_a_faire(text))
        self.assertEqual(screen(text, True), [])

    def test_a_heading_marker_opens_a_section_of_questions(self):
        self.assertIsNone(parc.debut_section('## Décisions attendues'))
        parc.ajouter_marqueur('trancher', 'Décisions attendues')
        self.assertEqual(parc.debut_section('## Décisions attendues'), 'trancher')
        self.assertEqual(parc.debut_section('**Décisions attendues :**'), 'trancher')
        self.assertIsNone(parc.debut_section('Décisions attendues hier par le client, toutes prises.'))

    def test_adding_a_marker_keeps_the_file_and_resorts_read_sessions(self):
        parc.MARQUEURS.parent.mkdir(parents=True)
        parc.MARQUEURS.write_text("# Mes marqueurs\n\n## Demande\n\n- ton arbitrage\n\nUne note à moi.\n",
                                  encoding='utf-8')
        before = parc.signature_marqueurs()
        self.assertTrue(parc.ajouter_marqueur('demande', 'pour validation PM'))
        self.assertTrue(parc.ajouter_marqueur('rien', 'tout roule'))
        text = parc.MARQUEURS.read_text(encoding='utf-8')
        self.assertIn('- ton arbitrage\n- pour validation PM\n', text)
        self.assertIn('Une note à moi.', text)
        self.assertIn('## Rien à faire\n\n- tout roule\n', text)
        self.assertNotEqual(parc.signature_marqueurs(), before)

    def test_a_bad_rubric_or_an_empty_expression_is_refused(self):
        self.assertFalse(parc.ajouter_marqueur('autre', 'quelque chose'))
        self.assertFalse(parc.ajouter_marqueur('demande', ' '))
        self.assertFalse(parc.MARQUEURS.exists())

    def test_the_command_adds_a_marker(self):
        env = dict(os.environ, MON_STUDIO_MARQUEURS=str(parc.MARQUEURS))
        ok = subprocess.run([sys.executable, str(SCRIPTS / 'parc.py'), '--marqueur', 'demande', 'à arbitrer'],
                            capture_output=True, text=True, env=env)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn('- à arbitrer', parc.MARQUEURS.read_text(encoding='utf-8'))
        bad = subprocess.run([sys.executable, str(SCRIPTS / 'parc.py'), '--marqueur', 'autre', 'x y z'],
                             capture_output=True, text=True, env=env)
        self.assertEqual(bad.returncode, 2)

    def test_the_shipped_example_reads_in_every_rubric(self):
        parc.MARQUEURS = EXAMPLE
        m = parc.marqueurs()
        self.assertIn('rien a faire de ton cote', m['rien'])
        self.assertIn('a trancher', m['trancher'])
        self.assertTrue(m['demande'])


if __name__ == '__main__':
    unittest.main()
