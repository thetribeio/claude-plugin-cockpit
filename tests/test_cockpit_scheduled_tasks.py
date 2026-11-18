"""Tests: a scheduled task whose last pass waits for the PM has its line on the board (PM, 2026-11-10).

python3 -m unittest discover -s tests

The app only shows a dot on « Tâches planifiées »: one had to open each task to find the one that waits. Mon Studio
reads the last pass of each task (automates) and puts one line on the board when it waits: a question (its options as
answer buttons), an authorization (pending, or refused and the turn cut), an error, or a cut turn. Nothing when it went
well; the line closes by itself when the next pass goes well."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc_taches', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
spec = importlib.util.spec_from_file_location('controle_taches', ROOT / 'scripts' / 'controle_lignes.py')
controle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controle)
# Noon of the previous day, not the real hour: a pass « 3 hours ago » must stay on the same day as NOW,
# or the tests fail between midnight and 3 a.m.
_hier = time.localtime(time.time() - 86400)
NOW = time.mktime((_hier.tm_year, _hier.tm_mon, _hier.tm_mday, 12, 0, 0, 0, 0, -1))
PASS = 'local_00000000-0000-0000-0000-0000000000a1'
OLD_PASS = 'local_00000000-0000-0000-0000-0000000000a0'


def at(hours_ago):
    return dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).isoformat()


def prompt(h, text='Lance le passage.'):
    return {'type': 'user', 'timestamp': at(h), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def tool(h, mid, name, inp):
    return {'type': 'assistant', 'timestamp': at(h),
            'message': {'id': mid, 'stop_reason': 'tool_use',
                        'content': [{'type': 'tool_use', 'id': 'u' + mid, 'name': name, 'input': inp}]}}


def result(h, mid, text='ok', error=False):
    return {'type': 'user', 'timestamp': at(h),
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'u' + mid, 'content': text, 'is_error': error}]}}


def refused(h, mid):
    return [result(h, mid, "The user doesn't want to proceed with this tool use. The tool use was rejected.", True),
            {'type': 'user', 'timestamp': at(h), 'origin': {'kind': 'human'},
             'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user for tool use]'}]}}]


def final(h, mid, text='Passage fait. Rien à faire de ton côté.'):
    return {'type': 'assistant', 'timestamp': at(h),
            'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def card(h, mid, ask, labels):
    inp = {'recap': 'Le passage est arrêté.', 'ask': ask, 'actions': [{'label': l, 'message': l} for l in labels]}
    return [tool(h, mid, parc.FIN_DE_TOUR, inp), result(h - 0.001, mid, 'Shown.')]


def error(h, text='API Error: 529 Overloaded\nretry later'):
    return {'type': 'assistant', 'timestamp': at(h), 'isApiErrorMessage': True,
            'message': {'id': 'err', 'model': '<synthetic>', 'content': [{'type': 'text', 'text': text}]}}


class Tasks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def automates(self, entries, name='Point du matin', title=None, older=None):
        """automates() on one task whose last pass is `entries` (and an older pass `older`, when given)."""
        index, metas = {}, []
        for sid, cli, ents, created in ((PASS, 'cli1', entries, NOW - 7200), (OLD_PASS, 'cli0', older, NOW - 90000)):
            if ents is None:
                continue
            path = self.root / f'{cli}.jsonl'
            path.write_text('\n'.join(json.dumps(e) for e in ents) + '\n', encoding='utf-8')
            os.utime(path, (NOW - 1800, NOW - 1800))   # written half an hour ago: not « Claude travaille »
            index[cli] = str(path)
            metas.append({'id': sid, 'cli': cli, 'cwd': '/studios/Essai', 'titre': title or name, 'archivee': False,
                          'tache': 't1', 'creee': created, 'parent': None, 'activite': created, 'focus': 0})
        task = {'id': 't1', 'displayName': name, 'enabled': True,
                'lastRunAt': dt.datetime.fromtimestamp(NOW - 7200, dt.timezone.utc).isoformat().replace('+00:00', 'Z')}
        cache = {'transcripts': {}}
        autos = parc.automates([task], metas, index, cache, NOW)
        return autos, metas

    def lines(self, entries, **kw):
        autos, metas = self.automates(entries, **kw)
        old = parc.CHANTIERS
        parc.CHANTIERS = self.root / 'chantiers'
        try:
            fresh, aged = parc.lignes_et_anciennes([], metas, autos, 7, NOW, None)
        finally:
            parc.CHANTIERS = old
        return [l for l in fresh + aged if l.get('tache')], autos

    def test_a_refused_authorization_names_the_task_and_the_tool(self):
        # measured on 2026-11-10: the pass waited on Bash, then « [Request interrupted by user for tool use] »
        lines, autos = self.lines([prompt(3), tool(2.9, 'a', 'Bash', {'command': 'python3 matin.py preparer'}),
                                   *refused(1, 'a')])
        self.assertEqual(autos[0]['arret']['quoi'], 'refused')
        self.assertEqual(len(lines), 1)
        l = lines[0]
        self.assertEqual((l['studio'], l['session'], l['suite']), ('Essai', 'Point du matin', 'Arrêtée sur une autorisation (commande du terminal)'))
        self.assertEqual((l['ouvrir'], l['verbe'], l['tache']), (PASS, 'Ouvrir', 'Point du matin'))
        self.assertIn('python3 matin.py preparer', l['detail'])
        self.assertNotIn('choix', l)

    def test_the_task_name_leads_when_the_session_says_something_else(self):
        lines, _ = self.lines([prompt(3), tool(2.9, 'a', 'Bash', {'command': 'ls'}), *refused(1, 'a')],
                              name='Ingestion auto', title='Rattrapage des conflits')
        self.assertEqual(lines[0]['suite'], 'Ingestion auto : arrêtée sur une autorisation (commande du terminal)')
        self.assertEqual(lines[0]['session'], 'Rattrapage des conflits')

    def test_a_pending_authorization_can_go_to_one_click(self):
        lines, _ = self.lines([prompt(3), tool(2.9, 'a', 'Bash', {'command': 'git push'})])
        l = lines[0]
        self.assertEqual((l['arret'], l['bloque'], l['extrait']), ('authorization', True, 'commande du terminal · git push'))
        self.assertEqual(l['suite'], 'Arrêtée sur une autorisation (commande du terminal)')

    def test_an_error_gives_its_reason_in_a_few_words(self):
        lines, _ = self.lines([prompt(3), error(2)])
        self.assertEqual(lines[0]['suite'], 'Arrêtée sur une erreur : API Error: 529 Overloaded')
        self.assertEqual(lines[0]['arret'], 'error')

    def test_a_card_question_gets_its_options_as_buttons(self):
        lines, _ = self.lines([prompt(3), *card(2, 'a', 'Relancer le passage maintenant ?', ['Oui, relance', 'Plus tard']),
                               final(1.9, 'b', "Le passage s'est arrêté.")])
        l = lines[0]
        self.assertEqual(l['titre'], 'Relancer le passage maintenant ?')
        self.assertEqual((l['choix'], l['seule'], l['question']), (['Oui, relance', 'Plus tard'], True, ''))

    def test_options_the_connector_would_refuse_give_no_buttons(self):
        for labels in (['Oui', 'Oui'], ['Q2 go', 'Plus tard'], ['x' * 90, 'Plus tard'], []):
            lines, _ = self.lines([prompt(3), *card(2, 'a', 'Relancer ?', labels), final(1.9, 'b', 'Arrêté.')])
            self.assertEqual(len(lines), 1, labels)
            self.assertNotIn('choix', lines[0], labels)

    def test_a_pass_that_went_well_has_no_line(self):
        lines, autos = self.lines([prompt(3), final(2, 'a')])
        self.assertEqual(lines, [])
        self.assertTrue(autos[0]['ok'])

    def test_the_pm_writing_last_is_no_failure(self):
        # « main »: the PM wrote in the pass and nothing refused a tool; it used to read « Dernier passage en échec »
        lines, autos = self.lines([prompt(3), final(2.5, 'a'), prompt(2, 'Merci, je regarde.')])
        self.assertEqual(lines, [])
        self.assertIsNone(autos[0]['ok'])

    def test_the_next_pass_that_goes_well_closes_the_line(self):
        lines, _ = self.lines([prompt(3), final(2, 'a')],
                              older=[prompt(27), tool(26.9, 'a', 'Bash', {'command': 'ls'}), *refused(25, 'a')])
        self.assertEqual(lines, [])

    def test_a_pass_a_chantier_asks_about_has_no_second_line(self):
        autos, metas = self.automates([prompt(3), error(2)])
        self.assertEqual(parc.ligne_de_tache(autos[0], {}, {}, {PASS}, 7, NOW), [])
        self.assertEqual(len(parc.ligne_de_tache(autos[0], {}, {}, set(), 7, NOW)), 1)


class Control(unittest.TestCase):
    AUTOS = [{'nom': 'Point du matin', 'lien': PASS, 'carte': None, 'arret': {'quoi': 'refused', 'outil': 'Bash'}},
             {'nom': 'Kit', 'lien': OLD_PASS, 'arret': None,
              'carte': {'menu': [{'question': 'Relancer ?', 'options': [{'label': 'Oui'}, {'label': 'Plus tard'}]}]}},
             {'nom': 'Ingestion', 'lien': 'local_00000000-0000-0000-0000-0000000000b0', 'carte': None, 'arret': None}]
    GOOD = [{'tache': 'Point du matin', 'ouvrir': PASS, 'affiche_suite': 'Arrêtée sur une autorisation (commande du terminal)'},
            {'tache': 'Kit', 'ouvrir': OLD_PASS, 'choix': ['Oui', 'Plus tard'], 'seule': True, 'question': '',
             'affiche_suite': 'Oui · Plus tard'}]

    def test_good_lines_pass(self):
        self.assertEqual(controle.taches(self.AUTOS, self.GOOD, set()), [])

    def test_a_waiting_pass_without_line_is_reported_unless_a_chantier_asks(self):
        self.assertIn('aucune ligne', controle.taches(self.AUTOS, self.GOOD[1:], set())[0][2])
        self.assertEqual(controle.taches(self.AUTOS, self.GOOD[1:], {PASS}), [])

    def test_a_line_for_a_pass_that_went_well_or_an_older_pass_is_reported(self):
        well = dict(self.GOOD[0], tache='Ingestion', ouvrir='local_00000000-0000-0000-0000-0000000000b0')
        self.assertIn('aurait dû se fermer', controle.taches(self.AUTOS, self.GOOD + [well], set())[0][2])
        older = dict(self.GOOD[0], ouvrir='local_00000000-0000-0000-0000-0000000000ff')
        self.assertIn("n'est pas le dernier", controle.taches(self.AUTOS, self.GOOD + [older], set())[0][2])

    def test_two_lines_a_wrong_name_or_foreign_buttons_are_reported(self):
        self.assertIn('2 lignes', controle.taches(self.AUTOS, self.GOOD + [self.GOOD[0]], set())[0][2])
        named = [dict(self.GOOD[0], tache='Autre'), self.GOOD[1]]
        self.assertIn('ne nomme pas', controle.taches(self.AUTOS, named, set())[0][2])
        foreign = [self.GOOD[0], dict(self.GOOD[1], choix=['go', 'pas encore'])]
        self.assertIn('hors des options', controle.taches(self.AUTOS, foreign, set())[0][2])


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(ROOT / 'tests' / 'tester-epinglee.js'),
                                str(ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'), str(data)],
                               capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def row(self, **more):
        return dict({'studio': 'Essai', 'session': 'Point du matin', 'cle': PASS, 'ouvrir': PASS, 'type': 'task',
                     'verbe': 'Ouvrir', 'tache': 'Point du matin', 'depuis': int(NOW * 1000)}, **more)

    def test_an_authorization_the_page_cannot_give_keeps_the_task_text(self):
        out = self.run_page({'lignes': [self.row(arret='authorization', bloque=True, extrait='commande du terminal · ls',
                                                 affiche_suite='Arrêtée sur une autorisation (commande du terminal)')],
                             'autorisations': {'actif': False, 'demandes': [], 'decisions': []}})
        self.assertIn('Arrêtée sur une autorisation (commande du terminal)', out['tableau'])
        self.assertNotIn('à rouvrir', out['tableau'])
        self.assertIn('Ouvrir ↗', out['tableau'])

    def test_a_question_shows_its_options_as_buttons(self):
        out = self.run_page({'lignes': [self.row(type='decision', verbe='Répondre', affiche_titre='Relancer ?',
                                                 affiche_suite='Oui, relance · Plus tard', choix=['Oui, relance', 'Plus tard'],
                                                 seule=True, question='')]})
        self.assertIn('>Oui, relance</button>', out['tableau'])
        self.assertIn('>Plus tard</button>', out['tableau'])


if __name__ == '__main__':
    unittest.main()
