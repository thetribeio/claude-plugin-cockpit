"""Tests: a tool that runs long is not an authorization: python3 -m unittest discover -s tests

PM, 2026-11-26: two sessions running a 10-minute test suite read « Session arrêtée sur une autorisation : à rouvrir »
on the board. A tool without result after 3 minutes of silence was taken for a tool waiting for consent. Now the
PermissionRequest hook (hooks/autorisation.py) leaves a trace of every request, switch on or off; the board calls a
pending tool an authorization only when its request was traced since the tool was called. Untraced, the session works;
after OUTIL_LONG_S without a move, it is stopped in the middle of its work, never « une autorisation »."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc_outil_long', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
HOOK = ROOT / 'hooks' / 'autorisation.py'
NOW = time.time()


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def transcript(folder, cli, silent_minutes):
    entries = [{'type': 'user', 'timestamp': at(12), 'origin': {'kind': 'human'}, 'message': {'content': 'Lance les tests.'}},
               {'type': 'assistant', 'timestamp': at(11), 'message': {'id': 'm1', 'stop_reason': 'tool_use', 'content': [
                   {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'python3 -m unittest discover'}}]}}]
    path = pathlib.Path(folder) / f'{cli}.jsonl'
    path.write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
    os.utime(path, (NOW - silent_minutes * 60, NOW - silent_minutes * 60))
    return path


def trace(cli, minutes_ago):
    d = parc.INTERNE / 'demandes-autorisation'
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{cli}.json').write_text(json.dumps({'t': NOW - minutes_ago * 60, 'outil': 'Bash'}))


class LongTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_tool_running_for_ten_minutes_works(self):
        r = parc._analyser(str(transcript(self.tmp.name, 'cli-tests', 10)), NOW)
        self.assertEqual(r['etat'], 'travaille')
        self.assertNotIn('attente', r)

    def test_a_traced_request_is_an_authorization(self):
        trace('cli-ask', 10)
        r = parc._analyser(str(transcript(self.tmp.name, 'cli-ask', 10)), NOW)
        self.assertEqual(r['etat'], 'suspens')
        self.assertEqual(r['attente']['outil'], 'Bash')

    def test_a_trace_older_than_the_tool_is_not_its_request(self):
        trace('cli-old', 60)
        r = parc._analyser(str(transcript(self.tmp.name, 'cli-old', 10)), NOW)
        self.assertEqual(r['etat'], 'travaille')

    def test_silent_past_the_limit_it_is_stopped_without_authorization(self):
        r = parc._analyser(str(transcript(self.tmp.name, 'cli-dead', parc.OUTIL_LONG_S / 60 + 5)), NOW)
        self.assertEqual(r['etat'], 'suspens')
        self.assertNotIn('attente', r)


class HookTrace(unittest.TestCase):
    def test_the_hook_traces_the_request_switch_off(self):
        with tempfile.TemporaryDirectory() as ms:
            env = dict(os.environ, MON_STUDIO=ms)
            demande = {'session_id': 'cli-hook', 'tool_name': 'Bash', 'tool_input': {'command': 'git push'}}
            out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(demande), capture_output=True, text=True,
                                 env=env, timeout=20)
            self.assertEqual(out.stdout, '')
            t = json.loads((pathlib.Path(ms) / '.parc' / 'demandes-autorisation' / 'cli-hook.json').read_text())
            self.assertEqual(t['outil'], 'Bash')
            self.assertNotIn('git push', json.dumps(t))   # nothing of what the tool would do

    def test_a_strange_session_id_writes_nothing(self):
        with tempfile.TemporaryDirectory() as ms:
            env = dict(os.environ, MON_STUDIO=ms)
            subprocess.run([sys.executable, str(HOOK)], input=json.dumps({'session_id': '../x', 'tool_name': 'Bash'}),
                           capture_output=True, text=True, env=env, timeout=20)
            self.assertFalse((pathlib.Path(ms) / '.parc' / 'demandes-autorisation').exists())


if __name__ == '__main__':
    unittest.main()
