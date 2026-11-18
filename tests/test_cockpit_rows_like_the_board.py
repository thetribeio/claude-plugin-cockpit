"""Tests of a chantier line shown like the foreman's board: python3 -m unittest discover -s tests

A line that comes from a foreman's mirror shows its subject alone in the Session column (the board's first column),
not the session nor « Chantier <name> », and the subject opens nothing. Its text ends as on the board with
« · à traiter dans la session « <label> » » when the question has its own session on the board and it is not the
foreman's (the board's todoItem rule: sessionId and sessionLabel of the userQueue line). The verb leads to that
session (PM, 2026-11-06), never to the foreman when a source exists.
Lines outside a chantier do not change. Boards, mirrors and session cards here are synthetic."""
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

FOREMAN, KIT, PILLAR, ALONE = 'local_foreman', 'local_kit', 'local_pillar', 'local_alone'
NOW = 1_760_400_000.0
SINCE = '2026-10-20T11:56:01+02:00'
SUBJECT = "Catalogue de l'org"
LABEL = 'plugin product-kits & skill cockpit'

def card(sid, title, cwd='/studios/product-kits'):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None}

CARDS = [card(FOREMAN, 'Foreman PM'), card(KIT, LABEL), card(PILLAR, 'ᐅ Kit A · fil rouge'),
         card(ALONE, 'Seule', cwd='/studios/Autre')]


