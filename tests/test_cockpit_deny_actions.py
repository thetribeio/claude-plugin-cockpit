"""Tests: the installer denies sessions the connector's three action tools (2026-11-26): python3 -m unittest discover -s tests

`repondre`, `decider` and `clore` are the page's gestures; nothing told a session from the page, so any session could
answer or grant a permission in the PM's place. `install.py apply` adds a deny rule for each to
~/.claude/settings.json (after a dated copy, no duplicate, nothing overwritten) and records the ones it added itself;
`disable` removes only those. Everything lives in a temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
TOOLS = ['mcp__mon-studio__repondre', 'mcp__mon-studio__decider', 'mcp__mon-studio__clore']


class DenyActions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        with mock.patch.dict(os.environ, {'HOME': str(self.home)}):
            os.environ.pop('MON_STUDIO', None)
            spec = importlib.util.spec_from_file_location('install_deny_actions', SCRIPTS / 'install.py')
            self.i = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.i)
        self.i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
        p = mock.patch.object(self.i.sys, 'platform', 'darwin')
        p.start()
        self.addCleanup(p.stop)

    def run_main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.i.main(list(argv))
        return code, out.getvalue()

    def write_settings(self, data):
        self.i.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.i.CLAUDE_SETTINGS.write_text(json.dumps(data), encoding='utf-8')

    def settings(self):
        return json.loads(self.i.CLAUDE_SETTINGS.read_text(encoding='utf-8'))

    def backups(self):
        return list(self.i.CLAUDE_SETTINGS.parent.glob('settings.json.avant-mon-studio-*'))

    def state(self):
        return json.loads(self.i.STATE.read_text(encoding='utf-8'))

    def test_the_three_tools_are_the_connectors_action_tools(self):
        self.assertEqual(self.i.ACTION_TOOLS, TOOLS)
        for t in TOOLS:
            self.assertIn(t.rsplit('__', 1)[1], self.i.PAGE_TOOLS)

    def test_apply_on_empty_settings_poses_the_three_rules_after_a_copy(self):
        self.assertEqual(self.run_main('apply')[0], 0)
        self.assertEqual(self.settings(), {'permissions': {'deny': TOOLS}})
        self.assertEqual(self.state()['refus_poses'], TOOLS)
        self.assertEqual(self.i.status()['actionsRefusees'], 'present')

    def test_apply_copies_an_existing_file_before_changing_it(self):
        self.write_settings({'theme': 'dark'})
        self.run_main('apply')
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(json.loads(self.backups()[0].read_text()), {'theme': 'dark'})
        self.assertEqual(self.settings()['theme'], 'dark')

    def test_other_deny_and_allow_rules_are_kept(self):
        self.write_settings({'permissions': {'deny': ['Bash(rm -rf *)'], 'allow': ['Bash(ls)'], 'ask': ['Bash(git push)']},
                             'env': {'A': '1'}})
        self.run_main('apply')
        s = self.settings()
        self.assertEqual(s['permissions']['deny'], ['Bash(rm -rf *)'] + TOOLS)
        self.assertEqual(s['permissions']['allow'], ['Bash(ls)'])
        self.assertEqual(s['permissions']['ask'], ['Bash(git push)'])
        self.assertEqual(s['env'], {'A': '1'})

    def test_apply_twice_adds_no_duplicate_and_no_second_copy(self):
        self.run_main('apply')
        self.run_main('apply')
        self.run_main('repair')
        self.assertEqual(self.settings()['permissions']['deny'], TOOLS)
        self.assertEqual(self.backups(), [])  # nothing existed the first time, nothing changed after
        self.assertEqual(self.state()['refus_poses'], TOOLS)

    def test_rules_already_there_are_not_added_nor_removed_by_disable(self):
        # The PM's seat: repondre and decider denied since early November.
        self.write_settings({'permissions': {'deny': ['mcp__mon-studio__repondre', 'mcp__mon-studio__decider']}})
        self.run_main('apply')
        self.assertEqual(self.settings()['permissions']['deny'],
                         ['mcp__mon-studio__repondre', 'mcp__mon-studio__decider', 'mcp__mon-studio__clore'])
        self.assertEqual(self.state()['refus_poses'], ['mcp__mon-studio__clore'])
        self.run_main('disable')
        self.assertEqual(self.settings()['permissions']['deny'],
                         ['mcp__mon-studio__repondre', 'mcp__mon-studio__decider'])

    def test_all_three_already_there_changes_nothing_and_disable_keeps_them(self):
        self.write_settings({'permissions': {'deny': list(TOOLS)}})
        before = self.i.CLAUDE_SETTINGS.read_text()
        self.run_main('apply')
        self.assertEqual(self.i.CLAUDE_SETTINGS.read_text(), before)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.state()['refus_poses'], [])
        self.run_main('disable')
        self.assertEqual(self.settings()['permissions']['deny'], TOOLS)

    def test_disable_removes_exactly_what_was_posed(self):
        self.write_settings({'permissions': {'deny': ['Bash(rm -rf *)'], 'allow': ['Bash(ls)']}})
        self.run_main('apply')
        code, out = self.run_main('disable')
        self.assertEqual(code, 0)
        self.assertIn('retiré     le refus aux sessions', out)
        self.assertEqual(self.settings()['permissions'], {'deny': ['Bash(rm -rf *)'], 'allow': ['Bash(ls)']})
        self.assertNotIn('refus_poses', self.state())

    def test_install_again_after_disable_poses_them_again(self):
        self.run_main('apply')
        self.run_main('disable')
        self.run_main('apply')
        self.assertEqual(self.settings()['permissions']['deny'], TOOLS)
        self.assertEqual(self.state()['refus_poses'], TOOLS)

    def test_unreadable_settings_are_never_written(self):
        self.i.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.i.CLAUDE_SETTINGS.write_text('{ pas du json', encoding='utf-8')
        code, out = self.run_main('apply')
        self.assertEqual(code, 0)
        self.assertEqual(self.i.CLAUDE_SETTINGS.read_text(), '{ pas du json')
        self.assertIn('illisible', out)
        self.assertEqual(self.i.status()['actionsRefusees'], 'unreadable')
        self.assertNotIn('refus_poses', self.state())

    def test_plan_announces_it_and_status_asks_for_it(self):
        self.assertTrue(any('refuserait aux sessions 3 gestes' in l for l in self.i.plan()))
        self.assertEqual(self.i.status()['actionsRefusees'], 'missing')
        self.run_main('apply')
        self.assertTrue(any('garderait  le refus aux sessions' in l for l in self.i.plan()))
        self.write_settings({})
        s = self.i.status()
        self.assertEqual(s['actionsRefusees'], 'missing')
        self.assertIn('refuse_actions', s['todo'])
        self.write_settings({'permissions': {'deny': TOOLS[:2]}})
        self.assertTrue(any('refuserait aux sessions 1 geste ' in l for l in self.i.plan()))

    def test_apply_does_not_pose_the_allow_rules_without_the_flag(self):
        self.run_main('apply')
        self.assertNotIn('allow', self.settings()['permissions'])


if __name__ == '__main__':
    unittest.main()
