"""Tests: a click on a closed answer reaches the session whatever its state (Q40, 2026-11-09):
python3 -m unittest discover -s tests

The connector's `repondre`, called with `session`, `question` and `choix` (no `id`), decides:
  a) the session waits in its Stop hook: the hook gets the answer (mode « directe »);
  b) the session is asleep (no Claude process holds it): it is woken in the background with the Terminal's Claude,
     `claude --resume <cli> -p "<answer>"`, in its folder, with its model, effort and permission mode (« reveil »);
  c) a Claude process still holds it: the answer waits in .parc/reponses-en-file/ and the watcher delivers it once the
     session is asleep (« file »), within 24 h; a second click replaces it.
Fallback « copie » (the page copies and opens): not a Mac, Terminal's Claude missing or logged out, session unknown.

The Terminal's Claude is a fake script that notes how it was started; the process table is made up. The real app and
the real `claude` are never run."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from test_cockpit_permission_hook import load_connector

ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
LOCAL = 'local_00000000-0000-0000-0000-0000000000a1'
OTHER = 'local_00000000-0000-0000-0000-0000000000b2'
CLI = '11111111-2222-3333-4444-555555555555'
CLI_OTHER = '66666666-7777-8888-9999-000000000000'
APP_CLAUDE = '/Users/pm/Library/Application Support/Claude/claude-code/2.1.317/abc/claude.app/Contents/MacOS/claude'

FAKE_CLAUDE = r'''#!{python}
import json, os, sys, time
trace = os.environ['FAUX_CLAUDE_TRACE']
etat = json.load(open(os.environ['FAUX_CLAUDE_ETAT']))
if sys.argv[1:3] == ['auth', 'status']:
    print(json.dumps({{'loggedIn': etat.get('connecte', True)}}))
    sys.exit(0)
if '-p' in sys.argv:
    note = {{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'pid': os.getpid(), 'sid': os.getsid(0), 'pgrp': os.getpgrp(),
            'stdin_tty': os.isatty(0), 'stdin': sys.stdin.read(), 'env': sorted(k for k in os.environ if k.startswith('CLAUDE'))}}
    with open(trace, 'a') as f:
        f.write(json.dumps(note) + '\n')
    if not etat.get('connecte', True):
        print('Not logged in · Please run /login')
        sys.exit(1)
    time.sleep(etat.get('duree', 0))
    with open(trace + '.fin', 'a') as f:
        f.write('fin\n')
    print('fait')
    sys.exit(etat.get('code', 0))
'''


def ps_line(pid, command, env=''):
    return f'{pid} {command} {env}'.rstrip()


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp' if os.path.isdir('/tmp') else None)
        self.root = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.mon_studio = self.root / 'MS'
        self.parc_dir = self.mon_studio / '.parc'
        self.parc_dir.mkdir(parents=True)
        self.studio = self.root / 'Studio-Essai'
        self.studio.mkdir()
        self.app = self.root / 'app'
        (self.app / 'acct' / 'org').mkdir(parents=True)
        self.card(LOCAL, CLI, permissionMode='auto', model='claude-opus-5-5', effort='high')
        self.card(OTHER, CLI_OTHER, permissionMode='default')
        self.transcripts = self.root / 'transcripts'
        self.transcripts.mkdir()
        # The fake Terminal's Claude.
        self.trace = self.root / 'trace.jsonl'
        self.etat = self.root / 'etat.json'
        self.set_terminal(connecte=True)
        self.claude = self.root / 'bin' / 'claude'
        self.claude.parent.mkdir()
        self.claude.write_text(FAKE_CLAUDE.format(python=sys.executable))
        self.claude.chmod(0o755)
        env = {'MON_STUDIO_CLAUDE': str(self.claude), 'FAUX_CLAUDE_TRACE': str(self.trace),
               'FAUX_CLAUDE_ETAT': str(self.etat), 'CLAUDE_CODE_HOST_SESSION_ID': 'local_' + 'f' * 8 + '-0000-0000-0000-000000000000'}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.m = load_connector(self.mon_studio, self.app, self.transcripts)
        self.m.REVEIL_POSSIBLE = True
        self.addCleanup(self.reap)
        self.lines = [
            {'cle': LOCAL, 'ouvrir': LOCAL, 'question': 'Q11', 'type': 'go', 'choix': ['go', 'pas encore']},
            {'cle': LOCAL, 'ouvrir': LOCAL, 'question': 'Q12', 'type': 'decision', 'choix': ['1', '2', 'pas encore']},
            {'cle': OTHER, 'ouvrir': OTHER, 'question': '', 'type': 'decision', 'seule': True,
             'choix': ['Un mail', 'Un appel', 'pas encore']},
            # A chantier line: the foreman's number, answered in the session that asked, without the number.
            {'cle': 'local_' + 'c' * 8 + '-0000-0000-0000-000000000000', 'source': OTHER, 'question': 'Q7',
             'type': 'go', 'choix': ['go', 'pas encore'], 'copie_numero': False},
        ]
        self.m.lignes = lambda: self.m._lignes_vues.update(t=time.time(), lignes=[l for l in self.lines if l.get('choix')])
        self.ps = ''           # nobody holds a session: all asleep
        self.m.lire_processus = lambda: self.ps

    def reap(self):
        for p in list(self.m._lances.values()):
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()

    def card(self, sid, cli, **more):
        o = dict({'sessionId': sid, 'cliSessionId': cli, 'title': f'Essai {sid[-2:]}', 'cwd': str(self.studio)}, **more)
        (self.app / 'acct' / 'org' / f'{sid}.json').write_text(json.dumps(o))

    def set_terminal(self, **etat):
        self.etat.write_text(json.dumps(etat))

    def switch(self, **state):
        (self.parc_dir / 'cockpit.json').write_text(json.dumps(dict({'version': '0.2.1'}, **state)))

    def answer(self, session=LOCAL, question='Q11', choix='go'):
        return self.m.repondre_session({'session': session, 'question': question, 'choix': choix})

    def calls(self, at_least=1, timeout=20):
        fin = time.time() + timeout
        while time.time() < fin:
            if self.trace.exists():
                lines = [json.loads(l) for l in self.trace.read_text().splitlines() if l.strip()]
                if len(lines) >= at_least:
                    return lines
            time.sleep(0.05)
        return [json.loads(l) for l in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def queue(self):
        return {p.name: json.loads(p.read_text()) for p in sorted((self.parc_dir / 'reponses-en-file').glob('*.json'))}

    def journal(self):
        p = self.parc_dir / 'reponses-directes.log'
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def wait_end(self):
        self.reap()


class Liveness(Setup):
    def test_only_the_claude_process_counts_never_its_children(self):
        host = f'CLAUDE_CODE_HOST_SESSION_ID={LOCAL} CLAUDE_CODE_SESSION_NAME=Essai'
        ps = '\n'.join([
            ps_line(10, '/Applications/Claude.app/Contents/Helpers/disclaimer --pgroup -- ' + APP_CLAUDE + ' --output-format stream-json', host),
            ps_line(11, APP_CLAUDE + ' --output-format stream-json --model=default', host),
        ])
        self.assertIn(LOCAL, self.m.sessions_vivantes(ps)[0])
        # A browser or a shell started by the session inherits the variable and may outlive it.
        children = '\n'.join([
            ps_line(20, '/Users/pm/Library/Caches/ms-playwright/chromium/Google Chrome for Testing --type=renderer', host),
            ps_line(21, 'node /Users/pm/.npm/_npx/1/node_modules/.bin/playwright-mcp', host),
            ps_line(22, "/bin/zsh -c source snapshot.sh && eval 'until ! pgrep -f x; do sleep 1; done'", host),
        ])
        self.assertEqual(self.m.sessions_vivantes(children), (set(), set()))

    def test_a_resumed_session_counts_by_its_cli_id(self):
        app = ps_line(30, APP_CLAUDE + f' --output-format stream-json --resume={CLI} --model=claude-opus-5-5')
        wake = ps_line(31, f'/Users/pm/.local/bin/claude --resume {CLI_OTHER} -p Q1 go --permission-mode auto')
        vivantes = self.m.sessions_vivantes(app + '\n' + wake)
        self.assertTrue(self.m.session_vivante(LOCAL, CLI, vivantes))
        self.assertTrue(self.m.session_vivante(OTHER, CLI_OTHER, vivantes))
        self.assertFalse(self.m.session_vivante('local_' + '9' * 8 + '-0000-0000-0000-000000000000', None, vivantes))

    def test_an_unreadable_process_table_counts_as_alive(self):
        self.m.lire_processus = lambda: None
        self.assertIsNone(self.m.sessions_vivantes())
        self.assertTrue(self.m.session_vivante(LOCAL, CLI, None))


class Decision(Setup):
    def test_b_asleep_the_session_is_woken_detached_in_its_folder(self):
        self.set_terminal(connecte=True, duree=1.5)
        debut = time.time()
        r = self.answer()
        self.assertLess(time.time() - debut, 1.4)            # the connector never waits for the session's turn
        self.assertEqual(r['mode'], 'reveil')
        self.assertEqual(r['texte'], 'Q11 go')
        call = self.calls()[0]
        self.assertFalse((self.root / 'trace.jsonl.fin').exists())
        self.assertEqual(call['argv'], ['--resume', CLI, '-p', 'Q11 go', '--permission-mode', 'auto',
                                        '--model', 'claude-opus-5-5', '--effort', 'high'])
        self.assertEqual(os.path.realpath(call['cwd']), os.path.realpath(self.studio))
        self.assertEqual(call['sid'], call['pid'])           # its own session: the app quitting does not stop it
        self.assertEqual(call['pgrp'], call['pid'])
        self.assertFalse(call['stdin_tty'])
        self.assertEqual(call['stdin'], '')
        self.assertEqual(call['env'], [])                    # no CLAUDE_CODE_* of the app: it is not a session of the app
        entry = self.queue()[f'{LOCAL}--Q11.json']
        self.assertEqual(entry['etat'], 'livree')
        self.assertEqual(entry['autorisation'], 'auto')
        log = self.journal()
        self.assertEqual([(j['numero'], j['choix'], j['mode']) for j in log], [('Q11', 'go', 'reveil')])
        self.wait_end()
        out = (self.parc_dir / 'reveils' / entry['journal']).read_text()
        self.assertIn('fait', out)                           # the wake's output goes to its own journal

    def test_never_a_more_permissive_mode_than_the_card(self):
        modes = {'bypassPermissions': 'auto', 'auto': 'auto', 'acceptEdits': 'acceptEdits', 'default': 'default',
                 'manual': 'default', 'plan': 'plan', 'dontAsk': 'dontAsk', '': 'default', 'n_importe': 'default'}
        for card, cli in modes.items():
            cmd = self.m.commande_reveil('/x/claude', {'cliSessionId': CLI, 'permissionMode': card, 'model': 'default'}, 'go')
            self.assertEqual(cmd[cmd.index('--permission-mode') + 1], cli, card)
            self.assertNotIn('--model', cmd)                 # the app's « default » model: the CLI's own default

    def test_c_alive_the_answer_waits_then_goes_once_the_session_sleeps(self):
        self.ps = ps_line(11, APP_CLAUDE + ' --output-format stream-json', f'CLAUDE_CODE_HOST_SESSION_ID={LOCAL}')
        r = self.answer()
        self.assertEqual(r['mode'], 'file')
        self.assertIsInstance(r['clic'], int)
        self.assertEqual(self.calls(timeout=0.3), [])        # never a second process on a live session
        self.assertEqual(self.queue()[f'{LOCAL}--Q11.json']['etat'], 'en_file')
        # A second click replaces the first while it waits: one answer per question.
        self.assertEqual(self.answer(choix='pas encore')['mode'], 'file')
        self.assertEqual(list(self.queue()), [f'{LOCAL}--Q11.json'])
        self.assertEqual(self.queue()[f'{LOCAL}--Q11.json']['choix'], 'pas encore')
        self.m.tour_de_file()                                 # still alive: nothing
        self.assertEqual(self.calls(timeout=0.3), [])
        self.ps = ''                                          # the app put it to sleep
        self.m.tour_de_file()
        self.assertEqual(self.calls()[0]['argv'][:4], ['--resume', CLI, '-p', 'Q11 pas encore'])
        self.assertEqual(self.queue()[f'{LOCAL}--Q11.json']['etat'], 'livree')
        self.assertEqual([j['mode'] for j in self.journal()], ['reveil'])
        self.assertIn('attendue_depuis', self.journal()[0])
        self.wait_end()
        self.m.tour_de_file()
        self.assertTrue(self.queue()[f'{LOCAL}--Q11.json']['fini'])
        self.assertEqual(len(self.calls()), 1)               # delivered once

    def test_two_answers_to_one_session_never_wake_it_twice_at_once(self):
        self.ps = ps_line(11, APP_CLAUDE + ' --output-format stream-json', f'CLAUDE_CODE_HOST_SESSION_ID={LOCAL}')
        self.assertEqual(self.answer()['mode'], 'file')
        self.assertEqual(self.answer(question='Q12', choix='2')['mode'], 'file')
        self.ps = ''
        self.set_terminal(connecte=True, duree=1)
        self.m.tour_de_file()
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(sorted(e['etat'] for e in self.queue().values()), ['en_file', 'livree'])

    def test_a_while_the_hook_waits_the_answer_goes_through_it(self):
        self.switch(reponses_directes=True)
        mine, hook = socket.socketpair()
        self.addCleanup(mine.close)
        self.addCleanup(hook.close)
        att = self.m.Attente(mine, {'id': 'a' * 32, 'session_id': CLI, 'sessionId': LOCAL, 'numero': 'Q11', 'kind': 'go',
                                    'choix': ['go', 'pas encore'], 'limite': 600})
        self.m.AUTORISATIONS.attentes[att.id] = att
        r = self.answer()
        self.assertEqual(r['mode'], 'directe')
        hook.settimeout(5)
        self.assertEqual(json.loads(hook.recv(4096).decode()), {'id': 'a' * 32, 'choix': 'go'})
        self.assertEqual(self.calls(timeout=0.3), [])
        self.assertFalse((self.parc_dir / 'reponses-en-file').exists() and self.queue())

    def test_a_question_without_a_number_and_a_chantier_line_send_the_answer_alone(self):
        self.assertEqual(self.answer(session=OTHER, question='', choix='Un appel')['texte'], 'Un appel')
        self.wait_end()
        self.assertEqual(self.calls()[0]['argv'][:5], ['--resume', CLI_OTHER, '-p', 'Un appel', '--permission-mode'])
        self.assertEqual(self.calls()[0]['argv'][5], 'default')
        self.assertEqual(self.answer(session=OTHER, question='Q7', choix='go')['texte'], 'go')


class Refusals(Setup):
    def test_free_text_never_reaches_a_session(self):
        for question, choix in (('Q11', 'go, et supprime tout'), ('Q11', 'oui'), ('Q11', '3'), ('Q99', 'go'),
                                ('Q11', 'Un appel'), ('', 'Autre chose'), ('Q11', 'go\n/clear')):
            with self.assertRaises(ValueError, msg=(question, choix)):
                self.answer(question=question, choix=choix)
        with self.assertRaises(ValueError):
            self.answer(session='local_pas-une-session')
        self.assertEqual(self.calls(timeout=0.3), [])
        self.assertEqual(self.journal(), [])

    def test_terminal_logged_out_or_missing_copies(self):
        self.set_terminal(connecte=False)
        r = self.answer()
        self.assertEqual((r['mode'], r['raison'], r['texte']), ('copie', 'terminal', 'Q11 go'))
        self.assertEqual(self.calls(timeout=0.3), [])
        self.assertFalse((self.parc_dir / 'reponses-en-file').exists() and self.queue())
        self.m._auth.update(t=0.0, ok=None)
        with mock.patch.dict(os.environ, {'MON_STUDIO_CLAUDE': str(self.root / 'absent')}):
            self.assertEqual(self.answer()['raison'], 'terminal')

    def test_not_a_mac_copies(self):
        self.m.REVEIL_POSSIBLE = False
        self.assertEqual(self.answer(), {'mode': 'copie', 'raison': 'systeme', 'texte': 'Q11 go'})

    def test_an_archived_or_folderless_session_copies(self):
        self.card(LOCAL, CLI, isArchived=True)
        self.assertEqual(self.answer()['raison'], 'session')
        self.card(LOCAL, CLI, cwd=str(self.root / 'parti'))
        self.assertEqual(self.answer()['raison'], 'session')
        self.assertEqual(self.calls(timeout=0.3), [])

    def test_a_wake_that_finds_the_terminal_logged_out_says_so_and_stops_the_next(self):
        self.set_terminal(connecte=True)
        self.answer()
        self.set_terminal(connecte=False)                    # « OAuth session expired » after auth status said yes
        entry = self.queue()[f'{LOCAL}--Q11.json']
        log = self.parc_dir / 'reveils' / entry['journal']
        self.wait_end()
        log.write_text('OAuth session expired · Please run /login\n')
        self.m.tour_de_file()
        entry = self.queue()[f'{LOCAL}--Q11.json']
        self.assertEqual((entry['etat'], entry['raison']), ('echec', 'terminal'))
        self.assertIs(json.loads((self.parc_dir / 'terminal.json').read_text())['connecte'], False)
        self.set_terminal(connecte=True)                     # auth status says yes again, the wake said no
        self.assertEqual(self.answer(question='Q12', choix='1')['raison'], 'terminal')
        self.assertEqual(self.journal()[-1]['mode'], 'echec')

    def test_a_wake_that_ends_on_an_error_is_not_shown_as_sent(self):
        self.set_terminal(connecte=True, code=3)             # the session was deleted, or the model was refused
        self.answer()

        def ended():
            fin = time.time() + 20
            while time.time() < fin and any(p.poll() is None for p in self.m._lances.values()):
                time.sleep(0.05)
        ended()
        self.m.tour_de_file()
        # Q13: the first failure puts the answer back in the queue, never « envoyée »; the watcher wakes it once more.
        entry = self.queue()[f'{LOCAL}--Q11.json']
        self.assertEqual(entry['etat'], 'en_file')
        self.assertEqual(self.journal()[-1]['mode'], 'echec')
        self.assertTrue(self.journal()[-1]['encore'])
        self.m.tour_de_file()
        self.assertEqual(len(self.calls(at_least=2)), 2)
        ended()
        self.m.tour_de_file()
        entry = self.queue()[f'{LOCAL}--Q11.json']
        self.assertEqual((entry['etat'], entry['raison'], entry['code']), ('echec', 'reveil', 3))
        self.assertEqual(self.journal()[-1]['mode'], 'echec')
        page = [f for f in self.m.file_pour_la_page() if f['question'] == 'Q11'][0]
        self.assertEqual((page['etat'], page['raison']), ('echec', 'reveil'))



class Queue(Setup):
    def queued(self, age, etat='en_file'):
        (self.parc_dir / 'reponses-en-file').mkdir(exist_ok=True)
        e = {'session': LOCAL, 'question': 'Q11', 'choix': 'go', 'texte': 'Q11 go', 'etat': etat, 'clic': time.time() - age}
        (self.parc_dir / 'reponses-en-file' / f'{LOCAL}--Q11.json').write_text(json.dumps(e))

    def test_an_answer_waiting_24_hours_expires_and_the_page_is_told(self):
        self.ps = ps_line(11, APP_CLAUDE + ' --x', f'CLAUDE_CODE_HOST_SESSION_ID={LOCAL}')
        self.queued(24 * 3600 + 60)
        self.m.tour_de_file()
        self.assertEqual(self.queue()[f'{LOCAL}--Q11.json']['etat'], 'expiree')
        self.assertEqual(self.journal()[-1]['mode'], 'expiree')
        page = self.m.file_pour_la_page()
        self.assertEqual([(e['session'], e['question'], e['etat']) for e in page], [(LOCAL, 'Q11', 'expiree')])
        self.ps = ''
        self.m.tour_de_file()
        self.assertEqual(self.calls(timeout=0.3), [])         # an expired answer never goes

    def test_entries_are_forgotten_after_48_hours(self):
        self.queued(49 * 3600, etat='livree')
        self.m.tour_de_file()
        self.assertEqual(self.queue(), {})

    def test_a_question_settled_meanwhile_is_not_answered_again(self):
        self.queued(60)
        self.lines = [l for l in self.lines if l.get('question') != 'Q11']   # the PM answered in the session
        self.m.tour_de_file()
        self.assertEqual(self.queue()[f'{LOCAL}--Q11.json']['etat'], 'sans_objet')
        self.assertEqual(self.calls(timeout=0.3), [])

    def test_the_hook_takes_a_queued_answer_when_it_waits_on_that_question(self):
        self.switch(reponses_directes=True)
        self.queued(60)
        self.ps = ps_line(11, APP_CLAUDE + ' --x', f'CLAUDE_CODE_HOST_SESSION_ID={LOCAL}')
        mine, hook = socket.socketpair()
        self.addCleanup(mine.close)
        self.addCleanup(hook.close)
        att = self.m.Attente(mine, {'id': 'b' * 32, 'session_id': CLI, 'sessionId': LOCAL, 'numero': 'Q11', 'kind': 'go',
                                    'choix': ['go', 'pas encore'], 'limite': 600})
        self.m.AUTORISATIONS.attentes[att.id] = att
        self.m.tour_de_file()
        hook.settimeout(5)
        self.assertEqual(json.loads(hook.recv(4096).decode())['choix'], 'go')
        self.assertEqual(self.queue()[f'{LOCAL}--Q11.json']['etat'], 'livree')

    def test_attentes_gives_the_queue_to_the_page_even_switched_off(self):
        self.queued(60)
        out = self.m.attentes()
        self.assertFalse(out['actif'])
        self.assertEqual([(e['question'], e['choix'], e['etat']) for e in out['en_file']], [('Q11', 'go', 'en_file')])

    def test_the_tool_routes_without_an_id_to_the_wake(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.traiter({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': 'repondre', 'arguments': {'session': LOCAL, 'question': 'Q11', 'choix': 'go'}}})
        out = json.loads(json.loads(buf.getvalue())['result']['content'][0]['text'])
        self.assertEqual(out['mode'], 'reveil')


class InstallTodo(unittest.TestCase):
    def status(self, claude=None, connecte=True, started=True):
        root = pathlib.Path(tempfile.mkdtemp(prefix='cockpit-terminal-'))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        env = {'HOME': str(root / 'home'), 'MON_STUDIO_APP_SESSIONS': str(root / 'app')}
        trace, etat = root / 'trace.jsonl', root / 'etat.json'
        etat.write_text(json.dumps({'connecte': connecte}))
        if claude == 'fake':
            path = root / 'claude'
            path.write_text(FAKE_CLAUDE.format(python=sys.executable))
            path.chmod(0o755)
            env.update(MON_STUDIO_CLAUDE=str(path), FAUX_CLAUDE_TRACE=str(trace), FAUX_CLAUDE_ETAT=str(etat))
        with mock.patch.dict(os.environ, env):
            os.environ.pop('MON_STUDIO', None)
            if claude != 'fake':
                os.environ.pop('MON_STUDIO_CLAUDE', None)
            spec = importlib.util.spec_from_file_location('install_terminal_essai', INSTALL)
            i = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(i)
            i.INTERNAL.mkdir(parents=True)
            i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
            i.STATE.write_text(json.dumps({'version': i.plugin_version()}), encoding='utf-8')
            if started:   # the PM did the Terminal step of « Mise en route » once (2026-11-15)
                i.TERMINAL_NOTE.write_text(json.dumps({'connecte': False, 't': 0}), encoding='utf-8')
            with mock.patch.object(i.sys, 'platform', 'darwin'):
                s = i.status()
                again = i.status()
            calls = [json.loads(l) for l in trace.read_text().splitlines()] if trace.exists() else []
            return s, again, calls

    def test_before_the_terminal_step_nothing_is_checked_nor_asked(self):
        # 2026-11-15: the Terminal's login is a step of « Mise en route »; status never runs the check before it.
        s, again, calls = self.status('fake', connecte=False, started=False)
        self.assertIsNone(s['terminalLogin'])
        self.assertNotIn('terminal_login', s['todo'])
        self.assertEqual(calls, [])

    def test_missing_terminal_claude_asks_for_the_login(self):
        s, _, _ = self.status()
        self.assertEqual(s['terminalLogin'], 'absent')
        self.assertIn('terminal_login', s['todo'])

    def test_logged_out_asks_for_the_login_and_checks_again_each_time(self):
        s, again, calls = self.status('fake', connecte=False)
        self.assertEqual(s['terminalLogin'], 'deconnecte')
        self.assertIn('terminal_login', s['todo'])
        self.assertEqual(again['terminalLogin'], 'deconnecte')

    def test_logged_in_one_short_proof_then_kept(self):
        s, again, calls = self.status('fake', connecte=True)
        self.assertEqual(s['terminalLogin'], 'ok')
        self.assertNotIn('terminal_login', s['todo'])
        proofs = [c for c in calls if '-p' in c['argv']]
        self.assertEqual(len(proofs), 1)                      # the next status reads terminal.json
        self.assertEqual(again['terminalLogin'], 'ok')
        self.assertIn('--no-session-persistence', proofs[0]['argv'])
        self.assertEqual(proofs[0]['argv'][proofs[0]['argv'].index('--model') + 1], 'haiku')


class PageLines(unittest.TestCase):
    def run_page(self, payload):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    LINE = {'studio': 'Studio-Essai', 'session': 'Déploiement', 'cle': LOCAL, 'ouvrir': LOCAL, 'type': 'go', 'verbe': 'Go',
            'affiche_suite': 'Q11 · Studio : déployer en recette ?', 'question': 'Q11', 'choix': ['go', 'pas encore']}
    CLE = '|'.join([LOCAL, 'Q11', '', 'Q11 · Studio : déployer en recette ?'])

    def click(self, repondre=None, **more):
        payload = dict({'lignes': [dict(self.LINE)], 'cliquer': [['data-reveil', LOCAL]],
                        'attributs': {'data-question': 'Q11', 'data-choix': 'go', 'data-copier': 'Q11 go', 'data-ligne': self.CLE},
                        'attentes': {'actif': False, 'interrupteur': False, 'raison': '', 'attentes': []}}, **more)
        if repondre is not None:
            payload['repondre'] = repondre
        out = self.run_page(payload)
        return out, [r for r in out['tableau'].split('<tr') if 'Q11 ·' in r and '<td class="action">' in r][0]

    def test_asleep_the_line_says_the_session_resumes_without_opening_it(self):
        out, row = self.click({'mode': 'reveil', 'texte': 'Q11 go', 'clic': int(time.time() * 1000)})
        self.assertEqual([a for a in out['appels'] if a[0] == 'repondre'],
                         [['repondre', {'session': LOCAL, 'question': 'Q11', 'choix': 'go'}]])
        self.assertEqual([a for a in out['appels'] if a[0] == 'ouvrir'], [])
        self.assertIn('Envoi de « Q11 go » à la session…', row)   # not « envoyée » before the session has it
        self.assertNotIn('data-reveil', row)                  # no second answer while it resumes
        self.assertIn('>Ouvrir ↗</button>', row)            # the way into the session stays

    def test_alive_the_line_says_when_it_goes_with_the_click_time_and_keeps_the_buttons(self):
        clic = int(time.time() * 1000)
        out, row = self.click({'mode': 'file', 'texte': 'Q11 go', 'clic': clic})
        self.assertIn('Réponse prête : « Q11 go » partira dès que la session a fini son tour (cliquée à ', row)
        self.assertIn('data-reveil="' + LOCAL + '"', row)    # a new click replaces the answer
        self.assertEqual([a for a in out['appels'] if a[0] == 'ouvrir'], [])
        self.assertIn('>Ouvrir ↗</button>', row)

    def test_terminal_not_logged_in_copies_opens_and_says_why(self):
        out, row = self.click({'mode': 'copie', 'raison': 'terminal', 'texte': 'Q11 go'})
        self.assertEqual([a for a in out['appels'] if a[0] == 'ouvrir'], [['ouvrir', {'id': LOCAL, 'copier': 'Q11 go'}]])
        self.assertIn("Le Terminal n'est pas connecté : réponse copiée, colle-la dans la session", row)

    def test_a_refused_call_sends_nothing(self):
        out, row = self.click(repondreErreur='cancelled')
        self.assertEqual([a for a in out['appels'] if a[0] == 'ouvrir'], [])
        self.assertIn('refusée dans l', out['alerte'])

    def test_the_connector_word_on_each_line(self):
        now = int(time.time() * 1000)
        for etat, raison, dit, more in (('en_file', '', 'partira dès que la session a fini son tour', {}),
                                        ('expiree', '', 'Copier « Q11 go » et ouvrir la session', {}),
                                        ('echec', 'terminal', "Pas envoyée : le Terminal n'est pas connecté", {}),
                                        ('echec', 'reveil', "Pas envoyée : la session n'a pas pu reprendre", {}),
                                        ('livree', '', 'Envoi de « Q11 go » à la session…', {}),
                                        ('livree', '', 'Envoyée, la session reprend', {'recue': now}),
                                        ('livree', '', '« Q11 go » envoyée à ', {'recue': now, 'fini': True})):
            p = {'lignes': [dict(self.LINE)], 'attentes': {'actif': False, 'interrupteur': False, 'raison': '', 'attentes': [],
                 'en_file': [dict({'session': LOCAL, 'question': 'Q11', 'choix': 'go', 'texte': 'Q11 go', 'etat': etat,
                                   'raison': raison, 'clic': now, 'livree': now if etat == 'livree' else None,
                                   'fini': False}, **more)]}}
            row = [r for r in self.run_page(p)['tableau'].split('<tr') if 'Q11 ·' in r and '<td class="action">' in r][0]
            self.assertIn(dit, row, (etat, more))
            self.assertNotIn('veille', row)
        # Another session's queue, or another question, leaves the line alone.
        p['attentes']['en_file'][0]['question'] = 'Q12'
        row = [r for r in self.run_page(p)['tableau'].split('<tr') if 'Q11 ·' in r and '<td class="action">' in r][0]
        self.assertNotIn('Envoy', row)


if __name__ == '__main__':
    unittest.main()


class NothingBeforeTheGo(unittest.TestCase):
    """`status` runs before the PM's go: on a Mac where Mon Studio is not installed it must not run the Terminal's
    Claude (a paid call) nor write anything in ~/Mon Studio."""

    def test_status_before_install_runs_no_claude_and_writes_nothing(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix='cockpit-avant-go-'))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        trace, etat = root / 'trace.jsonl', root / 'etat.json'
        etat.write_text(json.dumps({'connecte': True}))
        path = root / 'claude'
        path.write_text(FAKE_CLAUDE.format(python=sys.executable))
        path.chmod(0o755)
        env = {'HOME': str(root / 'home'), 'MON_STUDIO_APP_SESSIONS': str(root / 'app'), 'MON_STUDIO_CLAUDE': str(path),
               'FAUX_CLAUDE_TRACE': str(trace), 'FAUX_CLAUDE_ETAT': str(etat)}
        with mock.patch.dict(os.environ, env):
            os.environ.pop('MON_STUDIO', None)
            spec = importlib.util.spec_from_file_location('install_avant_go', INSTALL)
            i = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(i)
            i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
            with mock.patch.object(i.sys, 'platform', 'darwin'):
                s = i.status()
                i.plan()
            self.assertIn('install', s['todo'])
            self.assertIsNone(s['terminalLogin'])
            self.assertNotIn('terminal_login', s['todo'])
            self.assertFalse(trace.exists(), 'the Terminal\'s Claude ran before the go')
            self.assertFalse(i.MON_STUDIO.exists(), '~/Mon Studio was created before the go')
