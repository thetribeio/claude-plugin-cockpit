"""Tests of the line detail in Mon Studio: python3 -m unittest discover -s tests

A click on a line's description unfolds its detail, as the foreman's board does: the full text, what made it appear
(trigger) and when. The mirror carries the line's detail and trigger (question.py); parc.py passes them on to the
pinned page. The session where to act ends the line's text, as on the board (test_cockpit_rows_like_the_board.py).
Boards, mirrors and sessions here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN, KIT = 'local_foreman', 'local_kit'
NOW = 1_760_400_000.0


def card(sid, title, cwd='/studios/Studio-Essai'):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None}


class ForThePage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name)

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def lines(self, waits, sessions=()):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': '2026-10-14T09:00:00+02:00', 'attentes': waits}))
        metas = [card(FOREMAN, 'Contremaître'), card(KIT, 'Kit A · tâche'), card('local_alone', 'Seule', '/studios/Autre')]
        lignes = parc.tableau(list(sessions), metas, [], 7, NOW, {})
        return parc.pour_la_page({'genere': NOW, 'pastilles_lues': True, 'tableau': lignes})['lignes']

    def test_chantier_line_carries_detail_and_trigger(self):
        l, = self.lines([{'type': 'decision', 'titre': 'Q5 · Format du CR', 'ou': 'Kit A', 'source': KIT,
                          'depuis': '2026-10-14T08:00:00+02:00', 'detail': 'Deux formats possibles.', 'declencheur': 'fin du couloir A'}])
        self.assertEqual((l['detail'], l['declencheur']), ('Deux formats possibles.', 'fin du couloir A'))
        self.assertEqual(l['agir_dans'], '')  # the question has no session of its own on the board: nothing to say
        self.assertEqual(l['ouvrir'], KIT)   # the session that asked (PM, 2026-11-06), not the foreman

    def test_review_names_the_kit_session_where_to_act(self):
        l, = self.lines([{'type': 'review', 'titre': 'Q12 · Relire le brief', 'ou': 'Kit A', 'source': KIT,
                          'sessionId': KIT, 'sessionLabel': 'Kit A · tâche', 'depuis': '2026-10-14T08:00:00+02:00'}])
        self.assertEqual((l['ouvrir'], l['agir_dans']), (KIT, 'Kit A · tâche'))

    def test_old_mirror_without_detail(self):
        l, = self.lines([{'type': 'go', 'titre': 'Q6 · Lancer', 'ou': 'Kit A', 'depuis': '2026-10-14T08:00:00+02:00'}])
        self.assertEqual((l['detail'], l['declencheur']), ('', ''))

    def test_cut_title_without_detail_unfolds_whole(self):
        long = 'Q8 · ' + 'mot ' * 80
        l, = self.lines([{'type': 'decision', 'titre': long, 'ou': 'Kit A', 'depuis': '2026-10-14T08:00:00+02:00'}])
        self.assertTrue(l['affiche_suite'].endswith('…'))
        self.assertEqual(l['detail'], long.strip())

    def test_line_outside_a_chantier_unfolds_its_full_text(self):
        stuck = {'id': 'local_alone', 'cwd': '/studios/Autre', 'titre': 'Seule', 'non_lue': False, 'derniere': NOW,
                 'etat': 'suspens', 'depuis': NOW - 600, 'outil': 'Bash'}
        l = [x for x in self.lines([], [stuck]) if x['cle'] == 'local_alone'][0]
        self.assertEqual(l['detail'], l['complet'])
        self.assertIn('Arrêtée en plein travail (commande du terminal)', l['detail'])
        self.assertEqual((l['declencheur'], l['agir_dans']), (None, None))



if __name__ == '__main__':
    unittest.main()
