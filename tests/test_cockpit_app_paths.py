"""Tests: Mon Studio finds the Claude app's files on every OS: python3 -m unittest discover -s tests

Asked on 2026-10-29 by the light foreman session (challenge of the foreman-pm kit, PM's go « fais-le si pas besoin de
mon avis »): parc.py hard-coded the macOS folder of the app's session records, so on a PC neither Mon Studio nor the
follow-up read anything. The folder is now resolved by OS, with the same rule as the point of the foreman-pm kit:
macOS ~/Library/Application Support/Claude, Windows %APPDATA%\\Claude, Linux ~/.config/Claude (XDG_CONFIG_HOME when
set); MON_STUDIO_APP_SESSIONS wins everywhere. question.py follows the same rule and no longer needs fcntl."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('.py', ''), SCRIPTS / name)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


parc = load('parc.py')
question = load('question.py')
H = pathlib.Path('/home/pm')


class AppPaths(unittest.TestCase):
    def test_macos_keeps_the_current_folder(self):
        self.assertEqual(parc.dossier_fiches({}, 'darwin', H), H / 'Library/Application Support/Claude/claude-code-sessions')
        self.assertEqual(parc.dossier_app({}, 'darwin', H) / 'Local Storage' / 'leveldb',
                         H / 'Library/Application Support/Claude/Local Storage/leveldb')

    def test_windows_reads_appdata(self):
        env = {'APPDATA': r'C:\Users\pm\AppData\Roaming'}
        self.assertEqual(parc.dossier_fiches(env, 'win32', H),
                         pathlib.Path(r'C:\Users\pm\AppData\Roaming') / 'Claude' / 'claude-code-sessions')
        self.assertEqual(parc.dossier_fiches({}, 'win32', H), H / 'AppData/Roaming/Claude/claude-code-sessions')

    def test_linux_reads_xdg_config(self):
        self.assertEqual(parc.dossier_fiches({}, 'linux', H), H / '.config/Claude/claude-code-sessions')
        self.assertEqual(parc.dossier_fiches({'XDG_CONFIG_HOME': '/cfg'}, 'linux', H),
                         pathlib.Path('/cfg/Claude/claude-code-sessions'))

    def test_the_variable_wins_everywhere(self):
        for os_name in ('darwin', 'win32', 'linux'):
            with self.subTest(os_name):
                env = {'MON_STUDIO_APP_SESSIONS': '/x/fiches', 'APPDATA': '/a'}
                self.assertEqual(parc.dossier_fiches(env, os_name, H), pathlib.Path('/x/fiches'))

    def test_question_follows_the_same_rule(self):
        for env, os_name in (({}, 'darwin'), ({'APPDATA': '/a'}, 'win32'), ({}, 'win32'), ({}, 'linux'),
                             ({'XDG_CONFIG_HOME': '/cfg'}, 'linux'), ({'MON_STUDIO_APP_SESSIONS': '/x'}, 'win32')):
            with self.subTest(os_name, env=env):
                self.assertEqual(question.app_sessions_dir(env, os_name, H), parc.dossier_fiches(env, os_name, H))

    def test_this_mac_is_unchanged(self):
        self.assertEqual(parc.APP, parc.dossier_fiches())
        if parc.sys.platform == 'darwin' and not parc.os.environ.get('MON_STUDIO_APP_SESSIONS'):
            self.assertEqual(parc.APP, pathlib.Path.home() / 'Library/Application Support/Claude/claude-code-sessions')


if __name__ == '__main__':
    unittest.main()
