"""Tests of skills/cockpit/scripts/parc.py: « Voir la session » never opens an archived session.
python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN = 'local_foreman'


def card(sid, archived=False, cwd='/studio', title=None):
    return {'id': sid, 'archivee': archived, 'cwd': cwd, 'titre': title or sid, 'parent': None}


class SessionToShow(unittest.TestCase):
    def show(self, wait, cards):
        found = parc.session_qui_en_parle(wait, FOREMAN, {c['id']: c for c in cards})
        return found['id'] if found else None

    def test_live_source(self):
        self.assertEqual(self.show({'source': 'local_kit', 'pilier': 'local_pillar'},
                                   [card('local_kit'), card('local_pillar')]), 'local_kit')

    def test_archived_source_falls_back_to_the_kit_pillar(self):
        self.assertEqual(self.show({'source': 'local_kit', 'pilier': 'local_pillar'},
                                   [card('local_kit', archived=True), card('local_pillar')]), 'local_pillar')

    def test_archived_source_and_pillar_show_nothing(self):
        self.assertIsNone(self.show({'source': 'local_kit', 'pilier': 'local_pillar'},
                                    [card('local_kit', archived=True), card('local_pillar', archived=True)]))

    def test_unknown_source_without_pillar_shows_nothing(self):
        self.assertIsNone(self.show({'source': 'local_gone'}, [card('local_kit')]))

    def test_never_the_foreman(self):
        self.assertIsNone(self.show({'source': FOREMAN}, [card(FOREMAN)]))


class ArchivedForTheBoard(unittest.TestCase):
    def test_lists_archived_sessions_the_board_could_open(self):
        cards = [card(FOREMAN), card('local_kit', archived=True), card('local_pillar', archived=True, cwd='/elsewhere'),
                 card('local_live'), card('local_other', archived=True, cwd='/other-studio')]
        mirror = {'sessionId': FOREMAN, 'attentes': [{'titre': 'Q44 · Raccourci', 'source': 'local_kit', 'pilier': 'local_pillar'}],
                  'piliers': [{'titre': 'Kit', 'sessionId': 'local_pillar'}]}
        self.assertEqual(parc.archivees_des_chantiers([mirror], cards), ['local_kit', 'local_pillar'])


if __name__ == '__main__':
    unittest.main()
