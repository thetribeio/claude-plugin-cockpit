"""What a line unfolds to (PM, 2026-11-06): python3 -m unittest discover -s tests

A click on a session's line shows, in short bullets, what the session expects of the PM, nothing else: its open
numbered questions (« Qn · titre », its options in a few words), then the sentences of its last message that ask him
something (each cut short); else the last sentence. No copied block (« Juste avant, son message disait… »), no
trigger that only explains Mon Studio; « Apparue » stays. Messages here are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc_depli', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
_VIDE = tempfile.TemporaryDirectory()
parc.CHANTIERS = pathlib.Path(_VIDE.name)   # no real mirror ever read here
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'

ATTENDS = ("Le tableau est prêt, avec deux onglets. J'ai vérifié les liens un par un.\n\n"
           "J'attends les 3 ajouts aux articles existants, puis je les mets dans un dernier onglet.\n\n"
           "Encore ouvert : Q14 (mode de partage du tableau).")


def session(texte, **more):
    return dict({'id': 'local_a', 'cwd': '/studios/Studio-Beta', 'titre': 'Démarrage', 'non_lue': True, 'derniere': 1e9,
                 'etat': 'attend', 'depuis': 1e9, 'texte': texte, 'chemin': '/dev/null'}, **more)


class Bullets(unittest.TestCase):
    def test_the_real_case_lists_what_the_session_waits_for(self):
        puces = parc.ce_qu_attend(session(ATTENDS, questions={'14': {'titre': 'Q14 · Mode de partage',
                                                                       'suite': 'lien en lecture ou copie ?'}}))
        self.assertEqual(puces, ['Q14 · Mode de partage : lien en lecture ou copie ?',
                                 "J'attends les 3 ajouts aux articles existants, puis je les mets dans un dernier onglet."])

    def test_numbered_questions_with_their_options(self):
        texte = ("Voici le bilan.\n\n**À trancher**\n\nQ3 · Format du CR : lequel ?\n1. Une page (recommandé)\n2. Un mail\n"
                 "Q4 · Envoi : je l'envoie à Léo, go ?")
        self.assertEqual(parc.ce_qu_attend(session(texte)),
                         ['Q3 · Format du CR : Une page / Un mail', "Q4 · Envoi : je l'envoie à Léo, go ?"])

    def test_requests_then_last_sentence(self):
        texte = "J'ai fini l'analyse.\n\nDonne-moi le fichier des ventes. Valide aussi le périmètre, sinon je ne peux rien lancer."
        self.assertEqual(parc.ce_qu_attend(session(texte)),
                         ['Donne-moi le fichier des ventes.', 'Valide aussi le périmètre, sinon je ne peux rien lancer.'])
        self.assertEqual(parc.ce_qu_attend(session("Tout est en place. Le tableau se met à jour seul.")),
                         ['Le tableau se met à jour seul.'])

    def test_a_list_after_a_request_is_carried(self):
        texte = "Reste à faire de ton côté :\n\n- confirmer le réel de septembre ;\n- valider la feuille de temps."
        self.assertEqual(parc.ce_qu_attend(session(texte, tete='Reste à faire de ton côté :')),
                         ['confirmer le réel de septembre ;', 'valider la feuille de temps.'])

    def test_bullets_are_short_and_few(self):
        texte = ' '.join(f"Donne-moi le fichier numéro {i} " + 'avec ' * 40 + '.' for i in range(10))
        puces = parc.ce_qu_attend(session(texte))
        self.assertLessEqual(len(puces), parc.PUCES_MAX)
        self.assertTrue(all(len(p) <= parc.PUCE_MAX + 2 for p in puces))

    def test_the_line_carries_bullets_and_no_copied_block(self):
        texte = "Long compte rendu.\n\nJe peux lancer la suite quand tu veux, mais rien ne presse vraiment pour l'instant ici."
        sessions = [session(texte, prio=3, tete="Je peux lancer la suite quand tu veux")]
        cards = [{'id': 'local_a', 'archivee': False, 'cwd': '/studios/Studio-Beta', 'titre': 'Démarrage', 'parent': None}]
        for l in parc.tableau(sessions, cards, [], 7, 1e9 + 60, {}):
            self.assertTrue(parc.rang_page(l)['puces'])   # the page unfolds to them, not to the detail


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    def test_the_unfold_shows_bullets_and_when(self):
        ligne = {'studio': 'Beta', 'session': 'Démarrage', 'cle': 'local_a', 'type': 'check', 'verbe': 'Vérifier',
                 'affiche_suite': "J'attends les 3 ajouts", 'puces': ['Q14 · Mode de partage', "J'attends les 3 ajouts"],
                 'detail': "J'attends les 3 ajouts. Juste avant, son message disait : « un long pavé »",
                 'declencheur': 'La session n\'a ni numéroté de question'}
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'p.json'
            data.write_text(json.dumps({'lignes': [ligne]}, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True, timeout=60)
        out = json.loads(r.stdout)
        self.assertIn('<ul class="attendu"><li>Q14 · Mode de partage</li><li>J&#39;attends les 3 ajouts</li></ul>', out['tableau'])
        self.assertIn('<dt>Apparue</dt>', out['tableau'])
        self.assertNotIn('Déclencheur', out['tableau'])
        self.assertNotIn('Juste avant', out['tableau'])


if __name__ == '__main__':
    unittest.main()
