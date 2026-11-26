"""A question « Qn · Titre ? question » with no « : » (PM, 2026-11-26): python3 -m unittest discover -s tests

1. Mon Studio cuts the title at the first « ? » (kept) when there is no « : »; with « : » nothing changes.
2. The end-of-turn check sends the session back (`sans_deux_points`) and never flags a well-formed question.
Texts are made up, no client name."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'

spec = importlib.util.spec_from_file_location('parc_sans_deux_points', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

LONGUE = "Le devis d'Ana est signé depuis le 12/10 et le client attend une réponse avant la fin de la semaine."


def message(ligne):
    return ("Prêt.\n\n**À trancher**\n\n" + ligne + "\n"
            "1) **Oui** (recommandé) : on lance.\n2) **Non** : on attend.\n"
            "Pourquoi : c'est plus simple. Si tu ne fais rien : rien ne part.\n")


def premiere(ligne):
    return [i for i in parc.a_trancher(message(ligne))[0] if i['num']][0]


class Titre(unittest.TestCase):
    def test_without_colon_the_title_stops_at_the_question_mark(self):
        it = premiere(f"Q3 · Faut-il garder le devis de Léo ? {LONGUE}")
        self.assertEqual(it['titre'], 'Q3 · Faut-il garder le devis de Léo ?')
        self.assertTrue(it['suite'].startswith('Le devis d'))

    def test_with_colon_nothing_changes(self):
        it = premiere(f"Q3 · Garder le devis de Léo : {LONGUE}")
        self.assertEqual(it['titre'], 'Q3 · Garder le devis de Léo')
        it = premiere(f"Q3 · Garder le devis de Léo ? : {LONGUE}")
        self.assertEqual(it['titre'], 'Q3 · Garder le devis de Léo ?')
        it = premiere(f"Q3 · Garder le devis ? (impact fort : échéance) : {LONGUE}")
        self.assertEqual(it['titre'], 'Q3 · Garder le devis ? (impact fort : échéance)')

    def test_a_colon_before_the_question_mark_is_the_separator(self):
        it = premiere("Q3 · Devis : faut-il le garder ? Oui ou non.")
        self.assertEqual(it['titre'], 'Q3 · Devis')

    def test_a_title_alone_followed_by_its_options_is_untouched(self):
        it = premiere("Q3 · Faut-il garder le devis de Camille ?")
        self.assertEqual(it['titre'], 'Q3 · Faut-il garder le devis de Camille ?')


class Controle(unittest.TestCase):
    def setUp(self):
        s = importlib.util.spec_from_file_location('format_questions_sdp', ROOT / 'hooks' / 'format_questions.py')
        sys.path.insert(0, str(ROOT / 'hooks'))
        self.hook = importlib.util.module_from_spec(s)
        s.loader.exec_module(self.hook)

    def kinds(self, ligne):
        return [k for k, _ in self.hook.ecarts(parc, premiere(ligne))]

    def test_a_missing_colon_is_flagged(self):
        self.assertIn('sans_deux_points', self.kinds(f"Q3 · Faut-il garder le devis de Robin ? {LONGUE}"))

    def test_well_formed_questions_are_not_flagged(self):
        for ligne in (f"Q3 · Garder le devis de Sam : {LONGUE}",
                      f"Q3 · Garder le devis de Sam ? : {LONGUE}",
                      f"Q3 · Garder le devis de Sam ? (impact faible) : {LONGUE}",
                      f"Q3 · Garder le devis (bloquante) : {LONGUE}",
                      f"**Q3 · Garder le devis de Sam** : {LONGUE}",
                      "Q3 · Devis : faut-il le garder ? Oui ou non.",
                      "Q3 · Faut-il garder le devis de Alex ?"):
            self.assertNotIn('sans_deux_points', self.kinds(ligne), ligne)

    def test_the_reason_tells_what_to_write(self):
        raison = self.hook.raison([(3, [('sans_deux_points', None)])])
        self.assertIn('« : »', raison)
        self.assertIn('Qn · <titre', raison)


if __name__ == '__main__':
    unittest.main()
