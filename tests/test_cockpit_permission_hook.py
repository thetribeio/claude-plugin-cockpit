"""Tests: allow or deny an authorization from the pinned page (Q40, Q44): python3 -m unittest discover -s tests

The PermissionRequest hook (hooks/autorisation.py) is off by default. Switched on (cockpit.json,
`autorisations_tableau: true`, optionally restricted to `autorisations_sessions`), it hands the request to every
instance of the local connector, each over its own Unix socket (~/Mon Studio/.parc/autorisations-<pid>.sock, folder
700, socket 600: the desktop app starts one instance per client), and waits on all the connections at once; the first
valid answer wins and the others are closed. The connector keeps requests in memory, at most 30 minutes; the page lists them with the MCP tool
`autorisations` and answers with `decider`, on the PM's click. Allow is for this request only (no permanent rule, no
`updatedPermissions`); deny comes with a short message. Socket missing, no answer in time, unknown or expired request:
the hook says nothing and the app's normal window stays. Nothing about a request is ever written to disk, only the
decision journal.

Mon Studio folders, cards and transcripts are synthetic; the real app is never run. A short temporary folder holds the
socket (a Unix socket path is limited to about a hundred characters)."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from test_cockpit_authorizations import Fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks' / 'autorisation.py'
CONNECTOR = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'mcp_mon_studio.py'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
SHORT_TMP = '/tmp' if os.path.isdir('/tmp') else None
CLI, LOCAL = 'cli-kit-a', 'local_00000000-0000-0000-0000-00000000000a'
REQUEST = {'session_id': CLI, 'transcript_path': '/x.jsonl', 'cwd': '/studios/Studio-Essai', 'permission_mode': 'default',
           'hook_event_name': 'PermissionRequest', 'tool_name': 'Bash',
           'tool_input': {'command': 'git push origin feat/x', 'description': 'Push'},
           'permission_suggestions': [{'type': 'addRules', 'rules': [{'toolName': 'Bash', 'ruleContent': 'git push:*'}],
                                       'behavior': 'allow', 'destination': 'localSettings'}]}


@unittest.skipIf(os.name == 'nt' or not hasattr(socket, 'AF_UNIX'), 'pas de socket Unix')
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SHORT_TMP)
        self.root = pathlib.Path(self.tmp.name)
        self.mon_studio = self.root / 'MS'
        self.parc_dir = self.mon_studio / '.parc'
        self.parc_dir.mkdir(parents=True)
        self.sock = self.parc_dir / f'autorisations-{os.getpid()}.sock'

    def tearDown(self):
        self.tmp.cleanup()

    def switch(self, on=True, sessions=None):
        state = {'version': '0.1.0'}
        if on is not None:
            state['autorisations_tableau'] = on
        if sessions is not None:
            state['autorisations_sessions'] = sessions
        (self.parc_dir / 'cockpit.json').write_text(json.dumps(state))

    def env(self, wait=None, **more):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('MON_STUDIO', 'CLAUDE_CODE_HOST'))}
        env['MON_STUDIO'] = str(self.mon_studio)
        if wait is not None:
            env['MON_STUDIO_AUTORISATION_ATTENTE'] = str(wait)
        env.update(more)
        return env

    def hook(self, request=REQUEST, wait=5, **env):
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(request), capture_output=True, text=True,
                              env=self.env(wait, **env), timeout=60)

    def files(self):
        return sorted(str(p.relative_to(self.mon_studio)) for p in self.mon_studio.rglob('*'))


class FakeConnector:
    """A socket that answers each request as told: 'allow', 'deny', 'other-id', 'garbage' or None (never answers)."""

    def __init__(self, path, answer):
        self.answer, self.requests = answer, []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(4)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            conn, _ = self.server.accept()
        except OSError:
            return
        with conn:
            data = b''
            while b'\n' not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            req = json.loads(data.split(b'\n')[0])
            self.requests.append(req)
            if self.answer is None:
                time.sleep(3)
                return
            if self.answer == 'garbage':
                conn.sendall(b'{not json\n')
            elif self.answer == 'other-id':
                conn.sendall(json.dumps({'id': '0' * 32, 'decision': 'allow'}).encode() + b'\n')
            else:
                conn.sendall(json.dumps({'id': req['id'], 'decision': self.answer}).encode() + b'\n')

    def close(self):
        self.server.close()


class HookAlone(Base):
    def test_no_mon_studio_no_switch_no_output(self):
        r = self.hook()
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.switch(on=None)
        fake = FakeConnector(self.sock, 'allow')
        self.addCleanup(fake.close)
        self.assertEqual((self.hook().returncode, self.hook().stdout), (0, ''))
        self.switch(on=False)
        self.assertEqual(self.hook().stdout, '')
        self.assertEqual(fake.requests, [])   # never even connected

    def test_silent_outside_the_trial_sessions(self):
        self.switch(sessions=['cli-other', 'local_other'])
        fake = FakeConnector(self.sock, 'allow')
        self.addCleanup(fake.close)
        self.assertEqual(self.hook().stdout, '')
        self.assertEqual(fake.requests, [])

    def test_a_trial_session_by_its_app_id_is_concerned(self):
        self.switch(sessions=[LOCAL])
        fake = FakeConnector(self.sock, 'allow')
        self.addCleanup(fake.close)
        out = json.loads(self.hook(CLAUDE_CODE_HOST_SESSION_ID=LOCAL).stdout)
        self.assertEqual(out['hookSpecificOutput']['decision']['behavior'], 'allow')

    def test_socket_missing_leaves_the_normal_window(self):
        self.switch()
        r = self.hook()
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_no_answer_in_time_leaves_the_normal_window(self):
        self.switch()
        fake = FakeConnector(self.sock, None)
        self.addCleanup(fake.close)
        start = time.monotonic()
        r = self.hook(wait=1)
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertLess(time.monotonic() - start, 30)
        self.assertEqual(len(fake.requests), 1)

    def test_allow_is_for_this_request_only(self):
        self.switch()
        fake = FakeConnector(self.sock, 'allow')
        self.addCleanup(fake.close)
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'hookSpecificOutput': {'hookEventName': 'PermissionRequest',
                                                                       'decision': {'behavior': 'allow'}}})
        self.assertNotIn('updatedPermissions', r.stdout)
        self.assertNotIn('updatedInput', r.stdout)
        (req,) = fake.requests
        self.assertRegex(req['id'], r'^[0-9a-f]{32}$')
        self.assertEqual((req['session_id'], req['cwd'], req['tool_name']), (CLI, '/studios/Studio-Essai', 'Bash'))
        self.assertEqual(req['extrait'], 'Bash · git push origin feat/x')
        self.assertTrue(req['heure'])

    def test_deny_comes_with_a_short_message(self):
        self.switch()
        fake = FakeConnector(self.sock, 'deny')
        self.addCleanup(fake.close)
        d = json.loads(self.hook().stdout)['hookSpecificOutput']['decision']
        self.assertEqual(d['behavior'], 'deny')
        self.assertTrue(0 < len(d['message']) < 80)
        self.assertNotIn('interrupt', d)

    def test_an_unreadable_or_foreign_answer_leaves_the_normal_window(self):
        for answer in ('garbage', 'other-id'):
            self.switch()
            fake = FakeConnector(self.sock, answer)
            self.assertEqual(self.hook().stdout, '', answer)
            fake.close()
            self.sock.unlink()

    def test_the_extract_is_cut_at_300_characters(self):
        self.switch()
        fake = FakeConnector(self.sock, 'deny')
        self.addCleanup(fake.close)
        self.hook(dict(REQUEST, tool_input={'command': 'echo ' + 'x' * 1000}))
        self.assertLessEqual(len(fake.requests[0]['extrait']), 300)

    def test_nothing_is_written_to_disk(self):
        self.switch()
        fake = FakeConnector(self.sock, 'allow')
        self.addCleanup(fake.close)
        before = self.files()
        self.hook()
        self.assertEqual(self.files(), before)

    def test_the_same_request_goes_to_every_socket_and_a_valid_answer_wins(self):
        self.switch()
        silent = FakeConnector(self.parc_dir / 'autorisations-1.sock', 'garbage')
        fake = FakeConnector(self.sock, 'deny')
        self.addCleanup(silent.close)
        self.addCleanup(fake.close)
        out = json.loads(self.hook().stdout)
        self.assertEqual(out['hookSpecificOutput']['decision']['behavior'], 'deny')
        (a,), (b,) = silent.requests, fake.requests
        self.assertEqual(a, b)

    def test_a_dead_socket_is_skipped(self):
        self.switch()
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(str(self.parc_dir / 'autorisations-2.sock'))
        dead.close()   # the file stays, nothing listens
        fake = FakeConnector(self.sock, 'allow')
        self.addCleanup(fake.close)
        self.assertEqual(json.loads(self.hook().stdout)['hookSpecificOutput']['decision']['behavior'], 'allow')

    def test_only_dead_sockets_leave_the_normal_window_at_once(self):
        self.switch()
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(str(self.sock))
        dead.close()
        start = time.monotonic()
        r = self.hook(wait=20)
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertLess(time.monotonic() - start, 10)

    def test_the_old_single_socket_is_not_used(self):
        self.switch()
        old = FakeConnector(self.parc_dir / 'autorisations.sock', 'allow')
        self.addCleanup(old.close)
        self.assertEqual(self.hook().stdout, '')
        self.assertEqual(old.requests, [])


def load_connector(mon_studio, app, transcripts):
    old = os.environ.get('MON_STUDIO')
    os.environ['MON_STUDIO'] = str(mon_studio)
    try:
        spec = importlib.util.spec_from_file_location('mcp_mon_studio_essai', CONNECTOR)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        if old is None:
            os.environ.pop('MON_STUDIO', None)
        else:
            os.environ['MON_STUDIO'] = old
    m.parc.APP, m.parc.TRANSCRIPTS = app, transcripts
    return m


class ConnectorSetup(Base):
    def setUp(self):
        super().setUp()
        self.app = self.root / 'app'
        (self.app / 'acct' / 'org').mkdir(parents=True)
        (self.app / 'acct' / 'org' / f'{LOCAL}.json').write_text(json.dumps(
            {'sessionId': LOCAL, 'cliSessionId': CLI, 'title': 'Kit A · déploiement', 'cwd': '/studios/Studio-Essai'}))
        self.transcripts = self.root / 'transcripts'
        (self.transcripts / 'proj').mkdir(parents=True)
        self.transcript = self.transcripts / 'proj' / f'{CLI}.jsonl'
        self.transcript.write_text('{}\n')
        os.utime(self.transcript, (time.time() - 600, time.time() - 600))
        self.m = load_connector(self.mon_studio, self.app, self.transcripts)
        self.switch()
        self.assertTrue(self.m.AUTORISATIONS.demarrer(), self.m.AUTORISATIONS.raison)
        self.addCleanup(self.m.AUTORISATIONS.arreter)

    def start_hook(self, request=REQUEST, wait=20):
        p = subprocess.Popen([sys.executable, str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=self.env(wait))
        p.stdin.write(json.dumps(request))
        p.stdin.close()
        def done():
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
            p.stderr.close()
        self.addCleanup(done)
        return p

    def finish(self, p):
        p.wait(timeout=30)
        return p.stdout.read()

    def pending(self, n=1):
        for _ in range(200):
            d = self.m.autorisations()
            if len(d['demandes']) >= n:
                return d
            time.sleep(0.05)
        self.fail('aucune demande reçue')


class Connector(ConnectorSetup):
    def test_socket_and_folder_rights(self):
        self.assertEqual(stat.S_IMODE(self.sock.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.parc_dir.stat().st_mode), 0o700)
        self.assertTrue(stat.S_ISSOCK(self.sock.stat().st_mode))

    def test_a_request_is_listed_then_allowed_and_journaled(self):
        p = self.start_hook()
        d = self.pending()
        self.assertTrue(d['actif'])
        (r,) = d['demandes']
        self.assertEqual((r['session'], r['sessionId'], r['titre'], r['outil'], r['extrait']),
                         (CLI, LOCAL, 'Kit A · déploiement', 'commande du terminal', 'commande du terminal · git push origin feat/x'))
        self.assertIsInstance(r['depuis'], int)
        self.assertEqual(self.m.decider({'id': r['id'], 'decision': 'allow'}),
                         {'id': r['id'], 'decision': 'allow', 'envoye': True})
        out = self.finish(p)
        self.assertEqual(json.loads(out)['hookSpecificOutput']['decision'], {'behavior': 'allow'})
        (line,) = (self.parc_dir / 'autorisations.log').read_text().splitlines()
        j = json.loads(line)
        self.assertEqual((j['decision'], j['outil'], j['extrait'], j['session']),
                         ('allow', 'Bash', 'Bash · git push origin feat/x', CLI))   # the log keeps the raw name
        self.assertTrue(j['date'])
        after = self.m.autorisations()
        self.assertEqual(after['demandes'], [])
        self.assertEqual(after['decisions'][0]['decision'], 'allow')

    def test_deny_reaches_the_hook(self):
        p = self.start_hook()
        (r,) = self.pending()['demandes']
        self.m.decider({'id': r['id'], 'decision': 'deny'})
        out = self.finish(p)
        self.assertEqual(json.loads(out)['hookSpecificOutput']['decision']['behavior'], 'deny')

    def test_an_expired_request_is_refused_and_the_window_stays(self):
        self.m.LIMITE_S = 0.5
        p = self.start_hook()
        (r,) = self.pending()['demandes']
        time.sleep(1.2)
        with self.assertRaisesRegex(ValueError, 'inconnue ou expirée'):
            self.m.decider({'id': r['id'], 'decision': 'allow'})
        out = self.finish(p)
        self.assertEqual(out, '')
        self.assertFalse((self.parc_dir / 'autorisations.log').exists())

    def test_unknown_request_and_bad_decision_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'inconnue ou expirée'):
            self.m.decider({'id': 'a' * 32, 'decision': 'allow'})
        with self.assertRaisesRegex(ValueError, 'allow ou deny'):
            self.m.decider({'id': 'a' * 32, 'decision': 'always'})

    def test_switched_off_nothing_is_shown_nor_decided(self):
        p = self.start_hook()
        self.pending()
        self.switch(on=False)
        d = self.m.autorisations()
        self.assertEqual((d['actif'], d['demandes'], d['decisions']), (False, [], []))
        with self.assertRaisesRegex(ValueError, 'coupées'):
            self.m.decider({'id': 'a' * 32, 'decision': 'allow'})
        p.kill()

    def test_a_request_answered_in_the_app_leaves_the_list(self):
        p = self.start_hook()
        self.pending()
        os.utime(self.transcript, (time.time() + 60, time.time() + 60))   # the session moved on: answered elsewhere
        self.assertEqual(self.m.autorisations()['demandes'], [])
        out = self.finish(p)
        self.assertEqual(out, '')

    def test_a_restarted_connector_leaves_the_normal_window(self):
        p = self.start_hook()
        self.pending()
        self.m.AUTORISATIONS.arreter()
        out = self.finish(p)
        self.assertEqual(out, '')

    def test_no_request_nor_nonce_on_disk(self):
        p = self.start_hook()
        (r,) = self.pending()['demandes']
        self.m.decider({'id': r['id'], 'decision': 'allow'})
        self.finish(p)
        self.assertEqual(sorted(x for x in self.files() if x.startswith('.parc')),
                         sorted(['.parc', '.parc/autorisations.log', f'.parc/{self.sock.name}', '.parc/cockpit.json']))
        for f in self.mon_studio.rglob('*'):
            if f.is_file():
                self.assertNotIn(r['id'], f.read_text(errors='replace'), f)

    def test_stopping_removes_its_own_socket(self):
        self.m.AUTORISATIONS.arreter()
        self.assertFalse(self.sock.exists())
        d = self.m.autorisations()
        self.assertFalse(d['actif'])
        self.assertTrue(d['raison'])

    def test_switched_off_says_why(self):
        self.switch(on=False)
        d = self.m.autorisations()
        self.assertEqual((d['actif'], d['interrupteur']), (False, False))
        self.assertIn('interrupteur', d['raison'])
        self.switch()
        self.assertEqual((self.m.autorisations()['actif'], self.m.autorisations()['raison']), (True, ''))

    def test_the_tools_are_declared_and_decider_is_not_read_only(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.traiter({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            self.m.traiter({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                            'params': {'name': 'decider', 'arguments': {'id': 'b' * 32, 'decision': 'deny'}}})
        listed, called = [json.loads(l) for l in buf.getvalue().splitlines()]
        tools = {t['name']: t for t in listed['result']['tools']}
        self.assertEqual(sorted(tools), ['attentes', 'autorisations', 'clore', 'conflits_juger', 'decider', 'gabarit', 'lignes', 'lire', 'matin_ecrire', 'ouvrir', 'projet', 'repondre', 'slack_juger', 'slack_ouvertes'])
        self.assertIs(tools['decider']['annotations']['readOnlyHint'], False)
        self.assertIs(tools['lire']['annotations']['readOnlyHint'], True)   # « Lire » writes nothing
        self.assertIs(tools['autorisations']['annotations']['readOnlyHint'], True)
        self.assertIs(tools['projet']['annotations']['readOnlyHint'], True)   # the project view writes nothing
        self.assertTrue(called['result']['isError'])
        self.assertIn('inconnue ou expirée', called['result']['content'][0]['text'])


def dead_pid():
    p = subprocess.Popen([sys.executable, '-c', ''])
    p.wait()
    return p.pid


def dead_socket(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.close()   # the file stays, nothing listens


class TwoConnectors(ConnectorSetup):
    """The desktop app starts two instances of the connector, one per client: each holds its own socket."""

    def setUp(self):
        super().setUp()
        self.m2 = load_connector(self.mon_studio, self.app, self.transcripts)
        # Same test process: the second instance takes another live pid for its socket name.
        self.sock2 = self.parc_dir / f'autorisations-{os.getppid()}.sock'
        self.m2.AUTORISATIONS = self.m2.Autorisations(self.sock2)
        self.assertTrue(self.m2.AUTORISATIONS.demarrer(), self.m2.AUTORISATIONS.raison)
        self.addCleanup(self.m2.AUTORISATIONS.arreter)

    def pending_in(self, m, n=1):
        for _ in range(200):
            d = m.autorisations()
            if len(d['demandes']) >= n:
                return d
            time.sleep(0.05)
        self.fail('aucune demande reçue')

    def test_each_holds_its_own_socket_in_600(self):
        self.assertNotEqual(self.sock, self.sock2)
        for path in (self.sock, self.sock2):
            self.assertTrue(stat.S_ISSOCK(path.stat().st_mode), path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.parc_dir.stat().st_mode), 0o700)
        for m in (self.m, self.m2):
            d = m.autorisations()
            self.assertEqual((d['actif'], d['raison']), (True, ''))

    def test_the_hook_reaches_both_and_decider_on_the_second_frees_it(self):
        p = self.start_hook()
        (r1,) = self.pending_in(self.m)['demandes']
        (r2,) = self.pending_in(self.m2)['demandes']
        same = lambda r: {k: v for k, v in r.items() if k != 'depuis'}   # each instance dates its own receipt
        self.assertEqual(same(r1), same(r2))
        self.m2.decider({'id': r2['id'], 'decision': 'allow'})
        out = self.finish(p)
        self.assertEqual(json.loads(out), {'hookSpecificOutput': {'hookEventName': 'PermissionRequest',
                                                                  'decision': {'behavior': 'allow'}}})
        for _ in range(100):   # the hook closed the first connection: the request leaves the first instance
            if not self.m.autorisations()['demandes']:
                break
            time.sleep(0.05)
        self.assertEqual(self.m.autorisations()['demandes'], [])
        self.assertEqual(self.m2.autorisations()['demandes'], [])
        (line,) = (self.parc_dir / 'autorisations.log').read_text().splitlines()
        self.assertEqual(json.loads(line)['decision'], 'allow')
        with self.assertRaisesRegex(ValueError, 'inconnue ou expirée'):
            self.m.decider({'id': r1['id'], 'decision': 'deny'})

    def test_deny_on_the_first_frees_it_too(self):
        p = self.start_hook()
        self.pending_in(self.m2)
        (r,) = self.pending_in(self.m)['demandes']
        self.m.decider({'id': r['id'], 'decision': 'deny'})
        self.assertEqual(json.loads(self.finish(p))['hookSpecificOutput']['decision']['behavior'], 'deny')

    def test_one_instance_stopping_leaves_the_other_able_to_decide(self):
        p = self.start_hook()
        self.pending_in(self.m)
        (r,) = self.pending_in(self.m2)['demandes']
        self.m.AUTORISATIONS.arreter()
        self.assertFalse(self.sock.exists())
        time.sleep(0.3)
        self.assertIsNone(p.poll())   # still waiting on the second
        self.m2.decider({'id': r['id'], 'decision': 'allow'})
        self.assertEqual(json.loads(self.finish(p))['hookSpecificOutput']['decision']['behavior'], 'allow')

    def test_a_dead_socket_is_cleaned_at_start_and_a_live_one_kept(self):
        gone = self.parc_dir / f'autorisations-{dead_pid()}.sock'
        refused = self.parc_dir / 'autorisations-1.sock'    # pid 1 lives, but nothing listens
        dead_socket(gone)
        dead_socket(refused)
        dead_socket(self.parc_dir / 'autorisations.sock')   # the old single socket, dead
        m3 = load_connector(self.mon_studio, self.app, self.transcripts)
        sock3 = self.parc_dir / f'autorisations-{os.getpid() + 100000}.sock'
        m3.AUTORISATIONS = m3.Autorisations(sock3)
        self.assertTrue(m3.AUTORISATIONS.demarrer(), m3.AUTORISATIONS.raison)
        self.addCleanup(m3.AUTORISATIONS.arreter)
        names = sorted(x.name for x in self.parc_dir.glob('autorisations*.sock'))
        self.assertEqual(names, sorted([self.sock.name, self.sock2.name, sock3.name]))

    def test_the_old_single_socket_is_kept_while_alive(self):
        old = FakeConnector(self.parc_dir / 'autorisations.sock', None)
        self.addCleanup(old.close)
        self.m.AUTORISATIONS.arreter()
        self.m.AUTORISATIONS = self.m.Autorisations(self.sock)
        self.assertTrue(self.m.AUTORISATIONS.demarrer())
        self.assertTrue((self.parc_dir / 'autorisations.sock').exists())

    def test_the_hook_ignores_a_dead_socket_left_behind(self):
        dead_socket(self.parc_dir / f'autorisations-{dead_pid()}.sock')
        p = self.start_hook()
        (r,) = self.pending_in(self.m2)['demandes']
        self.m2.decider({'id': r['id'], 'decision': 'allow'})
        self.assertEqual(json.loads(self.finish(p))['hookSpecificOutput']['decision']['behavior'], 'allow')

    def test_no_request_file_with_two_instances(self):
        p = self.start_hook()
        self.pending_in(self.m)
        (r,) = self.pending_in(self.m2)['demandes']
        self.m2.decider({'id': r['id'], 'decision': 'allow'})
        self.finish(p)
        self.assertEqual(sorted(x for x in self.files() if x.startswith('.parc')),
                         sorted(['.parc', '.parc/autorisations.log', '.parc/cockpit.json',
                                 f'.parc/{self.sock.name}', f'.parc/{self.sock2.name}']))
        for f in self.mon_studio.rglob('*'):
            if f.is_file():
                self.assertNotIn(r['id'], f.read_text(errors='replace'), f)


class NoUnixSocket(Base):
    def test_windows_does_nothing(self):
        m = load_connector(self.mon_studio, self.root / 'app', self.root / 'transcripts')
        m.POSSIBLE = False
        self.switch()
        self.assertFalse(m.AUTORISATIONS.demarrer())
        self.assertFalse(self.sock.exists())
        self.assertFalse(m.autorisations()['actif'])


@unittest.skipUnless(shutil.which('node'), 'node absent : la page épinglée n\'est pas essayée')
class PageButtons(Fixture):
    def run_page(self, payload):
        data = pathlib.Path(self.tmp.name) / 'payload.json'
        data.write_text(json.dumps(payload, ensure_ascii=False))
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def payload(self, actif=True, **more):
        demandes = [{'id': 'c' * 32, 'session': 'cli-local_bash', 'sessionId': 'local_bash', 'titre': 'Kit A · déploiement',
                     'outil': 'Bash', 'extrait': 'commande du terminal · git push origin feat/x', 'depuis': int(time.time() * 1000)},
                    {'id': 'd' * 32, 'session': 'cli-new', 'sessionId': None, 'titre': 'Kit Z · nouvelle',
                     'outil': 'Write', 'extrait': 'Write · /tmp/essai/z.md', 'depuis': int(time.time() * 1000)}]
        decisions = [{'date': '2026-10-29T10:00:00+01:00', 'decision': 'deny', 'outil': 'Bash', 'extrait': 'commande du terminal · rm -rf x',
                      'session': 'cli-x', 'titre': 'Kit Y'}]
        from test_cockpit_authorizations import parc
        return dict({'lignes': parc.pour_la_page(self.e)['lignes'],
                     'autorisations': {'actif': actif, 'demandes': demandes if actif else [], 'decisions': decisions if actif else []}},
                    **more)

    def test_a_line_with_its_request_has_the_two_buttons(self):
        out = self.run_page(self.payload())
        self.assertIn('autorisations', out['veilles'])
        self.assertIn('data-decider="' + 'c' * 32 + '" data-decision="allow"', out['bloc'])
        self.assertIn('Autoriser cette fois', out['bloc'])
        self.assertIn('Refuser', out['bloc'])
        self.assertIn('Kit Z · nouvelle', out['bloc'])            # a request without a line has its own row
        self.assertIn('data-decider="' + 'd' * 32 + '"', out['bloc'])
        self.assertEqual(out['blocTitre'], 'En un clic (2)')   # the two live requests; the other stops are on the board
        self.assertEqual([a for a in out['appels'] if a[0] == 'decider'], [])   # never on its own
        self.assertEqual(out['decisions'], '')   # « Dernières décisions » left the page (PM, 2026-11-06)
        self.assertNotIn('Dernières décisions', out['bloc'] + out['tableau'])

    def test_a_click_sends_the_decision_and_shows_it_sent(self):
        out = self.run_page(self.payload(cliquer=[['data-decider', 'c' * 32]], attributs={'data-decision': 'allow'}))
        self.assertEqual([a for a in out['appels'] if a[0] == 'decider'], [['decider', {'id': 'c' * 32, 'decision': 'allow'}]])
        self.assertIn('Envoyé : autorisé cette fois', out['bloc'])

    def test_a_refused_call_says_so_and_keeps_the_buttons(self):
        out = self.run_page(self.payload(cliquer=[['data-decider', 'c' * 32]], attributs={'data-decision': 'deny'},
                                         deciderErreur='tool_error'))
        self.assertIn('Réponse non envoyée', out['alerte'])
        self.assertIn('data-decider="' + 'c' * 32 + '" data-decision="deny"', out['bloc'])

    def test_switched_off_no_buttons(self):
        out = self.run_page(self.payload(actif=False))
        self.assertNotIn('data-decider', out['bloc'] + out['tableau'])
        self.assertTrue(out['blocHidden'])   # nothing a click settles
        self.assertEqual(out['tableau'].count('class="titre">Session arrêtée sur une autorisation : à rouvrir'), 5)


if __name__ == '__main__':
    unittest.main()
