"""Tests: a prompt handed to the PM to paste elsewhere is an ask: python3 -m unittest discover -s tests

The light foreman, 2026-10-26: the session « Kit COPIL » ended its message with « Pour le tester sur le COPIL n°10,
colle ceci dans ta session du projet … : », the prompt in a code block, then « Rien d'autre à faire de ton côté. ».
It took no number, and Mon Studio showed nothing: the gesture was set aside as one « the session does not wait on to
go on », and a message read without a probable ask makes no line (Q40). A real ask was lost. So:

  - a gesture followed by a block (« colle ceci : » then ```…```) is an ask, a « Vérifier » line while unnumbered;
  - « Rien à faire de ton côté » (or « Rien d'autre… ») never cancels such a gesture;
  - the session-start instruction of a chantier names the prompt to paste among the gestures that take a number,
    and forbids ending such a message with « Rien (d'autre) à faire de ton côté »; the reminder at each of the PM's
    messages says it too.

The message is the real one, its client and contents replaced."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

from test_cockpit_nothing_forgotten import card, final, pm  # noqa: E402

NOW = time.time()
REAL = ("Le gabarit du mail suit les COPIL passés : les décideurs en À, les points d'abord, le prochain COPIL à la fin. "
        "J'ai ajouté ce qui manquait : une rubrique pour les décisions, une date sur chaque action et une forme stable "
        "d'un mail à l'autre.\n\n"
        "Pour le tester sur le COPIL n°10, colle ceci dans ta session du projet pilote :\n\n"
        "```\nKit COPIL · test du mail de compte rendu. Lis le CR du COPIL n°10 et rédige le mail avec le gabarit "
        "(brouillon seulement, à défaut). Aucun envoi.\n```\n\n"
        "Rien d'autre à faire de ton côté.")


class GestureToPaste(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.CHANTIERS.mkdir()

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def lines(self, text, unread=False):
        path = pathlib.Path(self.tmp.name) / 'kit.jsonl'
        path.write_text(json.dumps(pm(3, 'Le mail ?')) + '\n' + json.dumps(final(2, text)) + '\n', encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(card('local_kit', 'Kit COPIL'), chemin=str(path), derniere=r['depuis'], non_lue=unread, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return parc.tableau([s], [card('local_kit', 'Kit COPIL')], [], 3650, NOW, {})

    def test_the_real_message_makes_a_line_even_once_read(self):
        (l,) = self.lines(REAL)
        self.assertEqual((l['type'], l['lecture']), ('check', 'a_verifier'))
        self.assertIn('colle ceci dans ta session du projet pilote', l['suite'])

    def test_rien_a_faire_never_cancels_a_block_to_paste(self):
        text = REAL.replace("Rien d'autre à faire de ton côté.", "Rien à faire de ton côté.")
        self.assertTrue(parc.rien_a_faire(text))
        self.assertEqual(len(self.lines(text)), 1)

    def test_a_block_shown_without_a_gesture_is_no_ask(self):
        text = "Voici la commande que j'ai lancée :\n\n```\npython3 parc.py --controle\n```\n\nRien à faire de ton côté."
        self.assertEqual(self.lines(text), [])

    def test_a_gesture_without_a_block_keeps_its_sort(self):
        _, _, notes, _ = parc.trier("Tu peux fermer cette session.", expliquer=True)
        self.assertEqual([n['prio'] for n in notes], [None])


class Instructions(unittest.TestCase):
    def test_the_session_start_names_the_prompt_to_paste(self):
        text = (SCRIPTS / 'question.py').read_text(encoding='utf-8')
        self.assertIn('dont un prompt à coller dans une', text)
        self.assertIn("ni par « Rien d\\'autre à faire de ton côté »", text)

    def test_the_reminder_names_it_too(self):
        hooks = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))['hooks']
        (cmd,) = [h['command'] for g in hooks['UserPromptSubmit'] for h in g['hooks'] if 'Mon Studio :' in h['command']]
        self.assertIn('un prompt à coller dans une autre session', cmd)


if __name__ == '__main__':
    unittest.main()
