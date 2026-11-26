"""Tests: a sentence that says nothing awaits the PM is never an ask: python3 -m unittest discover -s tests

The foreman of the Studio pilote, 2026-10-23: a « Répondre » line stayed 15 hours in Mon Studio, its text « Rien n'est
en attente de ta part de mon côté. ». The general reading of « rien n'est en attente de ta part » (rien_pour_toi) is
gone: it only ever acted on sessions long finished, and a session now says it waits for nothing by « Rien à faire de ton
côté » (rien_a_faire). What stays here is the negation of the sort (NEGATION: « rien à faire », « aucun feu vert »,
« pas besoin »…), and that a real ask next to a negation, or a PM awaited later, is still an ask.

The sentences here are synthetic, except those of the 14-day replay noted in docs/cockpit.md."""
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
    def test_a_negation_of_the_sort_makes_no_line(self):
        for phrase in ("Pas besoin de ton go sur Q3.",
                       "Rien à faire de ton côté sur ce point.",
                       "Aucune action de ta part."):
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
        # « Rien ne sort sans ton go » says the go is needed: the sort keeps it.
        for phrase in ("Rien ne sort sans ton go.",
                       "Rien n'est écrit sur le site avant ta validation.",
                       "Rien n'a été modifié dans le kit en attendant ta décision."):
            self.assertTrue(asks(phrase), phrase)


if __name__ == '__main__':
    unittest.main()
