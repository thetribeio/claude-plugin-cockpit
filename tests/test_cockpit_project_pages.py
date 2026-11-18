"""Tests: one pinned page per project (« épingle-moi le projet X », 2026-11-05): python3 -m unittest discover -s tests

One template, assets/page-epinglee.html. A project page is a copy whose PROJET_FIXE holds the Studio's folder: it opens
on that project only, without « Tous les projets » nor the tabs, titled with the project's name. install.py writes the
copy (copie-projet), notes the page (page-projet), forgets it (page-projet --retirer), and asks for
`republish_project_pages` when the template changed since its publication.

Everything runs on a fake HOME; the folder never lands in the repository."""
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
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-epinglee.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
MAIN = 'https://claude.ai/artifact/MainPage'
ALPHA_PAGE = 'https://claude.ai/artifact/AlphaPage'
ALPHA = '/Users/pm/Drive/Studio - Alpha'


def load_install(env):
    with mock.patch.dict(os.environ, env):
        os.environ.pop('MON_STUDIO', None)
        spec = importlib.util.spec_from_file_location('install_pages_under_test', SCRIPTS / 'install.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def quiet(function, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = function(*args)
    return code, out.getvalue()


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        env = {'HOME': str(self.root / 'home')}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.i = load_install(env)
        self.i.APP_SESSIONS.mkdir(parents=True)
        self.i.INTERNAL.mkdir(parents=True)
        self.i.record_state(version=self.i.plugin_version(), page=MAIN, pageSha=self.i.page_sha(),
                            pageTools=self.i.PAGE_TOOLS)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def state(self):
        return json.loads(self.i.STATE.read_text(encoding='utf-8'))

    def test_a_fresh_apply_builds_projets_json_so_status_names_the_pages(self):
        # First install: projets.json does not exist before apply; apply builds it once, and status offers the pages.
        alpha = _isolation.make_studio(self.root / 'Studio - Alpha')
        self.i.MON_STUDIO.mkdir(parents=True, exist_ok=True)
        (self.i.MON_STUDIO / 'studios.json').write_text(json.dumps([str(alpha)]), encoding='utf-8')
        self.assertFalse(self.i.PROJETS_JSON.exists())
        with mock.patch.object(self.i.sys, 'platform', 'darwin'):
            code, out = quiet(self.i.apply)
            self.assertEqual(code, 0, out)
            self.assertIn('liste par projet', out)
            s = self.i.status()
        self.assertEqual([p['dossier'] for p in s['missingProjectPages']], [str(alpha)])
        self.assertIn('publish_project_pages', s['todo'])

    def test_the_copy_fills_the_injection_point_and_the_title(self):
        target = self.root / 'scratch' / 'alpha.html'
        target.parent.mkdir()
        tricky = '/Users/pm/Drive/Studio "A" </script><b>'
        self.assertEqual(quiet(self.i.copy_project_page, tricky, str(target), 'Alpha & co')[0], 0)
        html = target.read_text(encoding='utf-8')
        self.assertNotIn('var PROJET_FIXE = "";', html)
        self.assertIn('<title>Alpha &amp; co</title>', html)
        line = next(l for l in html.splitlines() if l.startswith('var PROJET_FIXE = '))
        self.assertNotIn('</script>', line)
        self.assertEqual(json.loads(line[len('var PROJET_FIXE = '):-1].replace('<\\/', '</')), tricky)
        # The template itself keeps its empty value: the folder is never written in the repository.
        self.assertEqual(PAGE.read_text(encoding='utf-8').count('var PROJET_FIXE = "";'), 1)

    def test_the_copy_refuses_a_relative_folder_and_a_target_in_the_plugin(self):
        self.assertEqual(quiet(self.i.copy_project_page, 'Studio - Alpha', str(self.root / 'a.html'))[0], 1)
        self.assertEqual(quiet(self.i.copy_project_page, ALPHA, str(self.i.SKILL / 'assets' / 'alpha.html'))[0], 1)
        self.assertFalse((self.i.SKILL / 'assets' / 'alpha.html').exists())

    def test_a_noted_page_is_in_status_and_current(self):
        self.assertEqual(quiet(self.i.record_project_page, ALPHA + '/', ALPHA_PAGE)[0], 0)
        self.assertEqual(self.state()['pages_projet'], {ALPHA: ALPHA_PAGE})
        s = self.i.status()
        self.assertEqual(s['projectPages'], [{'dossier': ALPHA, 'page': ALPHA_PAGE, 'current': True}])
        self.assertNotIn('republish_project_pages', s['todo'])

    def test_one_page_per_project_and_a_valid_address(self):
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        self.assertEqual(quiet(self.i.record_project_page, ALPHA, 'https://claude.ai/artifact/Other')[0], 1)
        self.assertEqual(quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)[0], 0)   # republished at its address
        self.assertEqual(quiet(self.i.record_project_page, '/S/Beta', 'http://example.org')[0], 1)
        self.assertEqual(self.state()['pages_projet'], {ALPHA: ALPHA_PAGE})

    def test_a_new_template_asks_to_republish_the_project_pages(self):
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        state = self.state()
        state['pages_projet_etat'][ALPHA]['sha'] = 'old'
        self.i.STATE.write_text(json.dumps(state), encoding='utf-8')
        s = self.i.status()
        self.assertIn('republish_project_pages', s['todo'])
        self.assertEqual(s['projectPages'][0]['current'], False)
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        self.assertNotIn('republish_project_pages', self.i.status()['todo'])

    def test_fewer_tools_also_asks_to_republish(self):
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        state = self.state()
        state['pages_projet_etat'][ALPHA]['tools'] = ['lignes']
        self.i.STATE.write_text(json.dumps(state), encoding='utf-8')
        self.assertIn('republish_project_pages', self.i.status()['todo'])

    def test_forget_a_page(self):
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        code, out = quiet(self.i.forget_project_page, ALPHA)
        self.assertEqual(code, 0)
        self.assertIn('désépingler', out)
        self.assertEqual((self.state()['pages_projet'], self.state()['pages_projet_etat']), ({}, {}))
        self.assertEqual(self.i.status()['projectPages'], [])
        self.assertEqual(quiet(self.i.forget_project_page, 'Studio - Alpha')[0], 1)   # not a folder
        self.assertEqual(self.state()['pages_projet_retirees'], [ALPHA])
        self.assertEqual(quiet(self.i.forget_project_page, ALPHA)[0], 0)   # again: still out, noted once
        self.assertEqual(self.state()['pages_projet_retirees'], [ALPHA])

    # Pinned by default (PM, 2026-11-06): one page per Studio of projets.json, without asking.
    def studios(self, *pairs):
        self.i.PROJETS_JSON.parent.mkdir(parents=True, exist_ok=True)
        self.i.PROJETS_JSON.write_text(json.dumps({'studios': [{'nom': n, 'dossier': d, 'role': 'membre'} for n, d in pairs]}),
                                       encoding='utf-8')

    def test_every_studio_without_a_page_is_to_publish(self):
        import unicodedata
        beta = unicodedata.normalize('NFD', '/Users/pm/Drive/Studio - Bêta')
        self.studios(('Alpha', ALPHA), ('Bêta', beta), ('Alpha', ALPHA + '/'), ('Rien', 'relatif'))
        s = self.i.status()
        self.assertEqual(s['missingProjectPages'], [{'dossier': ALPHA, 'nom': 'Alpha'}, {'dossier': beta, 'nom': 'Bêta'}])
        self.assertIn('publish_project_pages', s['todo'])
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        # The page noted with the other Unicode form of the folder counts for it.
        quiet(self.i.record_project_page, unicodedata.normalize('NFC', beta), 'https://claude.ai/artifact/BetaPage')
        s = self.i.status()
        self.assertEqual(s['missingProjectPages'], [])
        self.assertNotIn('publish_project_pages', s['todo'])

    def test_a_page_the_pm_took_away_never_comes_back(self):
        self.studios(('Alpha', ALPHA), ('Gamma', '/S/Gamma'))
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        quiet(self.i.forget_project_page, ALPHA)
        quiet(self.i.forget_project_page, '/S/Gamma')    # no page yet: not proposed either
        s = self.i.status()
        self.assertEqual(s['missingProjectPages'], [])
        self.assertNotIn('publish_project_pages', s['todo'])
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)   # « épingle-moi Alpha » again
        self.assertEqual(self.state()['pages_projet_retirees'], ['/S/Gamma'])

    def test_no_list_yet_nothing_to_publish(self):
        self.assertEqual(self.i.status()['missingProjectPages'], [])

    def test_disable_lists_them_to_unpin_and_pin_page_comes_back(self):
        quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE)
        code, out = quiet(self.i.disable)
        self.assertEqual(code, 0)
        self.assertIn(f'désépingler la page du projet Studio - Alpha {ALPHA_PAGE}', out)
        state = self.state()
        state.pop('disabled')
        self.i.STATE.write_text(json.dumps(state), encoding='utf-8')
        self.assertIn('pin_page', self.i.status()['todo'])
        quiet(self.i.record_pinned)
        self.assertNotIn('pin_page', self.i.status()['todo'])

    def test_cli(self):
        env = dict(os.environ)
        r = subprocess.run(['python3', str(SCRIPTS / 'install.py'), 'page-projet', ALPHA, ALPHA_PAGE],
                           capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run(['python3', str(SCRIPTS / 'install.py'), 'page-projet', '--retirer', ALPHA],
                           capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()['pages_projet'], {})


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    VUE = {'dossier': ALPHA, 'nom': 'Alpha', 'questions': [], 'sujets': [], 'tiers': [], 'journal': []}

    def run_page(self, **entree):
        entree.setdefault('lignes', [{'studio': 'Alpha', 'cle': 'local_00000000-0000-0000-0000-000000000001',
                                      'complet': 'Une question', 'type': 'decision'}])
        entree.setdefault('projets', [{'studio': 'Alpha', 'dossier': ALPHA, 'nom': 'Alpha'}])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(entree, f)
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_a_project_page_opens_on_its_project_only(self):
        out = self.run_page(projetFixe=ALPHA, projet=self.VUE,
                            matin={'etat': 'ok', 'genere_le': '2026-11-05T07:30:00', 'jour': 'normale', 'agenda': [],
                                   'a_traiter': [], 'regle': [], 'preparer_demain': [], 'reunions_sans_cr': [],
                                   'entre_studio': []})
        self.assertIn(['projet', {'dossier': ALPHA}], out['appels'])
        self.assertFalse(out['projetCache'])
        self.assertTrue(out['boiteCachee'])
        self.assertTrue(out['tousProjetsHidden'])
        self.assertTrue(out['ongletsHidden'])
        self.assertTrue(out['matinHidden'])
        self.assertTrue(out['studiosHidden'])
        self.assertEqual((out['titreDocument'], out['titrePage'], out['projetNom']), ('Alpha', 'Alpha', 'Alpha'))

    def test_all_projects_stays_on_the_project(self):
        out = self.run_page(projetFixe=ALPHA, projet=self.VUE, cliquer=[['data-tous', '1']])
        self.assertFalse(out['projetCache'])
        self.assertEqual(out['titrePage'], 'Alpha')

    def test_the_main_page_is_unchanged(self):
        out = self.run_page()
        self.assertTrue(out['projetCache'])
        self.assertEqual((out['titreDocument'], out['titrePage']), ('Mon Studio', ''))
        self.assertFalse(out['tousProjetsHidden'])
        self.assertNotIn('projet', [a[0] for a in out['appels']])


if __name__ == '__main__':
    unittest.main()
