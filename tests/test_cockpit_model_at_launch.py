"""A session or sub-agent launched without a model is refused once, with the price list (hooks/modele_lancement.py)."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / 'hooks' / 'modele_lancement.py'
SESSION = 'mcp__ccd_session__start_session'
HOST = 'local_00000000-0000-0000-0000-0000000000a1'


class ModelAtLaunch(unittest.TestCase):
    def run_hook(self, payload, state=None, raw=None, host=HOST):
        with tempfile.TemporaryDirectory() as home:
            if state is not None:
                parc = Path(home) / 'Mon Studio' / '.parc'
                parc.mkdir(parents=True)
                (parc / 'cockpit.json').write_text(json.dumps(state), encoding='utf-8')
            env = dict(os.environ, HOME=home)
            env.pop('MON_STUDIO', None)
            env.pop('CLAUDE_CODE_HOST_SESSION_ID', None)
            if host is not None:
                env['CLAUDE_CODE_HOST_SESSION_ID'] = host   # a session of the desktop app
            return subprocess.run([sys.executable, str(HOOK)], input=raw if raw is not None else json.dumps(payload),
                                  capture_output=True, text=True, env=env, timeout=20)

    def call(self, tool, tool_input, state=None):
        if state is None:
            state = {'page': 'x'}
        return self.run_hook({'tool_name': tool, 'tool_input': tool_input}, state)

    def assertDenied(self, r):
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PreToolUse')
        self.assertEqual(out['permissionDecision'], 'deny')
        return out['permissionDecisionReason']

    def assertAllowed(self, r):
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_session_with_prompt_and_no_model_is_refused(self):
        reason = self.assertDenied(self.call(SESSION, {'title': 'T', 'prompt': 'fais ceci'}))
        self.assertLess(len(reason), 600)
        for word in ('Haiku', 'Sonnet', 'Opus', 'model'):
            self.assertIn(word, reason)

    def test_session_with_a_model_passes(self):
        self.assertAllowed(self.call(SESSION, {'title': 'T', 'prompt': 'fais ceci', 'model': 'sonnet'}))

    def test_offer_without_prompt_passes(self):
        self.assertAllowed(self.call(SESSION, {'initiation': 'offer', 'title': 'Une idée'}))
        self.assertAllowed(self.call(SESSION, {'initiation': 'offer', 'title': 'Une idée', 'prompt': '  '}))

    def test_start_by_proposal_id_alone_passes(self):
        self.assertAllowed(self.call(SESSION, {'proposal_id': 'task_ab12cd34'}))

    def test_general_purpose_agent_without_model_is_refused(self):
        self.assertDenied(self.call('Agent', {'description': 'x', 'prompt': 'y', 'subagent_type': 'general-purpose'}))
        self.assertDenied(self.call('Agent', {'description': 'x', 'prompt': 'y', 'subagent_type': 'claude'}))

    def test_agent_without_subagent_type_and_model_is_refused(self):
        self.assertDenied(self.call('Agent', {'description': 'x', 'prompt': 'y'}))

    def test_agent_with_a_model_passes(self):
        self.assertAllowed(self.call('Agent', {'description': 'x', 'prompt': 'y', 'model': 'haiku'}))

    def test_named_agent_passes(self):
        self.assertAllowed(self.call('Agent', {'description': 'x', 'prompt': 'y', 'subagent_type': 'backlog:redacteur-po'}))

    def test_fork_passes(self):
        self.assertAllowed(self.call('Agent', {'description': 'x', 'prompt': 'y', 'subagent_type': 'fork'}))

    def test_switch_off_lets_everything_through(self):
        off = {'page': 'x', 'controle_modele': False}
        self.assertAllowed(self.call(SESSION, {'prompt': 'fais ceci'}, off))
        self.assertAllowed(self.call('Agent', {'prompt': 'y'}, off))

    def test_switch_on_or_absent_keeps_the_check(self):
        self.assertDenied(self.call(SESSION, {'prompt': 'fais ceci'}, {'page': 'x', 'controle_modele': True}))

    def test_silent_outside_a_session_of_the_desktop_app(self):
        # A terminal session, a `claude -p` or a wake of the connector: no CLAUDE_CODE_HOST_SESSION_ID.
        payload = {'tool_name': 'Agent', 'tool_input': {'prompt': 'y'}}
        self.assertAllowed(self.run_hook(payload, {'page': 'x'}, host=None))
        self.assertAllowed(self.run_hook(payload, {'page': 'x'}, host=''))
        self.assertAllowed(self.run_hook({'tool_name': SESSION, 'tool_input': {'prompt': 'fais ceci'}}, {'page': 'x'},
                                         host=None))

    def test_silent_without_mon_studio_or_when_disabled(self):
        r = self.run_hook({'tool_name': 'Agent', 'tool_input': {'prompt': 'y'}})
        self.assertAllowed(r)
        self.assertAllowed(self.call('Agent', {'prompt': 'y'}, {'page': 'x', 'disabled': True}))

    def test_unreadable_input_is_silent_with_exit_0(self):
        for raw in ('', 'not json', '[1, 2]', '{"tool_name": "Agent", "tool_input": "x"}'):
            self.assertAllowed(self.run_hook(None, {'page': 'x'}, raw=raw))

    def test_unknown_tool_passes(self):
        self.assertAllowed(self.call('Bash', {'command': 'ls'}))


if __name__ == '__main__':
    unittest.main()
