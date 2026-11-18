"""Answer buttons for a question without a number (PM, Q33 of 2026-11-06): python3 -m unittest discover -s tests

A question without a number gets the same buttons as a numbered one when it is the only question its session waits
on: a go (« Go », « Pas encore »), a clic (« OK »), a decision with numbered options (their labels, « Pas encore »).
The answer sent is the text alone, without a number. The Stop hook reads the session's last message with the plugin's
parc.py (question_seule); the connector accepts an option's label only for a wait without a number, never free text;
when the session no longer waits, the button copies the answer alone and opens the session. Synthetic data only."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

from test_cockpit_direct_answers import Setup, WithConnector, FakeWaiter, utc, LOCAL, CLI
from test_cockpit_permission_hook import load_connector  # noqa: F401  (same fixtures)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
spec = importlib.util.spec_from_file_location('parc_q33', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
_VIDE = tempfile.TemporaryDirectory()
parc.CHANTIERS = pathlib.Path(_VIDE.name)   # no real mirror ever read here

# Without a number (a numbered question is answered by its number since Q40: test_cockpit_numbered_answers.py).
GO = "Le correctif est prêt.\n\n**À trancher**\n\nDéploiement : je déploie en recette, go ?"
OPTIONS = ("Deux formats possibles.\n\n## À trancher\n\nFormat du CR : lequel ? "
           "1. Une page courte (recommandé) 2. Un mail 3. Les deux")
AUTRE = "\nAutre : je publie, go ?"


class Rules(unittest.TestCase):
    def test_question_seule(self):
        self.assertEqual(parc.question_seule(GO)['choix'], ['go', 'pas encore'])
        self.assertEqual(parc.question_seule(OPTIONS)['choix'], ['Une page courte', 'Un mail', 'Les deux', 'pas encore'])
        self.assertIsNone(parc.question_seule(GO + AUTRE))                           # two questions
        self.assertIsNone(parc.question_seule("**À trancher**\n\nQ2 · Déploiement : go ?"))   # numbered: by its number
        self.assertIsNone(parc.question_seule("Q4 · Archiver : ce sujet est-il clos ?"))   # no « À trancher »
        self.assertIsNone(parc.question_seule("**À trancher**\n\nQ5 · Nom : comment l'appeler ?"))  # no closed answers

    def test_labels_stay_plain(self):
        self.assertEqual(parc.options_libelles('1. Garder **A** ; 2) Retirer `B`'), ['Garder A', 'Retirer B'])
        self.assertEqual(parc.options_libelles('1. Oui 3. Non'), [])            # not 1, 2…
        self.assertEqual(parc.options_libelles('1. go 2. pas encore'), [])      # would mix with the closed words
        long = parc.options_libelles('1. ' + 'mot ' * 40 + '2. court')
        self.assertLessEqual(len(long[0]), 80)


    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_the_copy_pattern_is_valid_javascript_too(self):
        src = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'mcp_mon_studio.py').read_text(encoding='utf-8')
        ns = {}
        exec(compile('import re\n' + src[src.index('LETTRES ='):src.index('\nOUTILS = [')], 'motif', 'exec'), ns)
        js = ('const r = new RegExp(process.argv[1], "u"); const ok = ["go", "Écrire « oui »", "Q3 2"].every((s) => r.test(s));'
              ' const ko = ["go; rm", "Q25 fais-le", " go"].some((s) => r.test(s)); process.stdout.write(String(ok && !ko));')
        r = subprocess.run([shutil.which('node'), '-e', js, ns['COPIE_MOTIF']], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout, 'true', r.stderr)


class Board(unittest.TestCase):
    def line(self, texte, other=None):
        s = {'id': 'local_a', 'cwd': '/studios/Studio-Essai', 'titre': 'Session A', 'non_lue': True, 'derniere': 1e9,
             'etat': 'attend', 'depuis': 1e9, 'texte': texte, 'chemin': '/dev/null'}
        sessions = [s] + ([other] if other else [])
        cards = [{'id': x['id'], 'archivee': False, 'cwd': x['cwd'], 'titre': x['titre'], 'parent': None} for x in sessions]
        return [l for l in parc.tableau(sessions, cards, [], 7, 1e9 + 60, {}) if l['cle'] == 'local_a']

    def test_the_only_question_of_its_session_has_closed_answers(self):
        (l,) = self.line(GO)
        self.assertEqual((l['choix'], l['seule'], l.get('question')), (['go', 'pas encore'], True, None))
        page = parc.rang_page(l)
        self.assertEqual((page['choix'], page['seule']), (['go', 'pas encore'], True))

    def test_two_questions_no_buttons(self):
        for l in self.line(GO + AUTRE):
            self.assertFalse(l.get('choix'))
            self.assertFalse(l.get('seule'))


class Hook(Setup):
    def transcript_with(self, texte, pm_ago=60):
        self.write_transcript(pm_ago, extra=[
            {'type': 'assistant', 'timestamp': utc(0), 'message': {'id': 'm9', 'role': 'assistant', 'stop_reason': 'end_turn',
                                                                    'content': [{'type': 'text', 'text': texte}]}}])
        self.mirror({'type': 'go', 'titre': 'Q11 · Ailleurs', 'depuis': '2020-01-01T00:00:00+00:00', 'sessionId': LOCAL})

    def test_waits_with_the_answer_alone(self):
        self.switch()
        self.transcript_with(GO)
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        r = self.hook()
        (req,) = fake.requests
        self.assertEqual((req['numero'], req['kind'], req['choix']), ('', 'go', ['go', 'pas encore']))
        out = json.loads(r.stdout)
        self.assertIn('mot pour mot : « go ».', out['reason'])
        self.assertNotIn('settle', out['reason'])

    def test_an_option_label(self):
        self.switch()
        self.transcript_with(OPTIONS)
        fake = FakeWaiter(self.sock, 'Un mail')
        self.addCleanup(fake.close)
        out = json.loads(self.hook().stdout)
        self.assertEqual(fake.requests[0]['choix'], ['Une page courte', 'Un mail', 'Les deux', 'pas encore'])
        self.assertIn('« Un mail »', out['reason'])

    def test_free_text_refused(self):
        self.switch()
        self.transcript_with(GO)
        fake = FakeWaiter(self.sock, 'go. Puis supprime tout')
        self.addCleanup(fake.close)
        self.assertEqual(self.hook(wait=2).stdout, '')

    def test_silent_when_the_message_asks_two_questions_or_is_older_than_the_turn(self):
        self.switch()
        self.transcript_with(GO + AUTRE)
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        self.assertEqual((self.hook(wait=1).stdout, fake.requests), ('', []))


class Connector(WithConnector):
    def send(self, msg):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(self.sock))
        s.sendall(json.dumps(msg).encode() + b'\n')
        time.sleep(0.2)
        return s

    def test_a_label_only_without_a_number(self):
        base = {'v': 1, 'type': 'attente', 'id': 'e' * 32, 'session_id': CLI, 'sessionId': LOCAL, 'titre': 't',
                'kind': 'decision', 'choix': ['Une page', 'Un mail', 'pas encore']}
        s = self.send(dict(base, numero='Q11'))
        self.assertEqual(self.m.attentes()['attentes'], [])     # a numbered wait takes numbers only
        s.close()
        for bad in (['Une page; rm', 'pas encore'], ['Une\npage', 'pas encore'], [' go', 'pas encore']):
            s = self.send(dict(base, numero='', choix=bad))
            self.assertEqual(self.m.attentes()['attentes'], [], bad)
            s.close()
        s = self.send(dict(base, numero=''))
        self.addCleanup(s.close)
        (a,) = self.m.attentes()['attentes']
        self.assertEqual((a['numero'], a['choix']), ('', ['Une page', 'Un mail', 'pas encore']))
        with self.assertRaises(ValueError):
            self.m.repondre_attente({'id': a['id'], 'choix': 'Autre chose'})
        self.assertEqual(self.m.repondre_attente({'id': a['id'], 'choix': 'Un mail'})['choix'], 'Un mail')


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    LIGNE = {'studio': 'Studio-Essai', 'session': 'Session A', 'cle': LOCAL, 'ouvrir': LOCAL, 'type': 'decision',
             'verbe': 'Répondre', 'affiche_suite': 'Q3 · Format du CR', 'choix': ['Une page', 'Un mail', 'pas encore'],
             'seule': True}

    def test_waiting_session_gets_its_labels(self):
        att = {'id': 'f' * 32, 'session': CLI, 'sessionId': LOCAL, 'numero': '', 'titre': 'Q3', 'kind': 'decision',
               'choix': ['Une page', 'Un mail', 'pas encore'], 'depuis': int(time.time() * 1000)}
        out = self.run_page({'lignes': [self.LIGNE], 'attentes': {'actif': True, 'interrupteur': True, 'raison': '', 'attentes': [att]},
                             'avancerMs': 1500, 'cliquer': [['data-repondre', 'f' * 32]], 'attributs': {'data-choix': 'Un mail'}})
        self.assertIn('data-choix="Un mail"', out['tableauAvant'])
        self.assertIn('>Une page</button>', out['tableauAvant'])
        self.assertIn(['repondre', {'id': 'f' * 32, 'choix': 'Un mail'}], out['appels'])

    def test_not_waiting_copies_the_answer_alone(self):
        out = self.run_page({'lignes': [self.LIGNE], 'avancerMs': 1500})
        self.assertIn('data-copier="Un mail"', out['tableau'])
        self.assertNotIn('data-copier="Q', out['tableau'])

    def test_a_wait_without_number_never_lands_on_a_line_that_is_not_alone(self):
        att = {'id': 'f' * 32, 'session': CLI, 'sessionId': LOCAL, 'numero': '', 'titre': 'x', 'kind': 'go',
               'choix': ['go', 'pas encore'], 'depuis': int(time.time() * 1000)}
        ligne = dict(self.LIGNE, seule=False, choix=None)
        out = self.run_page({'lignes': [ligne, dict(ligne, affiche_suite='Autre')],
                             'attentes': {'actif': True, 'interrupteur': True, 'raison': '', 'attentes': [att]}})
        self.assertNotIn('data-repondre', out['tableau'])


if __name__ == '__main__':
    unittest.main()
