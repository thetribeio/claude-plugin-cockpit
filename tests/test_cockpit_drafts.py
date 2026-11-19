"""Tests: drafts a session left and the PM never sent (Q39, 2026-11-07): python3 -m unittest discover -s tests

hooks/brouillons.py notes each Gmail or Slack draft a session creates or updates (PostToolUse hook, no LLM) in
~/Mon Studio/.parc/brouillons.json and forgets a deleted one; its catch-up reads the transcripts of the last 30 days.
The morning task checks in Gmail which are still drafts and writes them in matin.json (`brouillons`); matin.py
validates them and the Today tab lists them, never the board.

Every file lives in a temporary folder; the tool results have the shape of the real connectors' results."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import datetime as dt
import io
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import test_cockpit_matin as tm
from test_cockpit_matin import MatinBase, iso, item
from test_cockpit_projets import MONDAY, ASKER

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks' / 'brouillons.py'
HOOKS = ROOT / 'hooks' / 'hooks.json'
PROMPT = ROOT / 'skills' / 'mon-studio' / 'assets' / 'consigne-point-du-matin.md'
INSTALL = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py'
GMAIL = 'mcp__0000aaaa-0000-0000-0000-000000000000__'
SLACK = 'mcp__1111bbbb-0000-0000-0000-000000000000__'
LOCAL = 'local_00000000-0000-0000-0000-0000000000f1'
VIEW = 'https://mail.google.com/mail/?authuser=pm@example.org#all?compose=thread-f:1%2Bmsg-a:r-123'


def gmail_result(draft='r-123', message='1a00', view=VIEW):
    return json.dumps({'id': draft, 'messageId': message, 'threadId': message, 'viewUrl': view})


def slack_result(draft='Dr01', channel='C0TEST', name='projet-interne', dm=False):
    return [{'type': 'text', 'text': json.dumps({
        'channel_link': f'https://example.slack.com/archives/{channel}', 'draft_id': draft,
        'channel_info': {'channel_id': channel, 'name': name, 'is_dm': dm},
        'result': 'Draft created. The user can review, edit, and send it from Drafts & Sent in Slack.'})}]


def load_hook():
    spec = importlib.util.spec_from_file_location('brouillons_essai', HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class HookBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.mon_studio = self.root / 'Mon Studio'
        (self.mon_studio / '.parc').mkdir(parents=True)
        self.env = dict(os.environ, MON_STUDIO=str(self.mon_studio), CLAUDE_CODE_HOST_SESSION_ID=LOCAL)
        self.file = self.mon_studio / '.parc' / 'brouillons.json'

    def run_hook(self, tool, tool_input, response, session='cli-1', cwd='/S/Alpha', stdin=None):
        data = stdin if stdin is not None else json.dumps({
            'session_id': session, 'cwd': cwd, 'hook_event_name': 'PostToolUse', 'tool_name': tool,
            'tool_input': tool_input, 'tool_response': response})
        t = time.monotonic()
        r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))
        return time.monotonic() - t

    def drafts(self):
        if not self.file.exists():
            return {}
        return {e['cle']: e for e in json.loads(self.file.read_text(encoding='utf-8'))['brouillons']}


class Hook(HookBase):
    def test_a_gmail_draft_is_noted_with_its_link_session_and_folder(self):
        took = self.run_hook(GMAIL + 'create_draft', {'to': ['a@example.org', 'b@example.org'], 'cc': [],
                                                      'subject': 'Compte rendu du comité', 'body': 'Bonjour'}, gmail_result())
        self.assertLess(took, 2, 'the hook never slows a session')
        e = self.drafts()['gmail:r-123']
        self.assertEqual((e['outil'], e['brouillon'], e['message'], e['lien']), ('gmail', 'r-123', '1a00', VIEW))
        self.assertEqual((e['destinataire'], e['objet']), ('a@example.org (+1)', 'Compte rendu du comité'))
        self.assertEqual((e['session'], e['session_locale'], e['dossier']), ('cli-1', LOCAL, '/S/Alpha'))
        self.assertTrue(e['cree_le'] and e['maj_le'])

    def test_an_update_keeps_the_draft_and_refreshes_its_link_and_a_delete_forgets_it(self):
        self.run_hook(GMAIL + 'create_draft', {'to': ['a@example.org'], 'subject': 'Devis'}, gmail_result())
        first = self.drafts()['gmail:r-123']
        new_view = VIEW.replace('thread-f:1', 'thread-f:2')
        self.run_hook(GMAIL + 'update_draft', {'draftId': 'r-123', 'htmlBody': '<p>x</p>'},
                      [{'type': 'text', 'text': gmail_result(message='1a01', view=new_view)}], session='cli-2')
        e = self.drafts()['gmail:r-123']
        self.assertEqual((e['lien'], e['message'], e['objet'], e['session'], e['cree_le']),
                         (new_view, '1a01', 'Devis', 'cli-1', first['cree_le']))
        self.run_hook(GMAIL + 'delete_draft', {'draftId': 'r-123'}, 'Draft deleted.')
        self.assertEqual(self.drafts(), {})

    def test_without_a_view_link_the_link_is_built_from_the_message(self):
        self.run_hook(GMAIL + 'create_draft', {'to': ['a@example.org'], 'subject': 'S'}, json.dumps({'id': 'r-9', 'messageId': '1abc'}))
        self.assertEqual(self.drafts()['gmail:r-9']['lien'], 'https://mail.google.com/mail/u/0/#drafts?compose=1abc')

    def test_a_slack_draft_keeps_one_per_conversation(self):
        self.run_hook(SLACK + 'slack_send_message_draft', {'channel_id': 'C0TEST', 'message': '<@U01> pour lundi, <https://x.org|le doc>'}, slack_result())
        e = self.drafts()['slack:C0TEST']
        self.assertEqual((e['outil'], e['destinataire'], e['objet'], e['lien']),
                         ('slack', '#projet-interne', '@… pour lundi, le doc', 'https://example.slack.com/archives/C0TEST'))
        self.run_hook(SLACK + 'slack_send_message_draft', {'channel_id': 'C0TEST', 'message': 'Autre', 'thread_ts': '1793.0001'},
                      slack_result(draft='Dr02'))
        t = self.drafts()['slack:C0TEST:1793.0001']
        self.assertEqual(t['lien'], 'https://example.slack.com/archives/C0TEST/p17930001?thread_ts=1793.0001&cid=C0TEST')
        self.run_hook(SLACK + 'slack_send_message_draft', {'channel_id': 'C0TEST', 'message': 'Nouveau'}, slack_result(draft='Dr03'))
        d = self.drafts()
        self.assertEqual(len(d), 2)
        self.assertEqual((d['slack:C0TEST']['brouillon'], d['slack:C0TEST']['objet']), ('Dr03', 'Nouveau'))
        self.run_hook(SLACK + 'slack_send_message_draft', {'channel_id': 'D0X', 'message': 'Salut'}, slack_result(channel='D0X', name='U0', dm=True))
        self.assertEqual(self.drafts()['slack:D0X']['destinataire'], 'message direct')

    def test_errors_other_tools_and_garbage_note_nothing_and_print_nothing(self):
        self.run_hook(GMAIL + 'create_draft', {'to': ['a@example.org']}, 'Error: quota exceeded')
        self.run_hook(GMAIL + 'send_message', {'to': ['a@example.org']}, gmail_result())
        self.run_hook('mcp__x__list_drafts', {}, gmail_result())
        self.run_hook('', {}, None, stdin='{oops')
        self.run_hook('', {}, None, stdin='')
        self.assertFalse(self.file.exists())

    def test_old_entries_leave_and_a_corrupt_file_starts_again(self):
        old = {'cle': 'gmail:r-old', 'outil': 'gmail', 'maj_le': '2026-01-01T10:00:00+01:00', 'cree_le': '2026-01-01T10:00:00+01:00'}
        self.file.write_text(json.dumps({'version': 1, 'brouillons': [old]}), encoding='utf-8')
        self.run_hook(GMAIL + 'create_draft', {'to': ['a@example.org'], 'subject': 'S'}, gmail_result())
        self.assertEqual(list(self.drafts()), ['gmail:r-123'])
        self.file.write_text('{oops', encoding='utf-8')
        self.run_hook(GMAIL + 'create_draft', {'to': ['a@example.org'], 'subject': 'S'}, gmail_result(draft='r-5'))
        self.assertEqual(list(self.drafts()), ['gmail:r-5'])

    @unittest.skipIf(sys.platform.startswith('win'), 'flock')
    def test_a_held_lock_gives_up_quickly_without_writing(self):
        import fcntl
        lock = self.mon_studio / '.parc' / 'brouillons.json.lock'
        fd = os.open(lock, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            took = self.run_hook(GMAIL + 'create_draft', {'to': ['a@example.org'], 'subject': 'S'}, gmail_result())
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.assertLess(took, 4)
        self.assertFalse(self.file.exists())

    def test_the_hook_is_declared_on_the_draft_tools_only_and_silent_when_disabled(self):
        hooks = json.loads(HOOKS.read_text(encoding='utf-8'))['hooks']['PostToolUse']
        entry = next(h for h in hooks if 'brouillons.py' in h['hooks'][0]['command'])
        for name in ('create_draft', 'update_draft', 'delete_draft'):
            self.assertTrue(re.fullmatch(entry['matcher'], GMAIL + name), name)
        self.assertTrue(re.fullmatch(entry['matcher'], SLACK + 'slack_send_message_draft'))
        for name in (GMAIL + 'send_message', GMAIL + 'get_draft', SLACK + 'slack_send_message', 'Bash', 'create_draft'):
            self.assertFalse(re.fullmatch(entry['matcher'], name), name)
        cmd = entry['hooks'][0]['command']
        self.assertIn('[ -f "$HOME/Mon Studio/.parc/cockpit.json" ]', cmd)
        self.assertIn('! grep -q \'"disabled": true\'', cmd)
        self.assertTrue(cmd.endswith('>/dev/null 2>&1 || true'))
        self.assertLessEqual(entry['hooks'][0]['timeout'], 5)


class CatchUp(HookBase):
    def setUp(self):
        super().setUp()
        self.transcripts = self.root / 'projects'
        self.app = self.root / 'app'
        (self.app / 'a' / 'b').mkdir(parents=True)
        (self.app / 'a' / 'b' / f'{LOCAL}.json').write_text(json.dumps({'sessionId': LOCAL, 'cliSessionId': 'cli-1'}), encoding='utf-8')
        self.env.pop('CLAUDE_CODE_HOST_SESSION_ID')
        self.env.update(MON_STUDIO_TRANSCRIPTS=str(self.transcripts), MON_STUDIO_APP_SESSIONS=str(self.app))
        self.now = time.time()
        mac = mock.patch('sys.platform', 'darwin')  # these tests assume macOS: say so, whatever runs them
        mac.start()
        self.addCleanup(mac.stop)

    def stamp(self, days_ago):
        return dt.datetime.fromtimestamp(self.now - days_ago * 86400, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    def transcript(self, path, session, calls):
        """calls: [(id, days ago, tool, input, result, is_error)] as the CLI writes them: a tool_use line, a tool_result line."""
        lines = []
        for i, days, tool, inp, res, err in calls:
            lines.append({'type': 'assistant', 'timestamp': self.stamp(days), 'sessionId': session, 'cwd': '/S/Alpha',
                          'message': {'content': [{'type': 'tool_use', 'id': i, 'name': tool, 'input': inp}]}})
            lines.append({'type': 'user', 'timestamp': self.stamp(days), 'sessionId': session, 'cwd': '/S/Alpha',
                          'message': {'content': [{'type': 'tool_result', 'tool_use_id': i, 'content': res, 'is_error': err}]}})
        p = self.transcripts / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('\n'.join(json.dumps(l) for l in lines) + '\n', encoding='utf-8')

    def catch_up(self, *args):
        return subprocess.run([sys.executable, str(HOOK), 'rattrapage', *args], capture_output=True, text=True, env=self.env, timeout=30)

    def test_finds_the_drafts_still_there_once_each(self):
        calls = [('t1', 9, GMAIL + 'create_draft', {'to': ['a@example.org'], 'subject': 'Relevé'}, gmail_result('r-1', '1a1'), False),
                 ('t2', 8, GMAIL + 'create_draft', {'to': ['b@example.org'], 'subject': 'Supprimé'}, gmail_result('r-2', '1a2'), False),
                 ('t3', 8, GMAIL + 'delete_draft', {'draftId': 'r-2'}, 'ok', False),
                 ('t4', 7, GMAIL + 'create_draft', {'to': ['c@example.org'], 'subject': 'Raté'}, 'Error', True),
                 ('t5', 40, GMAIL + 'create_draft', {'to': ['d@example.org'], 'subject': 'Trop vieux'}, gmail_result('r-5', '1a5'), False),
                 ('t6', 2, SLACK + 'slack_send_message_draft', {'channel_id': 'C0TEST', 'message': 'Pour lundi'}, slack_result(), False)]
        self.transcript('-S-Alpha/cli-1.jsonl', 'cli-1', calls)
        # A forked session copies its parent's lines: the same calls, noted once, with the first session.
        self.transcript('-S-Alpha/cli-9.jsonl', 'cli-1', calls[:1])
        self.transcript('-S-Alpha/cli-1/subagents/agent-a1.jsonl', 'cli-1',
                        [('t7', 1, GMAIL + 'create_draft', {'to': ['e@example.org'], 'subject': 'Sous-agent'}, gmail_result('r-7', '1a7'), False)])
        r = self.catch_up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('notés : 3 (2 gmail, 1 slack)', r.stdout)
        d = self.drafts()
        self.assertEqual(sorted(d), ['gmail:r-1', 'gmail:r-7', 'slack:C0TEST'])
        self.assertEqual((d['gmail:r-1']['session'], d['gmail:r-1']['session_locale'], d['gmail:r-1']['objet']), ('cli-1', LOCAL, 'Relevé'))
        self.assertEqual(d['gmail:r-1']['cree_le'][:10], dt.datetime.fromtimestamp(self.now - 9 * 86400).date().isoformat())

    def test_keeps_what_the_hook_noted_and_forgets_what_was_deleted_since(self):
        noted = {'cle': 'gmail:r-1', 'outil': 'gmail', 'objet': 'Du hook', 'maj_le': iso(self.now), 'cree_le': iso(self.now)}
        gone = dict(noted, cle='gmail:r-2', objet='Effacé')
        self.file.write_text(json.dumps({'version': 1, 'brouillons': [noted, gone]}), encoding='utf-8')
        self.transcript('-S-Alpha/cli-1.jsonl', 'cli-1', [
            ('t1', 3, GMAIL + 'create_draft', {'to': ['a@example.org'], 'subject': 'Relevé'}, gmail_result('r-1', '1a1'), False),
            ('t2', 1, GMAIL + 'delete_draft', {'draftId': 'r-2'}, 'ok', False)])
        self.assertEqual(self.catch_up().returncode, 0)
        d = self.drafts()
        self.assertEqual(list(d), ['gmail:r-1'])
        self.assertEqual(d['gmail:r-1']['objet'], 'Du hook')

    def test_nothing_found_still_writes_the_file(self):
        r = self.catch_up()
        self.assertIn('notés : 0 (aucun)', r.stdout)
        self.assertEqual(self.drafts(), {})
        self.assertTrue(self.file.exists())

    def test_install_asks_for_it_once_and_runs_it(self):
        home = self.root / 'home'
        with mock.patch.dict(os.environ, {'HOME': str(home), 'MON_STUDIO_TRANSCRIPTS': str(self.transcripts),
                                          'MON_STUDIO_APP_SESSIONS': str(self.app)}):
            os.environ.pop('MON_STUDIO', None)
            spec = importlib.util.spec_from_file_location('install_brouillons_essai', INSTALL)
            i = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(i)
            i.INTERNAL.mkdir(parents=True)
            i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
            i.STATE.write_text(json.dumps({'version': i.plugin_version()}), encoding='utf-8')
            self.assertIn('drafts_catch_up', i.status()['todo'])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(i.main(['brouillons-rattrapage']), 0)
            self.assertIn('notés : 0', out.getvalue())
            self.assertTrue((i.INTERNAL / 'brouillons.json').exists())
            self.assertNotIn('drafts_catch_up', i.status()['todo'])
            self.assertTrue(i.status()['draftsNoted'])


def draft(i, **extra):
    return dict({'cle': f'gmail:r-{i}', 'projet': 'Alpha', 'outil': 'gmail', 'destinataire': f'p{i}@example.org',
                 'objet': f'Objet {i}', 'depuis': '2026-10-30', 'lien': f'https://mail.google.com/mail/u/0/#drafts?compose={i}'}, **extra)


class Reading(MatinBase):
    def test_drafts_are_read_validated_and_capped_and_their_absence_is_an_empty_list(self):
        self.write()
        self.assertEqual(self.m.pour_la_page(MONDAY)['brouillons'], [])
        good = [draft(i) for i in range(12)]
        slack = draft('s', outil='slack', cle='slack:C0', lien='https://example.slack.com/archives/C0')
        bad = [draft('x', lien='https://example.org/x'), draft('y', outil='slack'), draft('z', outil='teams'),
               draft('w', lien=''), {'cle': '', 'outil': 'gmail'}, 'pas un objet', draft('d', depuis='hier')]
        self.write(brouillons=[slack] + bad + good)
        b = self.m.pour_la_page(MONDAY)['brouillons']
        self.assertEqual(len(b), self.m.PLAFOND_BROUILLONS)
        self.assertEqual(b[0], slack)
        self.assertEqual(b[1]['depuis'], '', 'a date that is not AAAA-MM-JJ is dropped, not the draft')
        self.assertEqual([x['cle'] for x in b[2:]], [f'gmail:r-{i}' for i in range(8)])

    def test_fait_hides_a_draft_and_a_done_item_for_good(self):
        self.write(a_traiter=[item(1)], brouillons=[draft(1), draft(2)])
        self.m.fait('k1', MONDAY)
        self.assertEqual(self.m.fait('gmail:r-1', MONDAY), {'fait': 'gmail:r-1'})
        with self.assertRaises(ValueError):
            self.m.fait('gmail:r-1', MONDAY)
        p = self.m.pour_la_page(MONDAY)
        self.assertEqual(([x['cle'] for x in p['brouillons']], p['a_traiter']), (['gmail:r-2'], []))
        # The next day the morning task writes it again: it stays hidden.
        tuesday = MONDAY + 86400
        self.write(genere_le=iso(tuesday), a_traiter=[item(1)], brouillons=[draft(1), draft(2)])
        p = self.m.pour_la_page(tuesday)
        self.assertEqual([x['cle'] for x in p['brouillons']], ['gmail:r-2'])
        self.assertEqual(p['a_traiter'], [], 'a done item does not come back the next day (PM, 2026-11-09)')

    def test_the_cli_line_counts_drafts(self):
        self.write(genere_le=iso(time.time()), brouillons=[draft(1)])
        env = dict(os.environ, MON_STUDIO=str(self.mon_studio))
        r = subprocess.run([sys.executable, str(ROOT / 'skills' / 'mon-studio' / 'scripts' / 'matin.py')], capture_output=True, text=True, env=env)
        self.assertIn('brouillons pas envoyés 1', r.stdout)


class Sessions(MatinBase):
    def test_a_draft_carries_its_live_session_from_the_noted_file(self):
        self.write(brouillons=[draft(1), draft(2), draft(3), draft(4)])
        notes = [{'cle': 'gmail:r-1', 'session': 'x', 'session_locale': ASKER},
                 {'cle': 'gmail:r-2', 'session': 'cli-ask', 'session_locale': ''},
                 {'cle': 'gmail:r-3', 'session': 'inconnue', 'session_locale': 'local_00000000-0000-0000-0000-0000000000ff'}]
        (self.mon_studio / '.parc' / 'brouillons.json').write_text(json.dumps({'brouillons': notes}), encoding='utf-8')
        for m in self.metas:
            if m['id'] == ASKER:
                m['cli'] = 'cli-ask'
        b = self.p.matin_pour_la_page(MONDAY, self.metas, self.compute())['brouillons']
        self.assertEqual([x['session'] for x in b], [ASKER, ASKER, None, None])
        for m in self.metas:
            m['archivee'] = True
        b = self.p.matin_pour_la_page(MONDAY, self.metas, self.compute())['brouillons']
        self.assertEqual([x['session'] for x in b], [None] * 4, 'an archived session is not offered')


class DraftConnector(MatinBase):
    # The helpers of the matin tests, without running their tests again.
    connector, call = tm.Connector.connector, tm.Connector.call

    def test_clore_with_matin_marks_a_draft_seen(self):
        m = self.connector()
        self.write(genere_le=iso(time.time()), brouillons=[draft(1)])
        ok, again = self.call(m, ('clore', {'cle': 'gmail:r-1', 'matin': True}), ('clore', {'cle': 'gmail:r-1', 'matin': True}))
        self.assertEqual(json.loads(ok['result']['content'][0]['text']), {'fait': 'gmail:r-1'})
        self.assertTrue(again['result']['isError'])
        self.assertEqual(m.lignes()['matin']['brouillons'], [])


class DraftPage(unittest.TestCase):
    run_page = tm.Page.run_page
    MATIN = dict(tm.Page.MATIN, brouillons=[
        dict(draft(1, objet='Compte rendu <comité>'), session=ASKER),
        dict(draft('s', outil='slack', cle='slack:C0', destinataire='#projet', objet='Pour lundi', projet='',
                   lien='https://example.slack.com/archives/C0'), session=None)])

    def test_the_today_tab_lists_them_at_the_bottom_with_their_buttons(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes', 'clore'])
        h = out['matin']
        self.assertIn('<h3 class="discret">Brouillons pas envoyés</h3>', h)
        self.assertGreater(h.index('Brouillons pas envoyés'), h.index('Préparer demain'))
        self.assertIn('Mail à p1@example.org : Compte rendu &lt;comité&gt;', h)
        self.assertIn('depuis le 30/10 · Alpha', h)
        self.assertIn('href="https://mail.google.com/mail/u/0/#drafts?compose=1" target="_blank" rel="noopener noreferrer">Ouvrir le brouillon ↗</a>', h)
        self.assertIn(f'data-sid="{ASKER}"', h)
        self.assertEqual(h.count('Ouvrir la session ↗'), 1, 'only a draft whose session is known')
        self.assertIn('Slack #projet : Pour lundi', h)
        self.assertIn('data-matin-fait="gmail:r-1"', h)
        self.assertIn('data-matin-fait="gmail:r-1" title="C\'est fait : ne plus l\'afficher">Fait</button>', h)
        # « Vu » belongs to the « Pour info » entries only; a draft keeps « Fait ».
        self.assertNotIn('>Vu</button>', h[h.index('Brouillons pas envoyés'):])

    def test_never_on_the_board_and_never_counted(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes', 'clore'])
        for zone in ('tableau', 'projets', 'studios', 'ongletMatin'):
            self.assertNotIn('brouillon', out[zone].lower(), zone)
            self.assertNotIn('Compte rendu', out[zone], zone)
        self.assertIn('<span class="pastille">3</span>', out['ongletMatin'])
        self.assertIn('Journée lourde · 3 à traiter', out['matin'])
        out = self.run_page(matin=dict(self.MATIN, a_traiter=[]), outils=['lignes', 'clore'])
        self.assertNotIn('pastille', out['ongletMatin'])

    def test_fait_calls_clore_with_matin_and_the_draft_leaves(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes', 'clore'], cliquer=[['data-matin-fait', 'gmail:r-1']])
        self.assertIn(['clore', {'cle': 'gmail:r-1', 'matin': True}], out['appels'])
        self.assertNotIn('data-matin-fait="gmail:r-1"', out['matin'])
        self.assertIn('Slack #projet', out['matin'])

    def test_without_the_connector_tools_only_the_link_stays(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes'])
        self.assertIn('Ouvrir le brouillon ↗', out['matin'])
        self.assertNotIn('>Fait</button>', out['matin'])

    def test_a_draft_without_an_https_link_is_not_shown(self):
        out = self.run_page(matin=dict(self.MATIN, brouillons=[draft(1, lien='javascript:alert(1)')]))
        self.assertNotIn('Brouillons pas envoyés', out['matin'])
        self.assertNotIn('javascript:', out['matin'])


class Prompt(unittest.TestCase):
    def test_the_morning_prompt_checks_drafts_in_gmail_and_never_touches_them(self):
        c = PROMPT.read_text(encoding='utf-8')
        # 2026-11-10: preparer gives the drafts to check; the task reads no file.
        self.assertNotIn('brouillons.json', c)
        self.assertIn("`brouillons` : ceux de la sortie de `preparer` qui n'ont pas été envoyés", c)
        self.assertIn('`{"cle", "projet", "outil", "destinataire", "objet", "depuis", "lien"}`', c)
        self.assertIn('une seule lecture chacun', c)
        self.assertIn('une seule recherche par canal', c)
        self.assertIn('Introuvable ou plus marqué brouillon (envoyé ou supprimé) : il ne compte plus', c)
        self.assertIn('`viewUrl`', c)
        self.assertIn("tu n'en modifies ni n'en supprimes aucun", c)
        self.assertNotIn('—', c)
        self.assertLess(len(c.split()), 1500, 'the prompt stays short')


if __name__ == '__main__':
    unittest.main()
