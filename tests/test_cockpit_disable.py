"""Tests of disabling Mon Studio without touching the plugin: python3 -m unittest discover -s tests

The PM can only disable a whole plugin in Claude Code, never one skill: disabling the cockpit skill takes away what
it put on the Mac and silences its hook. Everything runs on a fake HOME: `launchctl` is a fake one, alone on PATH,
so the real launchd of the Mac running the tests is never touched. The app's configuration is synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = 'https://claude.ai/artifact/AbCdEf'


def load(name, env):
    """A fresh copy of a cockpit script, its paths taken from this environment."""
    with mock.patch.dict(os.environ, env):
        if 'MON_STUDIO' not in env:
            os.environ.pop('MON_STUDIO', None)
        spec = importlib.util.spec_from_file_location(f'{name}_under_test', SCRIPTS / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class Disable(unittest.TestCase):
    """Mon Studio installed on a fake HOME: state, copies, an old local server's agent, connector declared in the app."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.home = root / 'home'
        fake_bin = root / 'bin'
        fake_bin.mkdir()
        self.launchctl_log = root / 'launchctl.log'
        launchctl = fake_bin / 'launchctl'
        launchctl.write_text(f'#!/bin/sh\necho "$@" >> "{self.launchctl_log}"\n')
        launchctl.chmod(0o755)
        env = {'HOME': str(self.home), 'PATH': str(fake_bin)}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop('MON_STUDIO', None)
        mac = mock.patch('sys.platform', 'darwin')  # these tests assume macOS: say so, whatever runs them
        mac.start()
        self.addCleanup(mac.stop)
        self.install = load('install', env)
        i = self.install
        i.APP_SESSIONS.mkdir(parents=True)
        for name in ('parc.py', 'mcp_mon_studio.py') + i.PROJECT_TOOLS:
            (i.INTERNAL / name).parent.mkdir(parents=True, exist_ok=True)
            (i.INTERNAL / name).write_text((SCRIPTS / name).read_text(encoding='utf-8'), encoding='utf-8')
        (i.MON_STUDIO / 'CLAUDE.md').write_text('# Mon Studio\n', encoding='utf-8')
        (i.MON_STUDIO / 'fils-rouges.json').write_text('[]', encoding='utf-8')
        i.LEGACY_AGENT.parent.mkdir(parents=True)
        i.LEGACY_AGENT.write_text('<plist/>', encoding='utf-8')
        i.record_state(version=i.plugin_version(), installedAt='2026-10-13T09:00:00', page=PAGE,
                       pageSha=i.page_sha())
        self.write_config({'mcpServers': {'mon-studio': i.connector_entry(),
                                          'other-server': {'command': 'node', 'args': ['/opt/other.js']}},
                           'preferences': {'theme': 'dark'}})

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write_config(self, config):
        self.install.APP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        self.install.APP_CONFIG.write_text(json.dumps(config, indent=2), encoding='utf-8')

    def config(self):
        return json.loads(self.install.APP_CONFIG.read_text(encoding='utf-8'))

    def state(self):
        return json.loads(self.install.STATE.read_text(encoding='utf-8'))

    def run_quiet(self, function, *args, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = function(*args, **kwargs)
        return code, out.getvalue()

    def status_on_a_mac(self):
        with mock.patch.object(sys, 'platform', 'darwin'):
            return self.install.status()

    def test_disable_removes_what_the_skill_put_on_the_mac(self):
        i = self.install
        before = i.APP_CONFIG.read_text(encoding='utf-8')
        code, out = self.run_quiet(i.disable)
        self.assertEqual(code, 0)
        self.assertFalse(i.LEGACY_AGENT.exists())
        self.assertIn(f'bootout gui/{os.getuid()}/io.thetribe.mon-studio', self.launchctl_log.read_text())
        config = self.config()
        self.assertNotIn('mon-studio', config['mcpServers'])
        self.assertEqual(config['mcpServers']['other-server'], {'command': 'node', 'args': ['/opt/other.js']})
        self.assertEqual(config['preferences'], {'theme': 'dark'})
        self.assertEqual((i.INTERNAL / 'claude_desktop_config.before-disable.json').read_text(encoding='utf-8'), before)
        state = self.state()
        self.assertTrue(state['disabled'])
        self.assertTrue(state['disabledAt'])
        self.assertTrue(state['pageUnpinned'])
        self.assertEqual(state['page'], PAGE)
        self.assertEqual(state['version'], i.plugin_version())
        # Without a foreman, nothing in .parc runs any more: the copies go.
        for name in ('parc.py', 'mcp_mon_studio.py') + i.PROJECT_TOOLS:
            self.assertFalse((i.INTERNAL / name).exists(), name)
        # The PM's files stay.
        self.assertTrue((i.MON_STUDIO / 'CLAUDE.md').exists())
        self.assertTrue((i.MON_STUDIO / 'fils-rouges.json').exists())
        self.assertIn(f'désépingler la page {PAGE}', out)
        self.assertIn("quitter et rouvrir l'app", out)

    def test_disable_names_the_morning_tasks_still_in_the_app(self):
        """`disable` cannot delete a scheduled task (only the app's tool can): it says which remain, and `status`
        keeps asking until they are gone, so a forgotten task never runs every morning for nothing."""
        i = self.install
        i.MORNING_TASK.parent.mkdir(parents=True)
        i.MORNING_TASK.write_text('---\nname: point-du-matin\n---\nx\n', encoding='utf-8')
        code, out = self.run_quiet(i.disable)
        self.assertEqual(code, 0)
        self.assertIn('supprimer la tâche planifiée « point-du-matin »', out)
        self.assertNotIn('point-du-matin-verif', out)
        with mock.patch.object(i.sys, 'platform', 'darwin'):
            s = i.status()
            self.assertEqual(s['todo'], ['disabled', 'delete_morning_tasks'])
            self.assertEqual(s['morningTasksLeft'], ['point-du-matin'])
            i.MORNING_TASK.unlink()
            self.assertEqual(i.status()['todo'], ['disabled'])

    def test_disabling_twice_keeps_the_first_date(self):
        i = self.install
        self.run_quiet(i.disable)
        i.record_state(disabledAt='2026-10-15T08:00:00')
        code, _ = self.run_quiet(i.disable)
        self.assertEqual(code, 0)
        self.assertEqual(self.state()['disabledAt'], '2026-10-15T08:00:00')

    def test_a_mon_studio_entry_that_is_not_ours_is_kept(self):
        i = self.install
        self.write_config({'mcpServers': {'mon-studio': {'command': '/usr/bin/python3', 'args': ['/opt/elsewhere.py']}}})
        before = i.APP_CONFIG.read_bytes()
        code, out = self.run_quiet(i.disable)
        self.assertEqual(code, 0)
        self.assertEqual(i.APP_CONFIG.read_bytes(), before)
        self.assertFalse((i.INTERNAL / 'claude_desktop_config.before-disable.json').exists())
        self.assertIn('pointe ailleurs : non modifiée', out)
        self.assertNotIn("quitter et rouvrir l'app", out)
        self.assertTrue(self.state()['disabled'])

    def test_foreman_tools_stay_while_there_are_chantiers(self):
        i = self.install
        (i.MON_STUDIO / 'chantiers').mkdir()
        mirror = i.MON_STUDIO / 'chantiers' / 'essai.json'
        mirror.write_text('{"chantier": "Essai"}', encoding='utf-8')
        self.run_quiet(i.disable)
        for name in ('parc.py',) + i.PROJECT_TOOLS:
            self.assertTrue((i.INTERNAL / name).exists(), name)
        self.assertFalse(i.CONNECTOR_COPY.exists())
        self.assertEqual(mirror.read_text(encoding='utf-8'), '{"chantier": "Essai"}')

    def test_status_proposes_nothing_once_disabled(self):
        i = self.install
        self.run_quiet(i.disable)
        s = self.status_on_a_mac()
        self.assertTrue(s['disabled'])
        self.assertTrue(s['disabledAt'])
        self.assertEqual(s['todo'], ['disabled'])
        self.assertEqual(s['connector'], 'absent')
        self.assertEqual(s['serverLeftovers'], [])

    def test_installing_again_reactivates_and_pins_the_same_page(self):
        i = self.install
        self.run_quiet(i.disable)

        with mock.patch.object(sys, 'platform', 'darwin'):
            code, out = self.run_quiet(i.apply, with_connector=True)
            self.assertEqual(code, 0)
            self.assertIn('réactivé', out)
            state = self.state()
            self.assertNotIn('disabled', state)
            self.assertNotIn('disabledAt', state)
            self.assertEqual(self.config()['mcpServers']['mon-studio'], i.connector_entry())
            s = self.status_on_a_mac()
            self.assertFalse(s['disabled'])
            self.assertNotIn('disabled', s['todo'])
            self.assertNotIn('publish_page', s['todo'])
            self.assertIn('pin_page', s['todo'])
            code, _ = self.run_quiet(i.record_pinned)
            self.assertEqual(code, 0)
            self.assertNotIn('pin_page', self.status_on_a_mac()['todo'])
            self.assertEqual(self.state()['page'], PAGE)

    def test_nothing_to_remove_when_mon_studio_was_never_installed(self):
        empty = pathlib.Path(self.tmp.name) / 'empty-home'
        install = load('install', {'HOME': str(empty), 'PATH': os.environ['PATH']})
        code, out = self.run_quiet(install.disable)
        self.assertEqual(code, 0)
        self.assertIn('rien à retirer', out)
        self.assertFalse(install.STATE.exists())


class AuthorizationSwitch(unittest.TestCase):
    """Answering an authorization from the page (Q40, Q44) stays as the PM set it: install.py never turns it on.
    Same fake HOME as Disable, without running Disable's own tests again."""
    setUp, tearDown = Disable.setUp, Disable.tearDown
    write_config, config, state = Disable.write_config, Disable.config, Disable.state
    run_quiet, status_on_a_mac = Disable.run_quiet, Disable.status_on_a_mac

    def test_off_by_default_and_kept_by_apply_and_disable(self):
        i = self.install
        s = self.status_on_a_mac()
        self.assertFalse(s['autorisationsTableau'])
        with mock.patch.object(sys, 'platform', 'darwin'):
            self.run_quiet(i.apply, with_connector=True)
        self.assertNotIn('autorisations_tableau', self.state())
        i.record_state(autorisations_tableau=True, autorisations_sessions=['local_essai'])
        with mock.patch.object(sys, 'platform', 'darwin'):
            self.run_quiet(i.apply, force=True)
        self.run_quiet(i.disable)
        self.assertIs(self.state()['autorisations_tableau'], True)
        self.assertEqual(self.state()['autorisations_sessions'], ['local_essai'])

    def test_direct_answers_off_by_default_and_kept_by_apply_and_disable(self):
        i = self.install
        s = self.status_on_a_mac()
        self.assertEqual((s['reponsesDirectes'], s['reponsesDirectesSessions'], s['reponsesDirectesMinutes']),
                         (False, None, None))
        with mock.patch.object(sys, 'platform', 'darwin'):
            self.run_quiet(i.apply, with_connector=True)
        self.assertNotIn('reponses_directes', self.state())
        i.record_state(reponses_directes=True, reponses_directes_sessions=['local_essai'], reponses_directes_minutes=5)
        with mock.patch.object(sys, 'platform', 'darwin'):
            self.run_quiet(i.apply, force=True)
        self.run_quiet(i.disable)
        st = self.state()
        self.assertEqual((st['reponses_directes'], st['reponses_directes_sessions'], st['reponses_directes_minutes']),
                         (True, ['local_essai'], 5))
        s = self.status_on_a_mac()
        self.assertEqual((s['reponsesDirectes'], s['reponsesDirectesMinutes']), (True, 5))

    def test_a_page_declared_without_the_answer_tools_is_republished(self):
        i = self.install
        self.run_quiet(i.record_page, PAGE)
        i.record_state(pageTools=['lignes', 'ouvrir', 'autorisations', 'decider'])
        s = self.status_on_a_mac()
        self.assertFalse(s['pageToolsCurrent'])
        self.assertIn('republish_page', s['todo'])

    def test_a_page_declared_with_fewer_tools_is_republished_with_all(self):
        i = self.install
        s = self.status_on_a_mac()
        self.assertFalse(s['pageToolsCurrent'])
        self.assertIn('republish_page', s['todo'])
        self.run_quiet(i.record_page, PAGE)
        self.assertEqual(self.state()['pageTools'], ['lignes', 'projet', 'ouvrir', 'autorisations', 'decider', 'attentes', 'repondre', 'clore', 'lire', 'gabarit'])
        s = self.status_on_a_mac()
        self.assertTrue(s['pageToolsCurrent'])
        self.assertNotIn('republish_page', s['todo'])


class Hook(unittest.TestCase):
    """The session-start hook copies nothing once Mon Studio is disabled, even when the plugin's version moves."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mon_studio = pathlib.Path(self.tmp.name) / 'Mon Studio'
        (self.mon_studio / '.parc').mkdir(parents=True)
        self.sync = load('sync', {'MON_STUDIO': str(self.mon_studio)})
        self.platform = mock.patch.object(sys, 'platform', 'darwin')
        self.platform.start()
        self.popen = mock.patch.object(self.sync.subprocess, 'Popen')
        self.run = mock.patch.object(self.sync.subprocess, 'run')
        self.popen_calls = self.popen.start()
        self.run_calls = self.run.start()

    def tearDown(self):
        self.run.stop()
        self.popen.stop()
        self.platform.stop()
        self.tmp.cleanup()

    def write_state(self, state):
        self.sync.STATE.write_text(json.dumps(state), encoding='utf-8')

    def test_disabled_copies_nothing_even_at_a_new_version(self):
        self.assertNotEqual(self.sync.plugin_version(), '0.0.1')
        self.write_state({'version': '0.0.1', 'disabled': True, 'disabledAt': '2026-10-15T08:00:00'})
        before = self.sync.STATE.read_text(encoding='utf-8')
        self.assertIsNone(self.sync.needs_update())
        self.sync.check()
        self.sync.apply_update()
        self.popen_calls.assert_not_called()
        self.run_calls.assert_not_called()
        self.assertEqual(self.sync.STATE.read_text(encoding='utf-8'), before)
        self.assertFalse(self.sync.LOG.exists())

    def test_reactivated_follows_the_versions_again(self):
        self.write_state({'version': '0.0.1'})
        self.assertEqual(self.sync.needs_update(), ('0.0.1', self.sync.plugin_version()))
        self.sync.check()
        self.popen_calls.assert_called_once()


if __name__ == '__main__':
    unittest.main()
