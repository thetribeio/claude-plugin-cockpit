"""Tests: quoted text is never read as an ask: python3 -m unittest discover -s tests

The foreman of the Studio pilote, 2026-10-23, 9:20: a « Go » line in Mon Studio, « Les vraies demandes restent, comme
« Aucune question pour toi, mais j'attends ton go ». », from the fil rouge's report of a fix. The example it quoted made
the go. So:

  - a quotation of three words or more (« … », “ … ”, " … ", ` … `) is read as « … » by the sort; the line keeps the
    whole text. A shorter one is still read: it is the reply asked for (« go », « Q12 1 »);
  - a sentence is an ask only if it is one with and without its quotations (« « Rien à faire de ton côté » contredisait
    Q112, que je disais en attente de ta réponse » is no ask);
  - a sentence is not cut inside a quotation (« Choisis « Drive partagés › 3. Clients › … ». » stays whole);
  - a sentence about « la demande » or « la ligne », with a determiner, that does not speak to the PM, is no ask, outside
    a « pour toi » section.

The sentences here are synthetic, except the reported one and those of the 14-day replay noted in docs/cockpit.md."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

REPORTED = "Les vraies demandes restent, comme « Aucune question pour toi, mais j'attends ton go »."


def asks(text):
    """The sentences of a message that make a line of Mon Studio."""
    _, _, notes, _ = parc.trier(text, expliquer=True)
    return [n['p'] for n in notes if n['prio'] is not None]


class Quotes(unittest.TestCase):
    def test_the_reported_sentence_makes_no_line(self):
        message = ("J'ai installé deux changements dans ton plugin local.\n\n"
                   "- **Mon Studio n'affiche plus de demande fantôme.** " + REPORTED + "\n\n"
                   "Rien n'est parti sur GitHub.")
        self.assertEqual(asks(message), [])

    def test_a_quoted_ask_is_no_ask(self):
        for phrase in ("Alex a dit « j'attends des propositions concrètes » : ils veulent un plan.",
                       "Question à poser au client : « Tu as pu voir l'installation Javelot ? »",
                       'Le formulaire demande "Dis-moi ce qui ne va pas dans cette réponse".',
                       "La commande montre `dis-moi si c'est faux` au PM.",
                       "Le texte cité « Aucune question. Mais j'attends ton go. » ne compte pas."):
            self.assertEqual(asks(phrase), [], phrase)

    def test_a_short_quote_is_still_the_reply_asked_for(self):
        for phrase in ("J'attends ton « go ».",
                       "Réponds « go » ou « plus tard ».",
                       "Il me manque ta réponse : je supprime la phrase « Sur 5 ans : 366 K€/an », ou je la garde ?",
                       "Choisis « Drive partagés › 3. Clients › Studio F › Studio-Projet-Pilote »."):
            self.assertTrue(asks(phrase), phrase)

    def test_an_ask_only_without_its_quote_is_no_ask(self):
        phrase = "« Rien à faire de ton côté » contredisait Q112, que je venais de dire en attente de ta réponse."
        self.assertEqual(asks(phrase), [])

    def test_a_sentence_is_not_cut_inside_a_quote(self):
        self.assertEqual(parc.couper_phrases("Choisis « Drive partagés › 3. Clients › Studio F ». Puis valide."),
                         ["Choisis « Drive partagés › 3. Clients › Studio F ».", "Puis valide."])

    def test_the_line_keeps_the_quote(self):
        lignes, _, _, _ = parc.trier("Il me manque ta réponse : je supprime « Sur 5 ans : 366 K€/an », ou je la garde ?")
        self.assertIn("« Sur 5 ans : 366 K€/an »", lignes[0])


class TalksAboutAnAsk(unittest.TestCase):
    def test_a_sentence_about_asks_or_lines_is_no_ask(self):
        for phrase in ("Les vraies demandes restent, comme une question avec un go.",
                       "Une demande qui arrive par Slack devient une ligne à trancher.",
                       "La ligne groupes froids sort des points à trancher."):
            self.assertEqual(asks(phrase), [], phrase)

    def test_real_asks_about_questions_stay(self):
        for phrase in ("Mes questions restent ouvertes (PPTX, commande maison, feu vert pour construire init).",
                       "**Feu vert, quand ce sera prêt :** redéployer le kit sur le Studio pilote.",
                       "La ligne de Q3 attend ton go.",
                       "La demande de Léo est-elle à trancher ce soir ?"):
            self.assertTrue(asks(phrase), phrase)


if __name__ == '__main__':
    unittest.main()
