"""Mon Studio without a local server (Q13, 2026-10-29): python3 -m unittest discover -s tests

The pinned page and its connector are the only screen. parc.py has no server, no launcher and no launchd agent left;
install.py puts nothing of the server on the Mac any more, and takes away what an older installation left there,
except a file the PM changed. Everything runs on a fake HOME, with a fake `launchctl` alone on PATH: the real launchd
of the Mac running the tests is never called.

With the local screen gone, nothing may disappear in silence: a recent session of the app whose transcript is not on
this Mac (a cloud session, a moved folder) cannot be read, and the page and mon-studio.md say so in one line at the
top, without changing the lines."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'

FAKE_LAUNCHCTL = """#!/bin/sh
echo "$@" >> "{log}"
case "$1" in
  print) [ -f "{loaded}" ] && exit 0 || exit 113 ;;
  bootout) /bin/rm -f "{loaded}" ;;
esac
exit 0
"""


def load(name, env):
    """A fresh copy of a cockpit script, its paths taken from this environment."""
    with mock.patch.dict(os.environ, env):
        os.environ.pop('MON_STUDIO', None)
        spec = importlib.util.spec_from_file_location(f'{name}_no_server', SCRIPTS / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ParcHasNoServer(unittest.TestCase):
    def test_server_options_are_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, MON_STUDIO=str(pathlib.Path(tmp) / 'Mon Studio'))
            for option in ('--servir', '--lanceur', '--installer', '--desinstaller'):
                with self.subTest(option=option):
                    r = subprocess.run([sys.executable, str(SCRIPTS / 'parc.py'), option], capture_output=True,
                                       text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
                    self.assertEqual(r.returncode, 2)
                    self.assertIn('unrecognized arguments', r.stderr)
            self.assertFalse((pathlib.Path(tmp) / 'Library').exists())

    def test_no_server_code_left(self):
        source = (SCRIPTS / 'parc.py').read_text(encoding='utf-8')
        for word in ('launchctl', 'plistlib', '47474', 'http.server', 'mon-studio.html', '/ancien'):
            self.assertNotIn(word, source)
        with tempfile.TemporaryDirectory() as tmp:
            parc = load('parc', {'HOME': tmp})
        for name in ('servir', 'lanceur', 'installer', 'desinstaller', 'rendre_html', 'rendre_ancien', 'PORT', 'LABEL'):
            self.assertFalse(hasattr(parc, name), name)
        for name in ('construire', 'pour_la_page', 'rendre_md', 'expliquer', 'rapport_controle', 'ajouter_marqueur'):
            self.assertTrue(callable(getattr(parc, name)), name)


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.home = root / 'home'
        fake_bin = root / 'bin'
        fake_bin.mkdir()
        self.log = root / 'launchctl.log'
        self.loaded = root / 'agent-loaded'
        launchctl = fake_bin / 'launchctl'
        launchctl.write_text(FAKE_LAUNCHCTL.format(log=self.log, loaded=self.loaded))
        launchctl.chmod(0o755)
        env = {'HOME': str(self.home), 'PATH': str(fake_bin)}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop('MON_STUDIO', None)
        self.platform = mock.patch.object(sys, 'platform', 'darwin')
        self.platform.start()
        self.i = load('install', env)
        self.i.APP_SESSIONS.mkdir(parents=True)

    def tearDown(self):
        self.platform.stop()
        self.env.stop()
        self.tmp.cleanup()

    def run_quiet(self, function, *args, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = function(*args, **kwargs)
        return code, out.getvalue()

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def old_installation(self):
        """What install.py put on the Mac before Q13, exactly as it wrote it."""
        i = self.i
        i.LEGACY_AGENT.parent.mkdir(parents=True)
        i.LEGACY_AGENT.write_text('<plist/>', encoding='utf-8')
        self.loaded.write_text('')
        i.write_atomic(i.LEGACY_LAUNCH, json.dumps(i.legacy_launch(), ensure_ascii=False, indent=2) + '\n')
        i.write_atomic(i.LEGACY_SETTINGS, json.dumps(i.legacy_settings(), indent=2) + '\n')
        i.write_atomic(i.MON_STUDIO / 'CLAUDE.md', i.LEGACY_CLAUDE_MD)
        for page in i.LEGACY_PAGES:
            i.write_atomic(page, '<!doctype html><title>Mon Studio</title>\n<!-- mon-studio:tableau-21 -->\n')
        i.write_atomic(i.LEGACY_JOURNAL, 'ok 2026-10-28 09:00:00 · écran servi sur http://localhost:47474\n')
        for name in ('parc.py', 'mcp_mon_studio.py') + i.PROJECT_TOOLS:
            i.write_atomic(i.INTERNAL / name, (SCRIPTS / name).read_text(encoding='utf-8'))
        i.record_state(version='0.0.1', installedAt='2026-10-13T09:00:00')

    def test_a_first_install_puts_nothing_of_the_server(self):
        i = self.i
        code, out = self.run_quiet(i.apply, with_connector=True)
        self.assertEqual(code, 0, out)
        for path in (i.LEGACY_AGENT, i.LEGACY_LAUNCH, i.LEGACY_SETTINGS, i.MON_STUDIO / '.claude') + i.LEGACY_PAGES:
            self.assertFalse(path.exists(), path)
        self.assertEqual(i.PARC_COPY.read_bytes(), i.PARC_SOURCE.read_bytes())
        self.assertEqual(i.CONNECTOR_COPY.read_bytes(), i.CONNECTOR_SOURCE.read_bytes())
        self.assertEqual((i.MON_STUDIO / 'CLAUDE.md').read_text(encoding='utf-8'), i.CLAUDE_MD)
        self.assertNotIn('preview_start', i.CLAUDE_MD)
        self.assertTrue(all(c.startswith('print ') for c in self.calls()), self.calls())
        s = i.status()
        self.assertNotIn('remove_server', s['todo'])
        self.assertEqual(s['serverLeftovers'], [])
        for key in ('server', 'launchAgent'):
            self.assertNotIn(key, s)
        plan = '\n'.join(i.plan())
        for word in ('localhost', 'serveur local', 'retirerait', 'retiré'):
            self.assertNotIn(word, plan + out)

    def test_an_old_installation_is_cleaned_up(self):
        i = self.i
        self.old_installation()
        s = i.status()
        self.assertIn('remove_server', s['todo'])
        self.assertEqual(sorted(s['serverLeftovers']), sorted(str(p) for p in (
            i.LEGACY_AGENT, i.LEGACY_LAUNCH, i.LEGACY_SETTINGS, i.LEGACY_JOURNAL, i.MON_STUDIO / 'CLAUDE.md') + i.LEGACY_PAGES))
        self.assertIn(f'retirerait {i.LEGACY_AGENT}', '\n'.join(i.plan()))
        self.assertFalse(any(c.startswith('bootout') for c in self.calls()))  # status and plan only read

        code, out = self.run_quiet(i.apply)
        self.assertEqual(code, 0, out)
        self.assertIn(f'bootout gui/{os.getuid()}/io.thetribe.mon-studio', self.calls())
        self.assertFalse(any(c.startswith('bootstrap') for c in self.calls()))
        for path in (i.LEGACY_AGENT, i.LEGACY_LAUNCH, i.LEGACY_SETTINGS, i.LEGACY_JOURNAL, i.MON_STUDIO / '.claude') + i.LEGACY_PAGES:
            self.assertFalse(path.exists(), path)
        self.assertEqual((i.MON_STUDIO / 'CLAUDE.md').read_text(encoding='utf-8'), i.CLAUDE_MD)
        self.assertIn('arrêté     ancien serveur local', out)
        self.assertEqual(i.PARC_COPY.read_bytes(), i.PARC_SOURCE.read_bytes())
        s = i.status()
        self.assertNotIn('remove_server', s['todo'])
        self.assertEqual(s['serverLeftovers'], [])
        code, out = self.run_quiet(i.apply)
        self.assertEqual(code, 0)
        self.assertNotIn('ancien', out)

    def test_repair_cleans_up_too(self):
        i = self.i
        self.old_installation()
        code, out = self.run_quiet(i.main, ['repair'])
        self.assertEqual(code, 0, out)
        self.assertIn('réinstallation demandée', out)
        self.assertFalse(i.LEGACY_AGENT.exists())
        self.assertEqual(i.status()['serverLeftovers'], [])

    def test_files_the_pm_changed_stay(self):
        i = self.i
        self.old_installation()
        launch = json.dumps(dict(i.legacy_launch(), configurations=i.legacy_launch()['configurations']
                                 + [{'name': 'Mon app', 'runtimeExecutable': 'npm', 'port': 3000}]))
        settings = json.dumps({'permissions': {'allow': ['mcp__Claude_Browser__preview_start', 'Bash(ls:*)']}})
        claude_md = i.LEGACY_CLAUDE_MD + '\nMa note à moi.\n'
        page = '<!doctype html><title>Ma page</title>\n'
        i.write_atomic(i.LEGACY_LAUNCH, launch)
        i.write_atomic(i.LEGACY_SETTINGS, settings)
        i.write_atomic(i.MON_STUDIO / 'CLAUDE.md', claude_md)
        i.write_atomic(i.LEGACY_PAGES[0], page)
        s = i.status()
        self.assertNotIn(str(i.LEGACY_LAUNCH), s['serverLeftovers'])
        self.assertNotIn(str(i.LEGACY_SETTINGS), s['serverLeftovers'])
        self.assertIn('laisserait', '\n'.join(i.plan()))
        code, out = self.run_quiet(i.apply)
        self.assertEqual(code, 0, out)
        self.assertFalse(i.LEGACY_AGENT.exists())
        self.assertEqual(i.LEGACY_LAUNCH.read_text(encoding='utf-8'), launch)
        self.assertEqual(i.LEGACY_SETTINGS.read_text(encoding='utf-8'), settings)
        self.assertEqual((i.MON_STUDIO / 'CLAUDE.md').read_text(encoding='utf-8'), claude_md)
        self.assertEqual(i.LEGACY_PAGES[0].read_text(encoding='utf-8'), page)
        self.assertIn(f'gardé      {i.LEGACY_LAUNCH} : modifié', out)
        self.assertIn(f'gardé      {i.LEGACY_SETTINGS} : modifié', out)
        # What stays is not a leftover to remove: status does not ask for it again and again.
        self.assertNotIn('remove_server', i.status()['todo'])

    def test_disable_takes_the_leftovers_away(self):
        i = self.i
        self.old_installation()
        code, out = self.run_quiet(i.disable)
        self.assertEqual(code, 0, out)
        for path in (i.LEGACY_AGENT, i.LEGACY_LAUNCH, i.LEGACY_SETTINGS):
            self.assertFalse(path.exists(), path)
        self.assertEqual(i.status()['todo'], ['disabled'])


class SessionsWithoutTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.parc = parc = load('parc', {'HOME': str(root)})
        parc.APP, parc.TRANSCRIPTS, parc.CHANTIERS = root / 'app', root / 'transcripts', root / 'chantiers'
        parc.CHANTIERS.mkdir()
        (parc.TRANSCRIPTS / 'proj').mkdir(parents=True)
        self.now = time.time()
        self.card('local_a', 'cli-a', 'Kit A', self.now - 600)
        (parc.TRANSCRIPTS / 'proj' / 'cli-a.jsonl').write_text(json.dumps({
            'type': 'assistant', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.now - 600)),
            'message': {'role': 'assistant', 'stop_reason': 'end_turn',
                        'content': [{'type': 'text', 'text': 'Je publie la page ?'}]}}) + '\n')

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, sid, cli, title, activity, archived=False):
        folder = self.parc.APP / 'acct' / 'org'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{sid}.json').write_text(json.dumps({
            'sessionId': sid, 'cliSessionId': cli, 'title': title, 'cwd': '/studios/Studio-Essai',
            'lastActivityAt': int(activity * 1000), 'createdAt': int((activity - 60) * 1000), 'isArchived': archived}))

    def state(self):
        cache = {'version': self.parc.VERSION_CACHE, 'fiches': {}, 'transcripts': {}, 'suivi': {}, 'controle': {}}
        return self.parc.construire(7, 7, self.now, cache)

    def test_nothing_missing_says_nothing(self):
        e = self.state()
        self.assertIsNone(e['sans_transcript'])
        self.assertIsNone(self.parc.pour_la_page(e)['sans_transcript'])
        self.assertNotIn('transcript', self.parc.rendre_md(e))

    def test_a_recent_session_without_transcript_is_said_at_the_top(self):
        before = self.state()
        self.card('local_b', 'cli-b', 'Kit B dans le cloud', self.now - 3600)
        self.card('local_c', 'cli-c', 'Kit C ancien', self.now - 30 * 86400)          # outside the window
        self.card('local_d', 'cli-d', 'Kit D archivé', self.now - 60, archived=True)  # archived: not shown anyway
        self.card('local_e', None, 'Kit E sans identifiant', self.now - 900)
        e = self.state()
        st = e['sans_transcript']
        self.assertEqual((st['nombre'], st['titres']), (2, ['Kit E sans identifiant', 'Kit B dans le cloud']))
        self.assertEqual(st['texte'], "2 sessions de l'app non lues : leur historique est introuvable sur ce Mac (session dans le "
                                      "cloud, dossier déplacé…) : « Kit E sans identifiant », « Kit B dans le cloud ».")
        self.assertEqual(self.parc.pour_la_page(e)['sans_transcript'], st)
        md = self.parc.rendre_md(e).splitlines()
        self.assertEqual(md[2], f"_{st['texte']}_")
        # The lines do not change.
        page, page_before = self.parc.pour_la_page(e), self.parc.pour_la_page(before)
        self.assertEqual(page['lignes'], page_before['lignes'])
        self.assertEqual(page['anciennes'], page_before['anciennes'])
        self.assertTrue(page['lignes'])

    def test_a_card_just_moved_without_transcript_is_not_counted_yet(self):
        # 30/10, 17 h 53: after a clear_session the card already points to a new id, whose transcript comes with its first message.
        self.card('local_r', 'cli-r', 'Contremaître remis à zéro', self.now - 60)
        self.assertIsNone(self.state()['sans_transcript'])
        self.card('local_r', 'cli-r', 'Contremaître remis à zéro', self.now - 600)
        self.assertEqual(self.state()['sans_transcript']['nombre'], 1)

    def test_one_session_and_more_than_five(self):
        self.card('local_b', 'cli-b', 'Kit B', self.now - 3600)
        self.assertTrue(self.state()['sans_transcript']['texte'].startswith(
            "1 session de l'app non lue : son historique est introuvable"))
        for n in range(6):
            self.card(f'local_x{n}', f'cli-x{n}', f'Kit X{n}', self.now - 7200 - n)
        st = self.state()['sans_transcript']
        self.assertEqual((st['nombre'], len(st['titres'])), (7, 5))
        self.assertTrue(st['texte'].endswith('et 2 autre(s).'))

    def test_the_pinned_page_shows_it(self):
        page = (ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html').read_text(encoding='utf-8')
        self.assertIn('id="sans-transcript"', page)
        self.assertIn('p.sans_transcript', page)


if __name__ == '__main__':
    unittest.main()
