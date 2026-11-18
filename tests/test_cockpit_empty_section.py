"""Tests: an empty « À trancher » section makes no line: python3 -m unittest discover -s tests

Adversarial review of 2026-10-29, before the cockpit enters the agency catalog: a session that follows the reminder
of Mon Studio loosely (« À trancher : rien. », « ## À trancher / Aucune. », « ## To decide / None. ») made a phantom
« Répondre » line, even once read, in the PM's own format. The same happened under a heading of the PM's glossary.
A line that only says the section is empty is not a question; a real question in the same section still is."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
from test_cockpit_two_styles import screen  # noqa: E402

EMPTY = ("## À trancher\n\nAucune.",
         "## À trancher\n\nAucune.\n\nRien à faire de ton côté.",
         "## À trancher\n\nAucune question.",
         "**À trancher** : rien pour l'instant.",
         "À trancher : rien.",
         "Le fichier est rangé.\n\n## À trancher\n\n- Aucune pour l'instant.",
         "## À trancher\n\nRien pour l'instant : je continue.",
         "## À trancher\n\nNéant.",
         "## To decide\n\nNone.",
         "## To decide\n\nNothing for now.")


class EmptySection(unittest.TestCase):
    def test_a_section_that_says_it_is_empty_makes_no_line(self):
        for text in EMPTY:
            for unread in (False, True):
                with self.subTest(text, unread=unread):
                    self.assertEqual(screen(text, unread), [])

    def test_the_parser_keeps_no_item_for_it(self):
        for text in EMPTY:
            with self.subTest(text):
                self.assertEqual(parc.a_trancher(text)[0], [])

    def test_a_real_question_in_the_section_still_counts(self):
        self.assertEqual(screen("## À trancher\n\n**Q4 · Devis** : je l'envoie ?", False), ['Répondre'])
        self.assertEqual(screen("## À trancher\n\nAucune.\n\n**Q4 · Devis** : je l'envoie ?", False), ['Répondre'])
        self.assertEqual(len(screen("## À trancher\n\nRien de plus ? Je peux fermer le sujet.", False)), 1)
        self.assertEqual(len(screen("## À trancher\n\nRien : valide le devis avant jeudi.", False)), 1)
        self.assertEqual(len(parc.a_trancher("## À trancher\n\nAucune objection à lever avant jeudi ?")[0]), 1)
        self.assertEqual(len(parc.a_trancher("## À trancher\n\nRien à signaler, mais relis le devis.")[0]), 1)

    def test_a_glossary_heading_inherits_the_rule(self):
        saved = parc.MARQUEURS
        parc.MARQUEURS = pathlib.Path(tempfile.mkdtemp()) / 'marqueurs.md'
        parc._marqueurs['vu'] = 0.0
        try:
            parc.ajouter_marqueur('trancher', 'Décisions attendues')
            self.assertEqual(screen("## Décisions attendues\n\nAucune.\n\nRien à faire de ton côté.", True), [])
            self.assertEqual(len(screen("## Décisions attendues\n\nOn garde le lot 2 ou on le coupe ?", False)), 1)
        finally:
            parc.MARQUEURS = saved
            parc._marqueurs['vu'] = 0.0


if __name__ == '__main__':
    unittest.main()
