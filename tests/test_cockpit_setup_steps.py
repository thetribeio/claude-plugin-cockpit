"""Tests: the « Mise en route » block (2026-11-15, review Q4 and Q8): python3 -m unittest discover -s tests

`/cockpit:mon-studio` lays only the base (folder, connector, pages, rules). The morning point, the first check of each
Studio's conflicts and the Terminal's login are lines of a block at the head of the board, from the first day, each
with its cost and its button, until done (seen on the Mac) or « Pas pour moi ». Computed without a model
(projets.mise_en_route), rendered by the page; the morning step's permissions are written only by
`install.py apply --autorisations`, never by `repair`. Everything lives in temporary folders."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_cockpit_permission_hook import Base, load_connector

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
FAKE_AUTH = """#!{python}
import json, os, sys
open(os.environ['FAUX_TRACE'], 'a').write(' '.join(sys.argv[1:]) + '\\n')
print(json.dumps({{'loggedIn': os.environ.get('FAUX_CONNECTE') == '1'}}))
"""


class Steps(Base):
    def setUp(self):
        super().setUp()
        self.home = self.root / 'home'
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {'HOME': str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('MON_STUDIO_CLAUDE', None)
        self.m = load_connector(self.mon_studio, self.root / 'app', self.root / 'tr')
        self.p = self.m.charger_projets()
        self.addCleanup(self.m.AUTORISATIONS.arreter)

    def tasks(self, *names):
        for n in names:
            f = self.home / '.claude' / 'scheduled-tasks' / n / 'SKILL.md'
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('x', encoding='utf-8')

    def fake_claude(self, connecte):
        exe, trace = self.root / 'claude', self.root / 'trace.txt'
        exe.write_text(FAKE_AUTH.format(python=sys.executable))
        exe.chmod(0o755)
        for k, v in {'MON_STUDIO_CLAUDE': str(exe), 'FAUX_TRACE': str(trace), 'FAUX_CONNECTE': '1' if connecte else '0'}.items():
            patcher = mock.patch.dict(os.environ, {k: v})
            patcher.start()
            self.addCleanup(patcher.stop)
        return trace

    def cles(self, r=None):
        return [e['cle'] for e in (r or self.p.mise_en_route(1000))['etapes']]

    def test_a_fresh_mac_has_the_morning_point_first_then_the_terminal(self):
        r = self.p.mise_en_route(1000)
        self.assertEqual([e['cle'] for e in r['etapes']], ['etape-matin', 'etape-terminal'])
        self.assertEqual(r['matin'], 'a_faire')
        matin, terminal = r['etapes']
        self.assertIn('passe quotidienne des conflits en dépend', matin['note'])
        self.assertEqual(matin['copier'], '/cockpit:mon-studio point du matin')
        self.assertRegex(matin['cout'], r'\d,\d\d \$ par jour ouvré, \d,\d\d % de ta semaine')
        self.assertIn("n'est pas installé sur ce Mac", terminal['detail'])
        self.assertEqual(terminal['copier'], '/cockpit:mon-studio terminal')

    def test_the_morning_step_leaves_once_both_tasks_exist(self):
        self.tasks('point-du-matin')
        self.assertIn('etape-matin', self.cles(), 'one task is not the step done')
        self.tasks('point-du-matin-verif')
        r = self.p.mise_en_route(1000)
        self.assertNotIn('etape-matin', self.cles(r))
        self.assertEqual(r['matin'], 'fait')

    def test_pas_pour_moi_sets_a_step_aside_for_good(self):
        self.assertEqual(self.m.clore({'cle': 'etape-matin'}), {'ecarte': 'etape-matin'})
        r = self.p.mise_en_route(1000)
        self.assertEqual(self.cles(r), ['etape-terminal'])
        self.assertEqual(r['matin'], 'ecarte')
        with self.assertRaises(ValueError):
            self.m.clore({'cle': 'etape-matin'})
        with self.assertRaises(ValueError):
            self.m.clore({'cle': 'etape-autre'})

    def test_a_logged_in_terminal_note_is_the_step_done(self):
        (self.parc_dir / 'terminal.json').write_text(json.dumps({'connecte': True, 't': 1}))
        self.assertEqual(self.cles(), ['etape-matin'])

    def test_the_terminal_is_checked_locally_at_most_every_ten_minutes(self):
        trace = self.fake_claude(connecte=False)
        r = self.p.mise_en_route(1000)
        self.assertIn('etape-terminal', self.cles(r))
        self.assertNotIn("n'est pas installé", r['etapes'][-1]['detail'])
        self.p.mise_en_route(1100)
        self.assertEqual(trace.read_text().splitlines(), ['auth status'], 'no `claude -p`, and kept 10 minutes')
        os.environ['FAUX_CONNECTE'] = '1'
        self.assertNotIn('etape-terminal', self.cles(self.p.mise_en_route(1000 + 601)))

    def test_the_costs_come_from_install_once_recorded(self):
        (self.parc_dir / 'cockpit.json').write_text(json.dumps({'etapes': {'matin': 'environ 9,99 $ par jour ouvré'}}))
        self.assertEqual(self.p.mise_en_route(1000)['etapes'][0]['cout'], 'environ 9,99 $ par jour ouvré')

    def test_the_connector_gives_the_block_with_the_lines(self):
        with mock.patch.object(self.p, 'mise_en_route', return_value={'etapes': [], 'matin': 'fait'}) as mr:
            with mock.patch.object(self.p, 'calculer', return_value=None), \
                    mock.patch.object(self.p, 'matin_pour_la_page', return_value=None), \
                    mock.patch.object(self.p, 'conflits_global', return_value=None):
                out = self.m.lignes()
        self.assertEqual(out['mise_en_route'], {'etapes': [], 'matin': 'fait'})
        mr.assert_called_once()

    def test_a_step_button_only_copies_its_command(self):
        with mock.patch.object(self.m.subprocess, 'run') as run:
            self.assertEqual(self.m.ouvrir({'copier': '/cockpit:mon-studio point du matin'}),
                             {'copie': '/cockpit:mon-studio point du matin'})
            self.assertEqual(run.call_args[0][0], ['pbcopy'])
            with self.assertRaises(ValueError):
                self.m.ouvrir({'copier': '/cockpit:mon-studio désactive'})
        self.assertEqual(run.call_count, 1)


def load_install(home):
    with mock.patch.dict(os.environ, {'HOME': str(home)}):
        os.environ.pop('MON_STUDIO', None)
        spec = importlib.util.spec_from_file_location('install_setup_steps', SCRIPTS / 'install.py')
        i = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(i)
    return i


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.i = load_install(self.home)
        self.i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
        p = mock.patch.object(self.i.sys, 'platform', 'darwin')
        p.start()
        self.addCleanup(p.stop)

    def quiet(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.i.main(list(argv))
        return code, out.getvalue()

    def test_the_plan_lays_the_base_and_names_the_steps_left_for_the_block(self):
        text = '\n'.join(self.i.plan())
        self.assertIn('ne poserait pas : le point du matin', text)
        self.assertIn('« Mise en route »', text)
        self.assertNotIn('autorisations pour', text)
        block = text.split(self.i.PASTE_START)[1]
        self.assertEqual(block.count('(étape de mise en route, seulement si tu la fais)'), 3)
        self.assertRegex(block, r'sans le point du matin : \d,\d\d \$ par jour')

    def test_an_installation_asks_for_none_of_the_steps(self):
        self.quiet('apply', '--connector')
        s = self.i.status()
        self.assertFalse({'create_morning_task', 'create_morning_check_task', 'allow_scripts', 'terminal_login',
                          'set_task_models', 'morning_blocked'} & set(s['todo']), s['todo'])
        self.assertIsNone(s['terminalLogin'])
        self.assertEqual(s['miseEnRoute'], {'ecartees': [], 'matin': 'a_faire'})
        settings = json.loads(self.i.CLAUDE_SETTINGS.read_text(encoding='utf-8'))
        self.assertEqual(settings, {'permissions': {'deny': self.i.ACTION_TOOLS}}, 'no allow rule written by the installation')
        state = json.loads(self.i.STATE.read_text(encoding='utf-8'))
        self.assertEqual(state['etapes'], self.i.setup_step_costs())

    def test_the_morning_step_shows_its_cost_and_only_its_go_writes_the_rules(self):
        self.quiet('apply', '--connector')
        code, out = self.quiet('etape', 'matin')
        self.assertEqual(code, 0)
        self.assertIn('ajouterait 6 autorisations', out)
        self.assertIn("Total de l'étape", out)
        before = self.i.CLAUDE_SETTINGS.read_text(encoding='utf-8')
        self.assertNotIn('allow', before, '`etape` writes nothing')
        self.quiet('repair')
        self.assertEqual(self.i.CLAUDE_SETTINGS.read_text(encoding='utf-8'), before, '`repair` never writes the allow rules')
        self.quiet('apply', '--autorisations')
        self.assertEqual(self.i.status()['scriptRules'], 'present')

    def test_a_step_set_aside_is_reported(self):
        self.i.INTERNAL.mkdir(parents=True, exist_ok=True)
        (self.i.INTERNAL / 'mise-en-route.json').write_text(json.dumps({'ecartees': {'matin': 1, 'terminal': 2}}))
        self.assertEqual(self.i.setup_steps_state(), {'ecartees': ['matin', 'terminal'], 'matin': 'ecarte'})


class Page(unittest.TestCase):
    MATIN = {'cle': 'etape-matin', 'etape': 'matin', 'titre': 'Mettre en route le point du matin', 'cout': 'environ 0,94 $',
             'note': 'La passe quotidienne des conflits en dépend.', 'detail': 'Chaque jour ouvré…',
             'copier': '/cockpit:mon-studio point du matin'}
    TERMINAL = {'cle': 'etape-terminal', 'etape': 'terminal', 'titre': 'Connecter le Claude du Terminal', 'cout': '',
                'note': '', 'detail': 'Six gestes…', 'copier': '/cockpit:mon-studio terminal'}
    VERIFIER = {'cle': 'a1b2c3d4e5f6', 'type': 'verifier', 'titre': 'Vérifier les conflits du Studio, une fois',
                'detail': 'Environ 3 questions…', 'depuis': 1, 'session': 'local_' + '0' * 8 + '-0000-0000-0000-' + '0' * 12,
                'copier': '/cockpit:conflits rattrapage'}

    def run_page(self, **payload):
        payload.setdefault('lignes', [])
        payload.setdefault('outils', ['lignes', 'ouvrir', 'clore'])
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def liste(self):
        return {'studios': [{'nom': 'Studio-Essai', 'dossier': '/studios/Studio-Essai', 'role': 'pm'}],
                'projets': [{'nom': 'Studio-Essai', 'dossier': '/studios/Studio-Essai', 'role': 'pm', 'lignes': [self.VERIFIER]}]}

    def test_the_block_heads_the_board_in_order_and_the_check_leaves_the_board(self):
        out = self.run_page(mise_en_route={'etapes': [self.MATIN, self.TERMINAL], 'matin': 'a_faire'},
                            liste_projets=self.liste())
        self.assertFalse(out['miseEnRouteHidden'])
        html = out['miseEnRoute']
        positions = [html.index(x) for x in ('point du matin', 'Vérifier les conflits de Studio-Essai', 'Claude du Terminal')]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('La passe quotidienne des conflits en dépend.', html)
        self.assertEqual(html.count('Pas pour moi'), 3)
        self.assertIn('data-copier="/cockpit:conflits rattrapage"', html)
        self.assertNotIn('Vérifier les conflits', out['tableau'])

    def test_no_step_left_no_block(self):
        out = self.run_page(mise_en_route={'etapes': [], 'matin': 'fait'})
        self.assertTrue(out['miseEnRouteHidden'])
        self.assertEqual(out['miseEnRoute'], '')

    def test_buttons_copy_the_command_and_set_a_step_aside(self):
        out = self.run_page(mise_en_route={'etapes': [self.MATIN], 'matin': 'a_faire'},
                            cliquer=[['data-etape-copier', '/cockpit:mon-studio point du matin'], ['data-clore', 'etape-matin']],
                            attributs={'data-etape': 'etape-matin'})
        self.assertIn(['ouvrir', {'copier': '/cockpit:mon-studio point du matin'}], out['appels'])
        self.assertIn(['clore', {'cle': 'etape-matin'}], out['appels'])
        self.assertTrue(out['miseEnRouteHidden'], 'set aside: the block leaves at once')

    def test_an_empty_today_sends_to_the_morning_step(self):
        out = self.run_page(mise_en_route={'etapes': [self.MATIN], 'matin': 'a_faire'}, matin={'etat': 'pas_passe'})
        self.assertIn('data-voir-etape="etape-matin"', out['matin'])
        self.assertIn('« Mise en route »', out['matin'])
        out = self.run_page(mise_en_route={'etapes': [], 'matin': 'fait'}, matin={'etat': 'pas_passe'})
        self.assertNotIn('data-voir-etape', out['matin'])
        self.assertIn('Point du matin pas encore passé', out['matin'])

    def test_a_project_page_has_no_block(self):
        out = self.run_page(mise_en_route={'etapes': [self.MATIN], 'matin': 'a_faire'}, projetFixe='/studios/Studio-Essai')
        self.assertTrue(out['miseEnRouteHidden'])


if __name__ == '__main__':
    unittest.main()
