"""Tests of the Session column of a chantier line without a subject in Mon Studio: python3 -m unittest discover -s tests

A line that comes from a foreman's mirror and has no subject (no lane on the board) names, in bold, the session where
its subject lives (the wait's source), not the foreman, with « Chantier <name> » below. A line with a subject shows
the subject alone (test_cockpit_rows_like_the_board.py); the source still drives « Voir la session » and the unread
dot. The verb leads to the session that asked (PM, 2026-11-06), never to the foreman when a source exists; the
question number is copied only when it is that session's own (its sessionId); « Voir la session » would open the same
session, so it is gone. Mirrors and session cards here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN, KIT, PILLAR, ALONE = 'local_foreman', 'local_kit', 'local_pillar', 'local_alone'
NOW = 1_760_400_000.0
SINCE = '2026-10-14T08:00:00+02:00'


def card(sid, title, archived=False, cwd='/studios/Studio-Essai'):
    return {'id': sid, 'archivee': archived, 'cwd': cwd, 'titre': title, 'parent': None}


class SessionColumn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name)
        self.transcript = pathlib.Path(self.tmp.name) / 'vide.jsonl'
        self.transcript.write_text('')

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def session(self, sid, unread, **extra):
        """A live session that asks nothing by itself (Claude is working): it only carries its unread dot."""
        cwd = '/studios/Autre' if sid == ALONE else '/studios/Studio-Essai'
        return dict({'id': sid, 'cwd': cwd, 'titre': sid, 'non_lue': unread, 'derniere': NOW, 'etat': 'travaille',
                     'depuis': NOW - 600, 'chemin': str(self.transcript)}, **extra)

    def compute(self, waits, cards=None, sessions=()):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': SINCE, 'attentes': waits}))
        cards = cards if cards is not None else [card(FOREMAN, 'Contremaître'), card(KIT, 'ᐅ Kit A · tâche'),
                                                 card(PILLAR, 'ᐅ Kit A · fil rouge'), card(ALONE, 'Seule', cwd='/studios/Autre')]
        return parc.tableau(list(sessions), cards, [], 7, NOW, {})

    def line(self, wait, cards=None, sessions=()):
        l, = [x for x in self.compute([dict({'depuis': SINCE}, **wait)], cards, sessions) if x.get('chantier')]
        return parc.pour_la_page({'genere': NOW, 'pastilles_lues': True, 'tableau': [l]})['lignes'][0]

    def test_source_is_named_and_the_verb_opens_it(self):
        l = self.line({'type': 'decision', 'titre': 'Q45 · Format du CR', 'source': KIT, 'pilier': PILLAR})
        self.assertEqual((l['session'], l['sous'], l['sujet']), ('ᐅ Kit A · tâche', 'Chantier Essai', ''))
        # The verb: the session that asked; the number is the foreman's (no sessionId), so nothing is copied.
        self.assertEqual((l['ouvrir'], l['question'], l['copie_numero']), (KIT, 'Q45', False))
        self.assertEqual((l['source'], l['source_titre']), (KIT, 'ᐅ Kit A · tâche'))
        self.assertEqual(l['nommee'], KIT)  # a click on the name opens the named session
        self.assertEqual(l['agir_dans'], '')

    def test_the_number_is_copied_when_it_is_the_session_own(self):
        l = self.line({'type': 'decision', 'titre': 'Q45 · Format du CR', 'source': KIT, 'sessionId': KIT,
                       'sessionLabel': 'ᐅ Kit A · tâche'})
        self.assertEqual((l['ouvrir'], l['question'], l['copie_numero'], l['cle']), (KIT, 'Q45', True, FOREMAN))

    def test_unread_dot_follows_the_source(self):
        wait = {'type': 'go', 'titre': 'Q46 · Lancer', 'source': KIT}
        self.assertTrue(self.line(wait, sessions=[self.session(KIT, True), self.session(FOREMAN, False)])['non_lue'])
        self.assertFalse(self.line(wait, sessions=[self.session(KIT, False), self.session(FOREMAN, True)])['non_lue'])

    def test_without_source_the_kit_pillar(self):
        l = self.line({'type': 'decision', 'titre': 'Q47 · Choix', 'pilier': PILLAR})
        self.assertEqual((l['session'], l['source'], l['ouvrir']), ('ᐅ Kit A · fil rouge', PILLAR, PILLAR))

    def test_without_source_nor_pillar_the_foreman(self):
        l = self.line({'type': 'decision', 'titre': 'Q48 · Choix'})
        self.assertEqual((l['session'], l['source'], l['ouvrir'], l['nommee']), ('Contremaître', '', FOREMAN, FOREMAN))

    def test_archived_source_falls_back_to_the_pillar(self):
        cards = [card(FOREMAN, 'Contremaître'), card(KIT, 'ᐅ Kit A · tâche', archived=True), card(PILLAR, 'ᐅ Kit A · fil rouge')]
        l = self.line({'type': 'decision', 'titre': 'Q49 · Choix', 'source': KIT, 'pilier': PILLAR}, cards)
        self.assertEqual((l['session'], l['source']), ('ᐅ Kit A · fil rouge', PILLAR))

    def test_archived_source_and_pillar_name_the_foreman(self):
        cards = [card(FOREMAN, 'Contremaître'), card(KIT, 'ᐅ Kit A · tâche', archived=True),
                 card(PILLAR, 'ᐅ Kit A · fil rouge', archived=True)]
        l = self.line({'type': 'decision', 'titre': 'Q50 · Choix', 'source': KIT, 'pilier': PILLAR}, cards)
        self.assertEqual((l['session'], l['source'], l['ouvrir']), ('Contremaître', '', FOREMAN))

    def test_unknown_source_names_the_foreman(self):
        l = self.line({'type': 'task', 'titre': 'Q51 · Geste', 'source': 'local_gone'})
        self.assertEqual((l['session'], l['source']), ('Contremaître', ''))

    def test_source_is_the_foreman_itself(self):
        l = self.line({'type': 'decision', 'titre': 'Q52 · Choix', 'source': FOREMAN})
        self.assertEqual((l['session'], l['source'], l['ouvrir']), ('Contremaître', '', FOREMAN))

    def test_review_keeps_its_rule(self):
        l = self.line({'type': 'review', 'titre': 'Q12 · Relire le brief', 'source': KIT})
        self.assertEqual((l['session'], l['ouvrir'], l['source'], l['question'], l['copie_numero']), ('ᐅ Kit A · tâche', KIT, KIT, 'Q12', False))
        self.assertEqual(l['nommee'], KIT)  # name and verb open the same session
        self.assertEqual(l['agir_dans'], '')  # the question has no session of its own on the board: nothing to say

    def test_open_menu_keeps_its_rule(self):
        menu = parc.lire_menu({'questions': [{'question': 'Je lance ?', 'options': [{'label': 'Oui'}, {'label': 'Non'}]}]})
        l = self.line({'type': 'go', 'titre': 'Q53 · Lancer', 'source': KIT, 'depuis': SINCE},
                      sessions=[self.session(KIT, True, etat='suspens', menu=menu)])
        self.assertEqual((l['session'], l['ouvrir'], l['source'], l['non_lue']), ('ᐅ Kit A · tâche', KIT, KIT, True))

    def test_line_outside_a_chantier_unchanged(self):
        stuck = self.session(ALONE, True, etat='suspens', outil='Bash', titre='Seule')
        lines = self.compute([{'type': 'decision', 'titre': 'Q54 · Choix', 'source': KIT, 'depuis': SINCE}], sessions=[stuck])
        l, = [x for x in lines if x['cle'] == ALONE]
        self.assertEqual((l['session'], l['ouvrir'], l.get('source'), l['non_lue']), ('Seule', ALONE, None, True))
        self.assertNotIn('sous', l)
        self.assertNotIn('nommee', l)

    def test_markdown_names_the_source(self):
        lines = self.compute([{'type': 'decision', 'titre': 'Q55 · Format du CR', 'ou': 'Chantier', 'source': KIT, 'depuis': SINCE}])
        e = {'genere': NOW, 'pastilles_lues': True, 'tableau': lines}
        md = parc.rendre_md(e)
        self.assertIn(f'| [ᐅ Kit A · tâche](#{KIT})<br>Chantier Essai |', md)
        self.assertIn('| Répondre | 0 min |', md)   # the name opens the session; no second link to the same one
        self.assertNotIn('Voir la session', md)

    def test_markdown_review_verb_stays_plain(self):
        lines = self.compute([{'type': 'review', 'titre': 'Q56 · Relire', 'source': KIT, 'depuis': SINCE}])
        md = parc.rendre_md({'genere': NOW, 'pastilles_lues': True, 'tableau': lines})
        self.assertIn(f'| [ᐅ Kit A · tâche](#{KIT})<br>Chantier Essai |', md)
        self.assertIn('| Relire |', md)


if __name__ == '__main__':
    unittest.main()
