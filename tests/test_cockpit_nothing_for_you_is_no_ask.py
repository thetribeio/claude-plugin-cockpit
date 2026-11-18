"""Tests: a sentence that says nothing awaits the PM is never an ask: python3 -m unittest discover -s tests

The foreman of the Studio pilote, 2026-10-23: a « Répondre » line stayed 15 hours in Mon Studio, its text « Rien n'est
en attente de ta part de mon côté. », the closing sentence of a message. « en attente de ta » made it a go; only the
exact « Rien à faire de ton côté. » was known. So a sentence whose clause opens on a negation (« rien », « aucune »,
« plus rien », « pas de », « il n'y a rien », « je n'attends rien »), speaks of waiting (attente, question, geste,
décision, à faire, à trancher…) and names the PM is no ask, in any order. It stays an ask when another clause speaks
to the PM, with an exception (« sauf », « mais », « au-delà »), or when the PM is awaited later (« sans ton go »).

The sentences here are synthetic, except the reported one and those of the 14-day replay noted in docs/cockpit.md."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)


def asks(text):
    """The sentences of a message that make a line of Mon Studio."""
    _, _, notes, _ = parc.trier(text, expliquer=True)
    return [n['p'] for n in notes if n['prio'] is not None]


class NothingForYou(unittest.TestCase):
    def test_the_reported_sentence_makes_no_line(self):
        message = ("Le tableau est à jour : la ligne de Q3 est partie au journal.\n\n"
                   "Rien n'est en attente de ta part de mon côté.")
        self.assertEqual(asks(message), [])

    def test_nothing_awaits_the_pm_in_any_order(self):
        for phrase in ("Rien n'est en attente de ta part de mon côté.",
                       "Aucune question ne t'attend.",
                       "Plus rien n'attend ton geste.",
                       "Rien à signaler pour toi.",
                       "De ta part, rien n'est attendu.",
                       "Je n'attends rien de ta part.",
                       "Il n'y a rien à trancher pour toi.",
                       "Pas de question pour toi.",
                       "Aucun feu vert attendu de ta part.",
                       "Pas de go à donner de ton côté.",
                       "Tu n'as rien à trancher.",
                       "Rien n'est décidé ou à faire de ton côté.",
                       "Rien de nouveau à faire de ton côté."):
            self.assertEqual(asks(phrase), [], phrase)

    def test_a_real_ask_stays(self):
        for phrase in ("J'attends ton go sur Q3, rien d'urgent.",
                       "Aucune question pour toi, mais j'attends ton go sur Q3.",
                       "Aucune question pour toi, dis-moi juste si tu valides le texte.",
                       "Rien à préparer de ton côté au-delà de répondre à ces questions.",
                       "Rien n'est en attente de ta part ?",
                       "Il ne reste que ton go sur Q3 à donner.",
                       "Je n'attends que ton feu vert.",
                       "**Rien n'est écrit dans le tableur.** Le diff des 4 lignes attend ton feu vert."):
            self.assertTrue(asks(phrase), phrase)

    def test_a_pm_awaited_later_keeps_its_sort(self):
        # « Rien ne sort sans ton go » says the go is needed: this rule does not decide it, the sort stays as before.
        for phrase in ("Rien ne sort sans ton go.",
                       "Rien n'est écrit sur le site avant ta validation.",
                       "Rien n'a été modifié dans le kit en attendant ta décision."):
            self.assertFalse(parc.rien_pour_toi(parc.nu(phrase)), phrase)


if __name__ == '__main__':
    unittest.main()
