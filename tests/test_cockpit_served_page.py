"""Tests: the pinned pages run the code the connector serves (option B, PM Q13, 2026-11-16).

A published page is a small shell (assets/page-epinglee.html: PROJET_FIXE, title, first paint, loader). The loader
calls the connector's read-only tool `gabarit`, which returns the page's code (assets/page-servie.html cut into css,
html and js) from its copy in ~/Mon Studio/.parc, and runs the script in a <script> filled by textContent. A change
of the served code alone asks for no republication; a change of the shell or of the tools declaration does.

python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
ASSETS = ROOT / 'skills' / 'mon-studio' / 'assets'
SHELL = ASSETS / 'page-epinglee.html'
SERVED = ASSETS / 'page-servie.html'
TESTER = ROOT / 'tests' / 'tester-epinglee.js'
VERSION = json.loads((ROOT / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']


def load(name, path, env):
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.env = {'HOME': str(self.root / 'home'), 'MON_STUDIO': str(self.root / 'home' / 'Mon Studio')}
        (self.root / 'home' / 'Mon Studio' / '.parc').mkdir(parents=True)
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()


class Connector(Base):
    def setUp(self):
        super().setUp()
        self.m = load('connector_served_under_test', SCRIPTS / 'mcp_mon_studio.py', self.env)

    def test_gabarit_is_declared_read_only(self):
        (t,) = [t for t in self.m.OUTILS if t['name'] == 'gabarit']
        self.assertIs(t['annotations']['readOnlyHint'], True)
        self.assertEqual(t['inputSchema']['properties'], {})

    def test_it_serves_the_styles_the_markup_and_the_script_of_the_installed_version(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.traiter({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'gabarit', 'arguments': {}}})
        r = json.loads(buf.getvalue())['result']
        self.assertNotIn('isError', r)
        g = json.loads(r['content'][0]['text'])
        self.assertEqual(g['version'], VERSION)
        self.assertRegex(g['empreinte'], r'^[0-9a-f]{12}$')
        self.assertIn(':root {', g['css'])
        self.assertIn('id="boite"', g['html'])
        for tag in ('<style>', '<script>', '</script>'):
            self.assertNotIn(tag, g['html'])
        self.assertIn('var SERVEUR = "host:mon-studio";', g['js'])
        if shutil.which('node'):
            f = self.root / 'servi.js'
            f.write_text(g['js'], encoding='utf-8')
            p = subprocess.run(['node', '--check', str(f)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_the_copy_next_to_the_connector_comes_first(self):
        ici = self.root / 'home' / 'Mon Studio' / '.parc'
        (ici / 'page-servie.html').write_text('<style>\nb{}\n</style>\n<p id="x"></p>\n<script>\nvar copie = 1;\n</script>\n',
                                              encoding='utf-8')
        (ici / 'cockpit.json').write_text(json.dumps({'version': '9.9.9'}), encoding='utf-8')
        self.m.ICI = ici
        g = self.m.gabarit()
        self.assertEqual((g['css'], g['html'], g['js'], g['version']), ('b{}\n', '<p id="x"></p>', 'var copie = 1;\n', '9.9.9'))

    def test_no_code_is_a_clear_error(self):
        self.m.ICI = self.root / 'ailleurs' / 'scripts'
        with self.assertRaisesRegex(RuntimeError, "code de la page absent"):
            self.m.gabarit()


class Shell(unittest.TestCase):
    def test_the_shell_is_small_and_holds_no_page_code(self):
        text = SHELL.read_text(encoding='utf-8')
        self.assertLess(len(text.encode('utf-8')), 6000)
        self.assertEqual(text.count('var PROJET_FIXE = "";'), 1)
        self.assertIn('<title>Mon Studio</title>', text)
        self.assertIn('callTool("host:mon-studio", "gabarit"', text)
        self.assertIn('s.textContent = g.js;', text)
        self.assertNotIn('var SERVEUR', text)
        self.assertNotIn('PROJET_FIXE', SERVED.read_text(encoding='utf-8').replace('typeof PROJET_FIXE === "string" ? PROJET_FIXE', ''))


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class ShellInAFakeBrowser(unittest.TestCase):
    def run_page(self, page, entree):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp) / 'entree.json'
            data.write_text(json.dumps(entree), encoding='utf-8')
            p = subprocess.run(['node', str(TESTER), str(page), str(data)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_the_shell_runs_the_served_code(self):
        out = self.run_page(SHELL, {'lignes': []})
        self.assertEqual(out['injectes'], ['STYLE', 'SCRIPT'])
        self.assertIn('lignes', out['veilles'])
        self.assertIn('id="boite"', out['coquille'])
        self.assertIn("Rien ne t'attend", out['tableau'])

    def test_a_connector_that_does_not_serve_the_code_says_so(self):
        for entree in ({'lignes': [], 'gabaritErreur': 'not_in_manifest'}, {'lignes': [], 'gabaritVide': True}):
            out = self.run_page(SHELL, entree)
            self.assertEqual((out['injectes'], out['veilles']), ([], []))
            self.assertIn('Mon Studio ne répond pas sur ce Mac', out['coquillePanne'])
            self.assertIn('connecteur « mon-studio »', out['coquillePanne'])


class Install(Base):
    def setUp(self):
        super().setUp()
        self.i = load('install_served_under_test', SCRIPTS / 'install.py', self.env)
        self.shell = self.root / 'page-epinglee.html'
        self.served = self.root / 'page-servie.html'
        shutil.copyfile(SHELL, self.shell)
        shutil.copyfile(SERVED, self.served)
        self.i.PAGE_SOURCE, self.i.PAGE_CODE_SOURCE = self.shell, self.served

    def test_the_page_declares_gabarit(self):
        self.assertEqual(self.i.PAGE_TOOLS[-1], 'gabarit')

    def test_only_the_shell_changes_the_fingerprint(self):
        base = self.i.page_sha()
        self.served.write_text(self.served.read_text(encoding='utf-8').replace('<h2>Mise en route</h2>', '<h2>Démarrage</h2>'),
                               encoding='utf-8')
        self.assertNotEqual(self.served.read_text(encoding='utf-8'), SERVED.read_text(encoding='utf-8'))
        self.assertEqual(self.i.page_sha(), base)
        self.shell.write_text(self.shell.read_text(encoding='utf-8').replace('Mon Studio se charge…', 'Chargement…'),
                              encoding='utf-8')
        self.assertNotEqual(self.i.page_sha(), base)

    def test_the_served_code_is_copied_next_to_the_connector(self):
        lines = []
        self.assertTrue(self.i.install_copies(lines, force=True))
        copy = self.i.INTERNAL / 'page-servie.html'
        self.assertEqual(copy.read_bytes(), self.served.read_bytes())
        self.assertEqual(self.i.copy_state(copy, self.served), 'current')
        copy.unlink()
        self.assertEqual(self.i.copies_to_install(), 'code de la page absent')

    def test_a_project_copy_is_the_shell_with_its_folder(self):
        html = self.i.project_page_html('/Users/pm/Drive/Studio - Alpha', 'Alpha')
        self.assertIn('var PROJET_FIXE = "/Users/pm/Drive/Studio - Alpha";', html)
        self.assertIn('<title>Alpha</title>', html)
        self.assertIn('"gabarit"', html)
        self.assertNotIn('var SERVEUR', html)


if __name__ == '__main__':
    unittest.main()
