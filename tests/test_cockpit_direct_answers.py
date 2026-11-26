"""Tests: answer a numbered question from the pinned page while the session waits (Q11, 2026-11-02):
python3 -m unittest discover -s tests

The Stop hook (hooks/reponse_directe.py) is off by default. Switched on (cockpit.json, `reponses_directes: true`,
optionally restricted to `reponses_directes_sessions`), it looks for a question this session asked during this turn
(since the PM's last message in the transcript) that is still open on its chantier's mirror, of kind go or decision with
numbered options. It then hands a wait to every connector socket and holds the stop until the PM clicks one of the
closed answers on the page (MCP tools `attentes` and `repondre`), or until the time is up. Only an answer from the
closed list is accepted, by the hook and by the connector. Nothing about a wait is written to disk, only the journal of
answers.

Mon Studio folders, mirrors, cards and transcripts are synthetic; the real app is never run."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from test_cockpit_permission_hook import Base, ConnectorSetup, CLI, LOCAL, load_connector

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks' / 'reponse_directe.py'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
FOREMAN = 'local_00000000-0000-0000-0000-0000000000f0'
OTHER = 'local_00000000-0000-0000-0000-0000000000b0'


def iso(seconds_ago):
    return (dt.datetime.now().astimezone() - dt.timedelta(seconds=seconds_ago)).replace(microsecond=0).isoformat()


def utc(seconds_ago):
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_ago)
    return t.strftime('%Y-%m-%dT%H:%M:%S.') + f'{t.microsecond // 1000:03d}Z'


class FakeWaiter:
    """A socket that answers each wait as told: a choice string, or None (never answers)."""

    def __init__(self, path, answer, raw=None):
        self.answer, self.raw, self.requests = answer, raw, []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(4)
        threading.Thread(target=self.serve, daemon=True).start()

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
            conn.sendall(json.dumps({'id': req['id'], 'choix': self.answer}).encode() + b'\n')
            time.sleep(0.5)

    def close(self):
        self.server.close()


class Setup(Base):
    def setUp(self):
        super().setUp()
        self.chantiers = self.mon_studio / 'chantiers'
        self.chantiers.mkdir()
        self.transcript = self.root / 'cli.jsonl'
        self.write_transcript()
        self.mirror()

    def switch(self, on=True, sessions=None, minutes=None):
        state = {'version': '0.1.0'}
        if on is not None:
            state['reponses_directes'] = on
        if sessions is not None:
            state['reponses_directes_sessions'] = sessions
        if minutes is not None:
            state['reponses_directes_minutes'] = minutes
        (self.parc_dir / 'cockpit.json').write_text(json.dumps(state))

    def write_transcript(self, pm_ago=60, extra=()):
        lines = [
            {'type': 'user', 'timestamp': utc(3600), 'message': {'role': 'user', 'content': 'Une demande plus ancienne'}},
            {'type': 'assistant', 'timestamp': utc(3500), 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Fait.'}]}},
            {'type': 'user', 'timestamp': utc(pm_ago), 'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'Prépare le déploiement'}]}},
            {'type': 'assistant', 'timestamp': utc(pm_ago - 5), 'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'question.py new --kind go'}}]}},
            # A tool result and a reminder are « user » lines the PM did not type: they never start a turn.
            {'type': 'user', 'timestamp': utc(1), 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': 't1', 'content': 'Q11 · Studio : déployer ?'}]}},
            {'type': 'user', 'timestamp': utc(1), 'isMeta': True, 'message': {'role': 'user', 'content': 'méta'}},
            {'type': 'user', 'timestamp': utc(1), 'message': {'role': 'user', 'content': '<system-reminder>rappel</system-reminder>'}},
        ] + list(extra)
        self.transcript.write_text('\n'.join(json.dumps(l, ensure_ascii=False) for l in lines) + '\n')

    def mirror(self, *attentes):
        if not attentes:
            attentes = ({'type': 'go', 'titre': 'Q11 · Studio : déployer en recette ?', 'ou': 'Studio', 'depuis': iso(20),
                         'doc': 'n20261102-11', 'sessionId': LOCAL, 'sessionLabel': 'Kit A · déploiement'},)
        (self.chantiers / 'essai.json').write_text(json.dumps(
            {'chantier': 'essai', 'studio': 'Studio-Essai', 'sessionId': FOREMAN, 'attentes': list(attentes)},
            ensure_ascii=False))

    def stop_input(self, **more):
        return dict({'session_id': CLI, 'transcript_path': str(self.transcript), 'cwd': '/studios/Studio-Essai',
                     'permission_mode': 'default', 'hook_event_name': 'Stop', 'stop_hook_active': False,
                     'last_assistant_message': 'Q11 · déployer en recette ?'}, **more)

    def hook_env(self, wait=5, local=LOCAL, **more):
        env = self.env(None, MON_STUDIO_REPONSE_ATTENTE=str(wait), **more)
        if local:
            env['CLAUDE_CODE_HOST_SESSION_ID'] = local
        return env

    def hook(self, stop=None, wait=5, local=LOCAL, **more):
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(stop or self.stop_input()),
                              capture_output=True, text=True, env=self.hook_env(wait, local, **more), timeout=60)


class HookSilent(Setup):
    def assertSilent(self, r):
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))

    def test_off_by_default(self):
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        self.assertSilent(self.hook())                       # no cockpit.json
        self.switch(on=None)
        self.assertSilent(self.hook())
        self.switch(on=False)
        self.assertSilent(self.hook())
        (self.parc_dir / 'cockpit.json').write_text(json.dumps({'reponses_directes': 'true'}))
        self.assertSilent(self.hook())
        self.assertEqual(fake.requests, [])

    def test_outside_the_trial_sessions(self):
        self.switch(sessions=['cli-other', OTHER])
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        self.assertSilent(self.hook())
        self.switch(sessions='local_x')                     # not a list: nobody
        self.assertSilent(self.hook())
        self.assertEqual(fake.requests, [])

    def test_a_trial_session_by_either_id_is_concerned(self):
        for ids in ([CLI], [LOCAL]):
            self.switch(sessions=ids)
            fake = FakeWaiter(self.sock, 'go')
            out = json.loads(self.hook().stdout)
            self.assertEqual(out['decision'], 'block', ids)
            fake.close()
            self.sock.unlink()

    def test_stop_hook_active(self):
        self.switch()
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        self.assertSilent(self.hook(self.stop_input(stop_hook_active=True)))
        self.assertEqual(fake.requests, [])

    def test_windows(self):
        self.switch()
        spec = importlib.util.spec_from_file_location('reponse_directe_essai', HOOK)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        with mock.patch.object(m.os, 'name', 'nt'), mock.patch.object(sys, 'stdin', io.StringIO('{}')) as stdin:
            self.assertEqual(m.main(), 0)
            self.assertEqual(stdin.tell(), 0)               # did not even read its input

    def test_no_question_asked_during_this_turn(self):
        self.switch()
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        cases = {
            'asked before the PM spoke': dict(depuis=iso(600)),
            'asked by another session': dict(sessionId=OTHER),
            'a line for a stopped session': dict(arret='menu'),
            'a review': dict(type='review'),
            'a task': dict(type='task'),
            'a decision without numbered options': dict(type='decision', detail='Que préfères-tu ?'),
            'no number': dict(titre='Studio : déployer ?'),
        }
        base = {'type': 'go', 'titre': 'Q11 · Studio : déployer en recette ?', 'depuis': iso(20), 'sessionId': LOCAL}
        for name, change in cases.items():
            self.mirror(dict(base, **change))
            self.assertSilent(self.hook())
        (self.chantiers / 'essai.json').unlink()           # settled and gone, or never posted
        self.assertSilent(self.hook())
        self.assertEqual(fake.requests, [])

    def test_no_transcript_or_no_pm_message(self):
        self.switch()
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        self.assertSilent(self.hook(self.stop_input(transcript_path=str(self.root / 'absent.jsonl'))))
        self.transcript.write_text(json.dumps({'type': 'assistant', 'timestamp': utc(5), 'message': {}}) + '\n')
        self.assertSilent(self.hook())
        self.assertEqual(fake.requests, [])

    def test_no_session_id_of_the_app(self):
        self.switch()
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        self.assertSilent(self.hook(local=None, MON_STUDIO_APP_SESSIONS=str(self.root / 'no-app')))
        self.assertEqual(fake.requests, [])

    def test_no_socket(self):
        self.switch()
        self.assertSilent(self.hook())


class HookWaits(Setup):
    def test_the_question_of_this_turn_and_its_closed_answers(self):
        self.switch()
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        (req,) = fake.requests
        self.assertRegex(req['id'], r'^[0-9a-f]{32}$')
        self.assertEqual((req['type'], req['session_id'], req['sessionId'], req['numero'], req['kind'], req['choix']),
                         ('attente', CLI, LOCAL, 'Q11', 'go', ['go', 'pas encore']))
        self.assertEqual(req['titre'], 'Q11 · Studio : déployer en recette ?')

    def test_a_valid_answer_gives_the_block_output(self):
        self.switch()
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        r = self.hook()
        self.assertEqual(json.loads(r.stdout), {
            'decision': 'block',
            'reason': 'Réponse du PM depuis Mon Studio, mot pour mot : « Q11 go ». Solde la ligne (question.py settle) '
                      'et poursuis.'})

    def test_not_yet_keeps_the_line_open(self):
        self.switch()
        fake = FakeWaiter(self.sock, 'pas encore')
        self.addCleanup(fake.close)
        reason = json.loads(self.hook().stdout)['reason']
        self.assertIn('« Q11 pas encore »', reason)
        self.assertIn('ne la solde pas', reason)

    def test_a_decision_with_numbered_options(self):
        self.switch()
        self.mirror({'type': 'decision', 'titre': 'Q4 · Format du CR', 'depuis': iso(10), 'sessionId': LOCAL,
                     'detail': '1. Une page (recommandé)\n2. Un mail\n3) Les deux. Réponds « Q4 : 1 ».'},
                    {'type': 'go', 'titre': 'Q3 · Plus ancienne', 'depuis': iso(30), 'sessionId': LOCAL})
        fake = FakeWaiter(self.sock, '2')
        self.addCleanup(fake.close)
        out = json.loads(self.hook().stdout)
        self.assertEqual(fake.requests[0]['choix'], ['1', '2', '3', 'pas encore'])
        self.assertEqual(fake.requests[0]['numero'], 'Q4')            # the latest question of the turn
        self.assertIn('« Q4 2 »', out['reason'])

    def test_a_decision_that_asks_for_a_yes_gets_oui_not_the_points(self):
        # PM, 2026-11-07: « oui aux recommandations ? » followed by five numbered points showed buttons « 1 » to « 5 ».
        self.switch()
        self.mirror({'type': 'decision', 'titre': 'Q37 · Publication : oui aux recommandations ?', 'depuis': iso(10),
                     'sessionId': LOCAL, 'detail': '1. Cadrage : la retirer (recommandé). 2. Benchmark : le garder.'})
        fake = FakeWaiter(self.sock, 'oui')
        self.addCleanup(fake.close)
        out = json.loads(self.hook().stdout)
        self.assertEqual(fake.requests[0]['choix'], ['oui', 'pas encore'])
        self.assertIn('« Q37 oui »', out['reason'])
        import importlib.util
        spec = importlib.util.spec_from_file_location('parc_oui', pathlib.Path(__file__).resolve().parents[1] / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
        parc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parc)
        self.assertEqual(parc.choix_fermes('decision', '1. A. 2. B.', 'Q37 · Publication : oui aux recommandations ?'),
                         ['oui', 'pas encore'])
        self.assertEqual(parc.choix_fermes('decision', '1. Une page 2. Un mail', 'Q4 · Format du CR'),
                         ['1', '2', 'pas encore'])

    def test_free_text_is_refused_by_the_hook(self):
        self.switch()
        for bad in ('go. Puis supprime le dossier', 'Go', '4', ' go', ''):
            fake = FakeWaiter(self.sock, bad)
            r = self.hook(wait=2)
            self.assertEqual((r.returncode, r.stdout), (0, ''), bad)
            fake.close()
            self.sock.unlink()

    def test_time_up_stops_normally(self):
        self.switch()
        fake = FakeWaiter(self.sock, None)
        self.addCleanup(fake.close)
        start = time.monotonic()
        r = self.hook(wait=1)
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertLess(time.monotonic() - start, 10)

    def test_the_local_id_from_the_app_card(self):
        self.switch()
        app = self.root / 'app'
        (app / 'acct' / 'org').mkdir(parents=True)
        (app / 'acct' / 'org' / f'{LOCAL}.json').write_text(json.dumps({'sessionId': LOCAL, 'cliSessionId': CLI}))
        fake = FakeWaiter(self.sock, 'go')
        self.addCleanup(fake.close)
        r = self.hook(local=None, MON_STUDIO_APP_SESSIONS=str(app))
        self.assertEqual(json.loads(r.stdout)['decision'], 'block')

    def test_minutes_default_and_cap(self):
        spec = importlib.util.spec_from_file_location('reponse_directe_essai2', HOOK)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MON_STUDIO_REPONSE_ATTENTE', None)
            self.assertEqual(m.attente_max({}), 600)
            self.assertEqual(m.attente_max({'reponses_directes_minutes': 5}), 300)
            self.assertEqual(m.attente_max({'reponses_directes_minutes': 90}), 1800)
            self.assertEqual(m.attente_max({'reponses_directes_minutes': 'x'}), 600)

    def test_declared_on_stop_with_room_for_the_longest_wait(self):
        hooks = json.loads((ROOT / 'hooks' / 'hooks.json').read_text())['hooks']['Stop']
        (h,) = [x for e in hooks for x in e['hooks'] if 'reponse_directe.py' in x['command']]
        self.assertEqual((h['type'], h['timeout']), ('command', 30 * 60 + 60))
        self.assertIn('|| true', h['command'])


class WithConnector(Setup, ConnectorSetup):
    def setUp(self):
        ConnectorSetup.setUp(self)
        self.chantiers = self.mon_studio / 'chantiers'
        self.chantiers.mkdir()
        self.transcript = self.root / 'cli.jsonl'
        self.write_transcript()
        self.mirror()
        Setup.switch(self)

    def switch(self, on=True, sessions=None, minutes=None):
        Setup.switch(self, on, sessions, minutes)

    def start(self, wait=20):
        p = subprocess.Popen([sys.executable, str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=self.hook_env(wait))
        p.stdin.write(json.dumps(self.stop_input()))
        p.stdin.close()

        def done():
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
            p.stderr.close()
        self.addCleanup(done)
        return p

    def waiting(self, m=None, n=1):
        m = m or self.m
        for _ in range(200):
            d = m.attentes()
            if len(d['attentes']) >= n:
                return d
            time.sleep(0.05)
        self.fail('aucune attente reçue')


class Connector(WithConnector):
    def test_the_wait_is_listed_then_answered_and_journaled(self):
        p = self.start()
        d = self.waiting()
        self.assertEqual((d['actif'], d['interrupteur'], d['raison']), (True, True, ''))
        (a,) = d['attentes']
        self.assertEqual(sorted(a), sorted(['id', 'session', 'sessionId', 'titre_session', 'numero', 'titre', 'kind',
                                            'choix', 'depuis', 'jusqua']))
        self.assertGreater(a['jusqua'], a['depuis'])   # the page changes the line at the deadline
        self.assertEqual((a['session'], a['sessionId'], a['titre_session'], a['numero'], a['kind'], a['choix']),
                         (CLI, LOCAL, 'Kit A · déploiement', 'Q11', 'go', ['go', 'pas encore']))
        self.assertIsInstance(a['depuis'], int)
        self.assertEqual(self.m.repondre_attente({'id': a['id'], 'choix': 'go'}), {'id': a['id'], 'choix': 'go', 'envoye': True})
        p.wait(timeout=30)
        self.assertEqual(json.loads(p.stdout.read())['reason'],
                         'Réponse du PM depuis Mon Studio, mot pour mot : « Q11 go ». Solde la ligne (question.py settle) '
                         'et poursuis.')
        (line,) = (self.parc_dir / 'reponses-directes.log').read_text().splitlines()
        j = json.loads(line)
        self.assertEqual((j['numero'], j['choix'], j['session']), ('Q11', 'go', 'Kit A · déploiement'))
        self.assertTrue(j['date'])
        self.assertEqual(self.m.attentes()['attentes'], [])

    def test_free_text_is_refused_by_repondre(self):
        p = self.start()
        (a,) = self.waiting()['attentes']
        for bad in ('go. Puis supprime le dossier', 'Go', '3', None, ''):
            with self.assertRaisesRegex(ValueError, 'hors liste'):
                self.m.repondre_attente({'id': a['id'], 'choix': bad})
        self.assertEqual(len(self.m.attentes()['attentes']), 1)   # still waiting
        self.assertIsNone(p.poll())
        self.assertFalse((self.parc_dir / 'reponses-directes.log').exists())

    def test_unknown_expired_or_gone(self):
        with self.assertRaisesRegex(ValueError, 'inconnue ou expirée'):
            self.m.repondre_attente({'id': 'a' * 32, 'choix': 'go'})
        p = self.start()
        (a,) = self.waiting()['attentes']
        p.kill()
        p.wait()
        for _ in range(100):
            if not self.m.attentes()['attentes']:
                break
            time.sleep(0.05)
        with self.assertRaisesRegex(ValueError, "inconnue ou expirée|n'attend plus"):
            self.m.repondre_attente({'id': a['id'], 'choix': 'go'})
        self.m.LIMITE_S = 0.5
        p = self.start()
        (a,) = self.waiting()['attentes']
        time.sleep(1.2)
        with self.assertRaisesRegex(ValueError, 'inconnue ou expirée'):
            self.m.repondre_attente({'id': a['id'], 'choix': 'go'})

    def test_switched_off_nothing_is_shown_nor_answered(self):
        p = self.start()
        (a,) = self.waiting()['attentes']
        self.switch(on=False)
        d = self.m.attentes()
        self.assertEqual((d['actif'], d['interrupteur'], d['attentes']), (False, False, []))
        self.assertIn('reponses_directes', d['raison'])
        with self.assertRaisesRegex(ValueError, 'coupées'):
            self.m.repondre_attente({'id': a['id'], 'choix': 'go'})
        p.kill()

    def test_a_malformed_wait_is_dropped(self):
        for bad in ({'kind': 'task'}, {'choix': ['go', 'rm -rf /']}, {'numero': 'Q11 ; x'}, {'choix': ['go']}):
            msg = dict({'v': 1, 'type': 'attente', 'id': 'e' * 32, 'session_id': CLI, 'sessionId': LOCAL,
                        'numero': 'Q11', 'titre': 't', 'kind': 'go', 'choix': ['go', 'pas encore']}, **bad)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(self.sock))
            s.sendall(json.dumps(msg).encode() + b'\n')
            time.sleep(0.2)
            self.assertEqual(self.m.attentes()['attentes'], [], bad)
            s.close()

    def test_no_wait_on_disk(self):
        before = self.files()
        p = self.start()
        (a,) = self.waiting()['attentes']
        self.assertEqual(self.files(), before)
        self.m.repondre_attente({'id': a['id'], 'choix': 'pas encore'})
        p.wait(timeout=30)
        self.assertEqual(sorted(set(self.files()) - set(before)), ['.parc/reponses-directes.log'])
        for f in self.mon_studio.rglob('*'):
            if f.is_file():
                self.assertNotIn(a['id'], f.read_text(errors='replace'), f)

    def test_the_tools_are_declared_and_repondre_is_not_read_only(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.traiter({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            self.m.traiter({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                            'params': {'name': 'repondre', 'arguments': {'id': 'b' * 32, 'choix': 'go'}}})
            self.m.traiter({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'attentes', 'arguments': {}}})
        listed, called, listed_waits = [json.loads(l) for l in buf.getvalue().splitlines()]
        tools = {t['name']: t for t in listed['result']['tools']}
        self.assertEqual(sorted(tools), ['attentes', 'autorisations', 'clore', 'conflits_juger', 'decider', 'gabarit', 'lignes', 'lire', 'matin_ecrire', 'ouvrir', 'projet', 'repondre', 'slack_juger', 'slack_ouvertes'])
        self.assertIs(tools['repondre']['annotations']['readOnlyHint'], False)
        self.assertIs(tools['lire']['annotations']['readOnlyHint'], True)   # « Lire » writes nothing
        self.assertIs(tools['attentes']['annotations']['readOnlyHint'], True)
        # Q40: « id » for a session that waits on the page, « session » and « question » for one that does not.
        self.assertEqual(tools['repondre']['inputSchema']['required'], ['choix'])
        self.assertEqual(sorted(tools['repondre']['inputSchema']['properties']), ['choix', 'id', 'question', 'session'])
        self.assertTrue(called['result']['isError'])
        self.assertIn('inconnue ou expirée', called['result']['content'][0]['text'])
        self.assertEqual(json.loads(listed_waits['result']['content'][0]['text'])['attentes'], [])


class TwoConnectors(WithConnector):
    def setUp(self):
        super().setUp()
        self.m2 = load_connector(self.mon_studio, self.app, self.transcripts)
        self.sock2 = self.parc_dir / f'autorisations-{os.getppid()}.sock'
        self.m2.AUTORISATIONS = self.m2.Autorisations(self.sock2)
        self.assertTrue(self.m2.AUTORISATIONS.demarrer(), self.m2.AUTORISATIONS.raison)
        self.addCleanup(self.m2.AUTORISATIONS.arreter)

    def test_the_answer_comes_through_the_second(self):
        p = self.start()
        (a1,) = self.waiting(self.m)['attentes']
        (a2,) = self.waiting(self.m2)['attentes']
        same = lambda a: {k: v for k, v in a.items() if k not in ('depuis', 'jusqua')}   # each instance dates its own receipt
        self.assertEqual(same(a1), same(a2))
        self.m2.repondre_attente({'id': a2['id'], 'choix': 'go'})
        p.wait(timeout=30)
        self.assertIn('« Q11 go »', json.loads(p.stdout.read())['reason'])
        for _ in range(100):   # the hook closed the first connection: the wait leaves the first instance
            if not self.m.attentes()['attentes']:
                break
            time.sleep(0.05)
        self.assertEqual(self.m.attentes()['attentes'], [])
        with self.assertRaisesRegex(ValueError, 'inconnue ou expirée'):
            self.m.repondre_attente({'id': a1['id'], 'choix': 'go'})
        self.assertEqual(len((self.parc_dir / 'reponses-directes.log').read_text().splitlines()), 1)


@unittest.skipUnless(shutil.which('node'), 'node absent : la page épinglée n\'est pas essayée')
class PageButtons(unittest.TestCase):
    def run_page(self, payload):
        with tempfile_dir() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def payload(self, actif=True, **more):
        lignes = [
            {'studio': 'Studio-Essai', 'session': 'Déploiement', 'cle': LOCAL, 'ouvrir': LOCAL, 'type': 'go', 'verbe': 'Go',
             'affiche_suite': 'Q11 · Studio : déployer en recette ?', 'question': 'Q11', 'choix': ['go', 'pas encore']},
            {'studio': 'Studio-Essai', 'session': 'Autre', 'cle': OTHER, 'ouvrir': OTHER, 'type': 'go', 'verbe': 'Go',
             'affiche_suite': 'Q12 · Studio : livrer ?', 'question': 'Q12', 'choix': ['go', 'pas encore']},
            {'studio': 'Studio-Essai', 'session': 'Déploiement, ancienne', 'cle': LOCAL, 'ouvrir': LOCAL, 'type': 'decision',
             'affiche_suite': 'Q9 · Studio : format ?', 'question': 'Q9'},
        ]
        attentes = [{'id': 'f' * 32, 'session': CLI, 'sessionId': LOCAL, 'titre_session': 'Kit A · déploiement',
                     'numero': 'Q11', 'titre': 'Q11 · Studio : déployer en recette ?', 'kind': 'go',
                     'choix': ['go', 'pas encore'], 'depuis': int(time.time() * 1000)}]
        return dict({'lignes': lignes, 'attentes': {'actif': actif, 'interrupteur': actif, 'raison': '',
                                                     'attentes': attentes if actif else []}}, **more)

    def rows(self, html):
        return [r for r in html.split('<tr') if '<td class="action">' in r]

    def test_buttons_only_on_the_waiting_line(self):
        out = self.run_page(self.payload())
        self.assertIn('attentes', out['veilles'])
        rows = self.rows(out['tableau'])
        waiting = [r for r in rows if 'Q11 ·' in r]
        others = [r for r in rows if 'Q11 ·' not in r]
        self.assertEqual(len(waiting), 1)
        self.assertIn('data-repondre="' + 'f' * 32 + '" data-choix="go"', waiting[0])
        # « Pas encore » is gone (PM, 2026-11-17): « Plus tard » hides the line on the board, nothing is sent.
        self.assertNotIn('data-choix="pas encore"', waiting[0])
        self.assertIn('>Go</button>', waiting[0])
        self.assertNotIn('>Pas encore</button>', waiting[0])
        # PM, 2026-11-07: the answer buttons never take the place of the way into the session.
        self.assertIn('>Ouvrir ↗</button>', waiting[0])
        self.assertIn('data-sid=', waiting[0])
        self.assertEqual(len(others), 2)
        for r in others:                                     # another session, or the same session's other question
            self.assertNotIn('data-repondre', r)
        self.assertNotIn("ne t'attend plus", out['tableau'])   # no deadline, no countdown (Q34)
        self.assertEqual([a for a in out['appels'] if a[0] == 'repondre'], [])   # never on its own

    def test_a_chantier_line_gets_the_buttons_of_the_session_that_asked(self):
        # Essai Q11 du 2026-11-02 : la ligne Q32 venait du miroir du chantier, cle = le contremaître, source = la
        # session qui attendait ; la page ne rapprochait que cle, et Alex ne voyait que « Go ↗ ».
        foreman = 'local_' + 'c' * 8 + '-0000-0000-0000-000000000000'
        p = self.payload()
        p['lignes'] = [
            {'studio': 'Studio-Essai', 'session': 'Déploiement', 'cle': foreman, 'source': LOCAL, 'ouvrir': foreman,
             'type': 'go', 'verbe': 'Go', 'affiche_suite': 'Q11 · Studio : déployer en recette ?', 'question': 'Q11'},
            {'studio': 'Studio-Essai', 'session': 'Déploiement', 'cle': foreman, 'source': LOCAL, 'ouvrir': foreman,
             'type': 'decision', 'verbe': 'Répondre', 'affiche_suite': 'Q9 · Studio : format ?', 'question': 'Q9'},
            {'studio': 'Studio-Essai', 'session': 'Autre', 'cle': foreman, 'source': OTHER, 'ouvrir': foreman,
             'type': 'go', 'verbe': 'Go', 'affiche_suite': 'Q11 · Studio : autre ?', 'question': 'Q11'},
        ]
        rows = self.rows(self.run_page(p)['tableau'])
        self.assertIn('data-repondre="' + 'f' * 32 + '" data-choix="go"', rows[0])
        self.assertNotIn('data-repondre', rows[1])           # same session, another question
        self.assertNotIn('data-repondre', rows[2])           # same number, another session

    def test_while_waiting_two_buttons_and_the_page_rerenders_at_the_deadline(self):
        # Essai de la réponse en direct du 02/11 : la ligne change au moment où la limite passe.
        p = self.payload(avancerMs=1500)   # past the first second of swap, the next re-render is the deadline
        p['attentes']['attentes'][0]['jusqua'] = int(time.time() * 1000) + 600000
        out = self.run_page(p)
        waiting = [r for r in self.rows(out['tableau']) if 'Q11 ·' in r][0]
        self.assertIn('data-choix="go"', waiting)
        self.assertNotIn('data-choix="pas encore"', waiting)
        self.assertNotIn('liberee', waiting)
        self.assertTrue(any(590000 < m <= 600100 for m in out['minuteurs'] if m), out['minuteurs'])

    def test_once_the_limit_passed_the_same_buttons_copy_and_open(self):
        # Q34 du 2026-11-04 : plus de « la session ne t'attend plus » ni d'autre bouton ; « Go » reste « Go ». Sans
        # attente, il copie « Q11 go » et ouvre la session. Le chemin vient de changer : une seconde d'inaction.
        p = self.payload(avancerMs=3000)   # the session waits, then its limit passes
        p['attentes']['attentes'][0]['jusqua'] = int(time.time() * 1000) + 2000
        out = self.run_page(p)
        self.assertIn('data-choix="go"', [r for r in self.rows(out['premier']) if 'Q11 ·' in r][0])
        waiting = [r for r in self.rows(out['tableau']) if 'Q11 ·' in r][0]
        self.assertNotIn('data-repondre', waiting)
        self.assertIn('data-reveil="' + LOCAL + '" data-question="Q11" data-choix="go" data-copier="Q11 go"', waiting)
        self.assertNotIn('data-copier="Q11 pas encore"', waiting)
        self.assertEqual(waiting.count('>Go</button>'), 1)
        self.assertNotIn("t'attend plus", out['tableau'])
        self.assertNotIn('Ouvrir la session pour répondre', out['tableau'])
        self.assertIn(' disabled', waiting.split('data-copier="Q11 go"')[1].split('>')[0])   # one second of swap

    def test_after_the_swap_second_the_button_works(self):
        p = self.payload(avancerMs=1500)
        p['attentes']['attentes'][0]['jusqua'] = int(time.time() * 1000) - 1000
        waiting = [r for r in self.rows(self.run_page(p)['tableau']) if 'Q11 ·' in r][0]
        self.assertNotIn(' disabled', waiting.split('data-copier="Q11 go"')[1].split('>')[0])

    def test_a_session_that_left_keeps_the_same_buttons(self):
        # La session est repartie (réponse dans l'app) : son attente disparaît, la ligne garde « Go », par la copie.
        p = self.payload(attentesApres={'actif': True, 'interrupteur': True, 'raison': '', 'attentes': []})
        out = self.run_page(p)
        self.assertIn('data-choix="go"', [r for r in self.rows(out['premier']) if 'Q11 ·' in r][0])
        after = [r for r in self.rows(out['tableau']) if 'Q11 ·' in r][0]
        self.assertNotIn('data-repondre', after)
        self.assertIn('data-copier="Q11 go"', after)
        self.assertNotIn("t'attend plus", after)

    def test_without_a_wait_go_copies_the_whole_answer_and_opens_the_session(self):
        p = self.payload(actif=False)
        rows = self.rows(self.run_page(p)['tableau'])
        q12 = [r for r in rows if 'Q12 ·' in r][0]
        self.assertIn('data-reveil="' + OTHER + '" data-question="Q12" data-choix="go" data-copier="Q12 go"', q12)
        self.assertNotIn(' disabled', q12.split('data-copier="Q12 go"')[1].split('>')[0])   # no swap on a first render
        cle = '|'.join([OTHER, 'Q12', '', 'Q12 · Studio : livrer ?'])
        # Q40: the click first asks the connector to answer the session; a connector from before Q40 (no « mode » in
        # its answer) leaves the old way: the whole answer copied and the session opened.
        out = self.run_page(self.payload(actif=False, cliquer=[['data-reveil', OTHER]],
                                         attributs={'data-question': 'Q12', 'data-choix': 'go', 'data-copier': 'Q12 go',
                                                    'data-ligne': cle}))
        self.assertEqual([a for a in out['appels'] if a[0] == 'repondre'],
                         [['repondre', {'session': OTHER, 'question': 'Q12', 'choix': 'go'}]])
        self.assertEqual([a for a in out['appels'] if a[0] == 'ouvrir'], [['ouvrir', {'id': OTHER, 'copier': 'Q12 go'}]])
        q12 = [r for r in self.rows(out['tableau']) if 'Q12 ·' in r][0]
        self.assertIn('« Q12 go » copié : colle-le dans la session', q12)

    def test_a_chantier_line_copies_for_the_session_that_asked(self):
        foreman = 'local_' + 'c' * 8 + '-0000-0000-0000-000000000000'
        p = self.payload(actif=False)
        p['lignes'] = [{'studio': 'Studio-Essai', 'session': 'Déploiement', 'cle': foreman, 'source': LOCAL, 'ouvrir': foreman,
                        'type': 'decision', 'verbe': 'Répondre', 'affiche_suite': 'Q9 · Studio : format ?', 'question': 'Q9',
                        'choix': ['1', '2', 'pas encore']}]
        row = self.rows(self.run_page(p)['tableau'])[0]
        self.assertIn('data-reveil="' + LOCAL + '" data-question="Q9" data-choix="1" data-copier="Q9 1"', row)
        self.assertIn('data-copier="Q9 2"', row)
        self.assertNotIn('data-copier="Q9 pas encore"', row)
        # The answers under the question, « Ouvrir ↗ » alone in « Agir » (PM, 2026-11-26: one line per gesture made rows high).
        self.assertIn('data-copier="Q9 1"', row.split('<td class="type">')[0].split('<td class="action">')[1])
        self.assertEqual(row.count('>Ouvrir ↗<'), 1)

    def test_the_answer_buttons_replace_the_open_verb(self):
        # Essai Q11 du 2026-11-02 : « Go ↗ » (ouvre la session) et « Go » (la réponse) côte à côte ; le PM ouvrait.
        rows = self.rows(self.run_page(self.payload())['tableau'])
        for r in [r for r in rows if 'Q11 ·' in r or 'Q12 ·' in r]:
            self.assertIn('class="reponses"', r.split('<td class="type">')[0])   # the answers under the question
            self.assertEqual(r.count('>Ouvrir ↗<'), 1)                            # « Ouvrir ↗ » stays, in « Agir »
            self.assertEqual(r.count('>Go'), 1)
        q9 = [r for r in rows if 'Q9 ·' in r][0]
        self.assertIn('class="act k-task ouvrir"', q9)                     # a decision without numbered options keeps its verb
        self.assertNotIn('class="reponses"', q9)

    def test_the_page_says_when_direct_answers_cannot_work(self):
        self.assertEqual(self.run_page(self.payload())['noteAttentes'], '')
        p = self.payload(actif=False)
        p['attentes']['interrupteur'] = True
        p['attentes']['raison'] = 'socket impossible'
        self.assertIn('socket impossible', self.run_page(p)['noteAttentes'])
        self.assertEqual(self.run_page(self.payload(actif=False))['noteAttentes'], '')   # switched off: normal
        self.assertIn('tool_error', self.run_page(dict(self.payload(), attentesErreur='tool_error'))['noteAttentes'])
        refused = self.run_page(dict(self.payload(), refuserVeille=['attentes']))
        self.assertIn("n'est pas accordé", refused['noteAttentes'])

    def test_a_click_sends_the_answer_and_shows_it_sent(self):
        out = self.run_page(self.payload(cliquer=[['data-repondre', 'f' * 32]], attributs={'data-choix': 'go'}))
        self.assertEqual([a for a in out['appels'] if a[0] == 'repondre'], [['repondre', {'id': 'f' * 32, 'choix': 'go'}]])
        self.assertIn('Envoyée, la session reprend', out['tableau'])
        self.assertNotIn('data-repondre', out['tableau'])

    def test_a_choice_outside_the_list_is_not_sent(self):
        out = self.run_page(self.payload(cliquer=[['data-repondre', 'f' * 32]], attributs={'data-choix': 'go, et plus'}))
        self.assertEqual([a for a in out['appels'] if a[0] == 'repondre'], [])

    def test_a_refused_call_says_so_and_keeps_the_buttons(self):
        out = self.run_page(self.payload(cliquer=[['data-repondre', 'f' * 32]], attributs={'data-choix': 'go'},
                                         repondreErreur='tool_error'))
        self.assertIn('Réponse non envoyée', out['alerte'])
        self.assertIn('data-repondre="' + 'f' * 32 + '"', out['tableau'])

    def test_switched_off_nothing_changes(self):
        off = self.run_page(self.payload(actif=False))
        self.assertNotIn('data-repondre', off['tableau'])
        self.assertNotIn('Envoyée', off['tableau'])
        none = self.run_page({'lignes': self.payload()['lignes']})
        self.assertEqual(off['tableau'], none['tableau'])


@contextlib.contextmanager
def tempfile_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        yield d


if __name__ == '__main__':
    unittest.main()