class Rows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name)

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def compute(self, waits, sessions=()):
        (parc.CHANTIERS / 'product-kits.json').write_text(json.dumps(
            {'chantier': 'Product kits', 'sessionId': FOREMAN, 'misAJour': SINCE, 'attentes': waits}))
        return parc.tableau(list(sessions), CARDS, [], 7, NOW, {})

    def line(self, wait, sessions=()):
        l, = [x for x in self.compute([dict({'depuis': SINCE}, **wait)], sessions) if x.get('chantier')]
        return parc.pour_la_page({'genere': NOW, 'pastilles_lues': True, 'tableau': [l]})['lignes'][0]

    def screens(self, wait):
        lines = self.compute([dict({'depuis': SINCE}, **wait)])
        e = {'genere': NOW, 'pastilles_lues': True, 'tableau': lines, 'fils_rouges': [], 'sans_action': []}
        return parc.rendre_md(e)

    # The Q129 line of 2026-10-20: a go asked by the plugin's session, on the « Catalogue de l'org » subject.
    Q129 = {'type': 'go', 'titre': 'Q129 · Mon Studio : Je pousse sur main le correctif', 'ou': SUBJECT,
            'source': KIT, 'pilier': KIT, 'sessionId': KIT, 'sessionLabel': LABEL}

    def test_subject_alone_and_the_session_where_to_act_ends_the_text(self):
        l = self.line(self.Q129)
        self.assertEqual((l['session'], l['sujet'], l['sous']), (SUBJECT, SUBJECT, ''))
        self.assertEqual(l['agir_dans'], LABEL)
        self.assertEqual(l['affiche_suite'], 'Q129 · Mon Studio : Je pousse sur main le correctif')
        # The verb opens the session that asked, and copies its own number (it took it: sessionId).
        self.assertEqual((l['verbe'], l['ouvrir'], l['question']), ('Go', KIT, 'Q129'))
        self.assertEqual((l['source'], l['source_titre']), (KIT, LABEL))

    def test_unread_dot_stays_on_the_line(self):
        unread = {'id': KIT, 'cwd': '/studios/product-kits', 'titre': LABEL, 'non_lue': True, 'derniere': NOW,
                  'etat': 'travaille', 'depuis': NOW - 600, 'chemin': '/dev/null'}
        self.assertTrue(self.line(self.Q129, sessions=[unread])['non_lue'])

    def test_question_session_is_the_foreman(self):
        l = self.line(dict(self.Q129, sessionId=FOREMAN, sessionLabel='Foreman PM', source=FOREMAN, pilier=None))
        self.assertEqual((l['session'], l['agir_dans'], l['ouvrir'], l['source']), (SUBJECT, '', FOREMAN, ''))

    def test_session_from_the_lane_only_says_nothing(self):
        # Q101 of 2026-10-20: no session of its own on the board; « Voir la session » falls back on the lane's pillar.
        wait = {'type': 'task', 'titre': "Q101 · Vérifier dans l'app", 'ou': SUBJECT, 'source': KIT, 'pilier': KIT}
        l = self.line(wait)
        self.assertEqual((l['session'], l['agir_dans'], l['source']), (SUBJECT, '', KIT))

    def test_label_without_id_says_nothing(self):
        l = self.line(dict(self.Q129, sessionId=None))
        self.assertEqual(l['agir_dans'], '')

    def test_review_goes_to_its_session_and_says_it(self):
        # Q128 of 2026-10-20: « Relire » leads to the subject's session, without a second button, and the text says it.
        l = self.line(dict(self.Q129, type='review', titre='Q128 · Relire la charte'))
        self.assertEqual((l['session'], l['verbe'], l['ouvrir'], l['source']), (SUBJECT, 'Relire', KIT, KIT))
        self.assertEqual(l['agir_dans'], LABEL)

    def test_without_subject_the_session_stays(self):
        for ou in (None, '', 'Chantier'):
            with self.subTest(ou=ou):
                l = self.line(dict(self.Q129, ou=ou))
                self.assertEqual((l['session'], l['sujet'], l['sous'], l['nommee']), (LABEL, '', 'Chantier Product kits', KIT))
                self.assertEqual(l['agir_dans'], LABEL)  # the board says it too

    def test_line_outside_a_chantier_unchanged(self):
        stuck = {'id': ALONE, 'cwd': '/studios/Autre', 'titre': 'Seule', 'non_lue': True, 'derniere': NOW,
                 'etat': 'suspens', 'depuis': NOW - 600, 'outil': 'Bash'}
        lines = self.compute([dict({'depuis': SINCE}, **self.Q129)], sessions=[stuck])
        l, = [x for x in lines if x['cle'] == ALONE]
        for k in ('sujet', 'sous', 'nommee', 'agir_dans', 'source'):
            self.assertNotIn(k, l)
        self.assertEqual((l['session'], l['ouvrir'], l['non_lue']), ('Seule', ALONE, True))

    def test_markdown(self):
        md = self.screens(self.Q129)
        self.assertIn(f"| {SUBJECT} | Q129 · Mon Studio : Je pousse sur main le correctif | [Go](#{KIT}) |", md)
        self.assertNotIn('à traiter dans la session', md, 'agir_dans is never displayed')
        self.assertNotIn('Chantier Product kits', md)

    def test_markdown_review_verb_opens_its_session(self):
        md = self.screens(dict(self.Q129, type='review', titre='Q128 · Relire la charte'))
        self.assertIn(f'| {SUBJECT} | Q128 · Relire la charte | [Relire](#{KIT}) |', md)


class Outside(unittest.TestCase):
    """A line outside a chantier comes out exactly as before: same fields, same screens."""
    def test_same_page_fields_and_screens(self):
        stuck = {'id': ALONE, 'cwd': '/studios/Autre', 'titre': 'Seule', 'non_lue': True, 'derniere': NOW,
                 'etat': 'suspens', 'depuis': NOW - 600, 'outil': 'Bash'}
        with tempfile.TemporaryDirectory() as tmp:
            saved, parc.CHANTIERS = parc.CHANTIERS, pathlib.Path(tmp)
            try:
                lines = parc.tableau([stuck], CARDS, [], 7, NOW, {})
            finally:
                parc.CHANTIERS = saved
        e = {'genere': NOW, 'pastilles_lues': True, 'tableau': lines, 'fils_rouges': [], 'sans_action': []}
        l, = parc.pour_la_page(e)['lignes']
        self.assertEqual((l['session'], l['sous'], l['sujet'], l['agir_dans'], l['nommee']), ('Seule', None, None, None, None))
        self.assertIn(f'| Autre | [Seule](#{ALONE}) | Arrêtée en plein travail (commande du terminal)', parc.rendre_md(e))


if __name__ == '__main__':
    unittest.main()
