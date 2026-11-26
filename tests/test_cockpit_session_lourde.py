"""Tests of the heavy-session hook: python3 -m unittest discover -s tests

Past the threshold (300 000 tokens by default, PM 2026-11-03), the session is told once to propose a fresh session,
then reminded every 100 000 tokens more, never at every message. Fake transcript, fake Mon Studio."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / 'hooks' / 'session_lourde.py'
HOOKS = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))['hooks']


class HeavySession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.ms = root / 'Mon Studio'
        (self.ms / '.parc').mkdir(parents=True)
        (self.ms / '.parc' / 'cockpit.json').write_text('{}')
        self.transcript = root / 't.jsonl'
        self.transcript.write_text('')

    def tearDown(self):
        self.tmp.cleanup()

    def turn(self, tokens, sidechain=False):
        """One more exchange whose last assistant message carries this context size (split as the API does)."""
        with self.transcript.open('a') as f:
            f.write(json.dumps({'type': 'user', 'message': {'content': 'suite'}}) + '\n')
            f.write(json.dumps({'type': 'assistant', 'isSidechain': sidechain, 'message': {'usage': {
                'input_tokens': 10, 'cache_read_input_tokens': tokens - 1010, 'cache_creation_input_tokens': 1000,
                'output_tokens': 500}}}) + '\n')

    def prompt(self, sid='s1'):
        env = {k: v for k, v in os.environ.items() if not k.startswith('MON_STUDIO')}
        env['MON_STUDIO'] = str(self.ms)
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({'session_id': sid, 'transcript_path': str(self.transcript), 'cwd': str(self.ms)}),
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_below_crossing_same_step_next_step(self):
        self.turn(250000)
        self.assertEqual(self.prompt(), '')                       # under the threshold: nothing
        self.turn(310000)
        out = self.prompt()
        self.assertIn('Cette session pèse environ 310', out)     # crossing: the instruction
        self.assertIn('hand_off_to_session', out)
        self.assertIn('detach_session', out)                     # a top-level session is launched, then detached
        self.assertIn('prompt complet à', out)                    # the paste prompt only as a fallback
        self.turn(380000)
        self.assertEqual(self.prompt(), '')                       # under +100 000: nothing
        self.turn(418000)
        self.assertIn('environ 420', self.prompt())               # next step: the reminder
        self.assertEqual(self.prompt(), '')                       # never at every message

    def test_threshold_from_cockpit_json_and_per_session(self):
        (self.ms / '.parc' / 'cockpit.json').write_text(json.dumps({'decoupe_seuil_tokens': 400000}))
        self.turn(350000)
        self.assertEqual(self.prompt(), '')
        self.turn(420000)
        self.assertNotEqual(self.prompt('s1'), '')
        self.assertNotEqual(self.prompt('s2'), '')                # another session has its own step

    def test_a_summary_starts_again(self):
        self.turn(320000)
        self.assertNotEqual(self.prompt(), '')
        self.turn(60000)                                          # after a context summary
        self.assertEqual(self.prompt(), '')
        self.turn(330000)
        self.assertNotEqual(self.prompt(), '')

    def test_subagent_usage_does_not_count(self):
        self.turn(100000)
        self.turn(900000, sidechain=True)
        self.assertEqual(self.prompt(), '')

    def test_silent_without_mon_studio(self):
        (self.ms / '.parc' / 'cockpit.json').unlink()
        self.turn(900000)
        self.assertEqual(self.prompt(), '')

    def test_declared_on_each_prompt(self):
        cmds = [h['command'] for g in HOOKS['UserPromptSubmit'] for h in g['hooks']]
        self.assertTrue(any('hooks/session_lourde.py' in c and 'cockpit.json' in c for c in cmds))


if __name__ == '__main__':
    unittest.main()
