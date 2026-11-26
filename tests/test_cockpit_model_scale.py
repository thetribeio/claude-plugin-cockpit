"""Tests of the two hooks of the model scale: python3 -m unittest discover -s tests

- hooks/reglage_ouverture.py: on a session's first message only, Claude is told to set its own model and effort.
- hooks/bareme_modele.py: an Opus or Fable sub-agent needs « [modèle justifié] », a launched session needs a model and
  Fable needs « [fable demandé] ».

Both are silent without Mon Studio, once disabled, with their switch off, and while the PM keeps a personal copy of the
same hook in <config>/hooks/. Fake HOME, fake transcript."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPENING = ROOT / 'hooks' / 'reglage_ouverture.py'
SCALE = ROOT / 'hooks' / 'bareme_modele.py'
HOOKS = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))['hooks']
SESSION = 'mcp__ccd_session__start_session'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        self.parc = self.home / 'Mon Studio' / '.parc'
        self.parc.mkdir(parents=True)
        self.state({'page': 'x'})

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, state):
        (self.parc / 'cockpit.json').write_text(json.dumps(state), encoding='utf-8')

    def run_hook(self, hook, payload, extra_env=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('MON_STUDIO', 'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_HOST_SESSION_ID'))}
        env['HOME'] = str(self.home)
        env.update(extra_env or {})
        r = subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True, text=True,
                           env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def personal_copy(self, name, config=None):
        folder = (config or self.home / '.claude') / 'hooks'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text('# the PM\'s own copy\n')


class OpeningSetting(Base):
    def setUp(self):
        super().setUp()
        self.transcript = self.home / 't.jsonl'
        self.transcript.write_text(json.dumps({'type': 'user', 'message': {'content': 'bonjour'}}) + '\n')

    def prompt(self, **env):
        return self.run_hook(OPENING, {'session_id': 's1', 'transcript_path': str(self.transcript)}, env)

    def answered(self):
        with self.transcript.open('a') as f:
            f.write(json.dumps({'type': 'assistant', 'message': {'content': 'ok'}}) + '\n')

    def test_first_message_prints_then_silent(self):
        out = self.prompt()
        for word in ("Réglage d'ouverture", 'set_session_model', 'set_session_effort', 'Fable', 'Opus high',
                     'attends le oui du PM'):
            self.assertIn(word, out)
        self.assertNotIn('Eric', out)
        self.answered()
        self.assertEqual(self.prompt(), '')

    def test_missing_transcript_is_a_first_message(self):
        self.assertIn('Réglage', self.run_hook(OPENING, {'transcript_path': str(self.home / 'absent.jsonl')}))

    def test_silent_without_mon_studio_or_disabled(self):
        self.state({'page': 'x', 'disabled': True})
        self.assertEqual(self.prompt(), '')
        (self.parc / 'cockpit.json').unlink()
        self.assertEqual(self.prompt(), '')

    def test_switch_off(self):
        self.state({'page': 'x', 'reglage_ouverture': False})
        self.assertEqual(self.prompt(), '')

    def test_silent_while_the_pm_keeps_a_personal_copy(self):
        self.personal_copy('reglage_ouverture.py')
        self.assertEqual(self.prompt(), '')

    def test_personal_copy_found_through_claude_config_dir(self):
        config = self.home / 'autre-config'
        self.personal_copy('reglage_ouverture.py', config)
        self.assertEqual(self.prompt(CLAUDE_CONFIG_DIR=str(config)), '')
        self.assertNotEqual(self.prompt(), '')   # ~/.claude has no copy

    def test_bad_input_is_silent(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('MON_STUDIO')}
        env['HOME'] = str(self.home)
        r = subprocess.run([sys.executable, str(OPENING)], input='pas du json', capture_output=True, text=True,
                           env=env, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_declared_on_each_prompt(self):
        cmds = [h['command'] for g in HOOKS['UserPromptSubmit'] for h in g['hooks']]
        self.assertTrue(any('hooks/reglage_ouverture.py' in c and 'cockpit.json' in c for c in cmds))


class ScaleGuard(Base):
    def call(self, tool, tool_input, **env):
        return self.run_hook(SCALE, {'tool_name': tool, 'tool_input': tool_input}, env)

    def assertDenied(self, out, word):
        o = json.loads(out)['hookSpecificOutput']
        self.assertEqual((o['hookEventName'], o['permissionDecision']), ('PreToolUse', 'deny'))
        self.assertIn(word, o['permissionDecisionReason'])
        self.assertIn('Barème modèle et effort', o['permissionDecisionReason'])
        self.assertNotIn('Eric', o['permissionDecisionReason'])

    def test_opus_subagent_refused_then_accepted_with_marker(self):
        self.assertDenied(self.call('Agent', {'prompt': 'fais', 'model': 'opus'}), '[modèle justifié]')
        self.assertDenied(self.call('Agent', {'prompt': 'fais', 'model': 'fable'}), '[modèle justifié]')
        self.assertEqual(self.call('Agent', {'prompt': '[modèle justifié] livrable client', 'model': 'opus'}), '')

    def test_small_subagents_and_fork_pass(self):
        self.assertEqual(self.call('Agent', {'prompt': 'lis', 'model': 'haiku'}), '')
        self.assertEqual(self.call('Agent', {'prompt': 'lis'}), '')
        self.assertEqual(self.call('Agent', {'prompt': 'fais', 'model': 'opus', 'subagent_type': 'fork'}), '')

    def test_session_without_model_refused(self):
        self.assertDenied(self.call(SESSION, {'title': 'T', 'prompt': 'fais'}), 'claude-sonnet-5-5')

    def test_one_refusal_when_modele_lancement_refuses_already(self):
        # In a desktop app session with controle_modele on, hooks/modele_lancement.py refuses it: not twice.
        host = {'CLAUDE_CODE_HOST_SESSION_ID': 'local_00000000-0000-0000-0000-0000000000a1'}
        self.assertEqual(self.call(SESSION, {'title': 'T', 'prompt': 'fais'}, **host), '')
        self.state({'page': 'x', 'controle_modele': False})
        self.assertDenied(self.call(SESSION, {'title': 'T', 'prompt': 'fais'}, **host), 'model')

    def test_fable_session_refused_then_accepted_with_marker(self):
        self.assertDenied(self.call(SESSION, {'prompt': 'fais', 'model': 'claude-fable-5'}), '[fable demandé]')
        self.assertEqual(self.call(SESSION, {'prompt': '[fable demandé] fais', 'model': 'claude-fable-5'}), '')
        self.assertEqual(self.call(SESSION, {'prompt': 'fais', 'model': 'claude-sonnet-5-5'}), '')

    def test_offer_proposal_and_fork_pass(self):
        self.assertEqual(self.call(SESSION, {'initiation': 'offer', 'title': 'Une idée', 'prompt': 'fais'}), '')
        self.assertEqual(self.call(SESSION, {'proposal_id': 'task_ab12cd34'}), '')
        self.assertEqual(self.call(SESSION, {'context': 'fork', 'prompt': 'suite', 'model': 'fable'}), '')

    def test_any_start_session_tool(self):
        self.assertDenied(self.call('mcp__autre__start_session', {'prompt': 'fais'}), 'model')

    def test_silent_without_mon_studio_disabled_or_switch_off(self):
        refused = {'prompt': 'fais', 'model': 'opus'}
        self.state({'page': 'x', 'controle_bareme': False})
        self.assertEqual(self.call('Agent', refused), '')
        self.state({'page': 'x', 'disabled': True})
        self.assertEqual(self.call('Agent', refused), '')
        (self.parc / 'cockpit.json').unlink()
        self.assertEqual(self.call('Agent', refused), '')

    def test_silent_while_the_pm_keeps_a_personal_copy(self):
        self.personal_copy('bareme_modele.py')
        self.assertEqual(self.call('Agent', {'prompt': 'fais', 'model': 'opus'}), '')

    def test_declared_before_each_launch(self):
        groups = [g for g in HOOKS['PreToolUse'] if any('hooks/bareme_modele.py' in h['command'] for h in g['hooks'])]
        self.assertEqual(len(groups), 1)
        for tool in ('Agent', SESSION):
            self.assertTrue(re.fullmatch(groups[0]['matcher'], tool), tool)


if __name__ == '__main__':
    unittest.main()
