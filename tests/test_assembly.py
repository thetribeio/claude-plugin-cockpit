"""Tests of the assembly of the cockpit plugin: python3 -m unittest discover -s tests

The plugin brings together Mon Studio (skill mon-studio), the point and the follow-up of the foreman-pm kit 0.8, and
the PM's working rules. Three things are checked here:
- every need listed by the kit (A-FOURNIR-PAR-LE-PLUGIN, nine items) is met or set aside with its reason, in the
  table of docs/a-fournir.md, and what the table says is met is really in the plugin;
- the plugin's hooks do nothing on a computer where Mon Studio is not installed;
- nothing depends on the `tribe` plugin nor on a path of one PM's computer.
"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOKS = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))['hooks']
A_FOURNIR = ROOT / 'docs' / 'a-fournir.md'
RULES = ('format-reponses.md', 'livrables.md', 'modele-effort.md', 'passation.md', 'sessions.md')
OPTIONAL_RULES = ('heures-publication.md',)   # adoption test of 2026-11-02: given only when the PM asks


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def commands():
    return [(event, g.get('matcher'), h['command']) for event, groups in HOOKS.items() for g in groups for h in g['hooks']]


def repo_files():
    listed = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard'],
                            capture_output=True, text=True).stdout.splitlines()
    return [ROOT / f for f in listed if (ROOT / f).is_file()]


def table_rows():
    """The rows of the table of docs/a-fournir.md: (number, need, state, where or why)."""
    rows = []
    for line in A_FOURNIR.read_text(encoding='utf-8').splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) == 4 and cells[0].isdigit():
            rows.append((int(cells[0]), cells[1], cells[2], cells[3]))
    return rows


class EveryNeedIsMetOrSetAside(unittest.TestCase):
    def test_the_nine_items_of_the_kit_are_in_the_table(self):
        self.assertEqual([r[0] for r in table_rows()], list(range(1, 10)))

    def test_each_item_is_met_or_set_aside_with_its_reason(self):
        for n, need, state, where in table_rows():
            self.assertIn(state, ('posé', 'écarté'), f'§{n} {need}')
            self.assertGreaterEqual(len(where), 30, f'§{n} : dire où, ou pourquoi')

    def test_what_is_met_is_in_the_plugin(self):
        for n, need, state, where in table_rows():
            if state != 'posé':
                continue
            paths = [p for p in re.findall(r'`([^`]+)`', where) if '/' in p and not p.startswith(('~', '$', '/'))]
            self.assertTrue(paths, f'§{n} : le tableau cite le fichier du plugin qui le pose')
            for p in paths:
                self.assertTrue((ROOT / p.split(' ')[0]).exists(), f'§{n} : {p} absent du plugin')

    def test_1_the_rules_come_with_a_session_start_hook(self):
        self.assertEqual(sorted(p.name for p in (ROOT / 'regles').glob('*.md')), sorted(RULES))
        starts = [c for e, m, c in commands() if e == 'SessionStart' and 'hooks/regles.py' in c]
        self.assertEqual(len(starts), 1)

    def test_2_nothing_clears_a_session_any_more(self):
        # the only PreToolUse allowed are the model controls on launches (0.3.12: the scale too), which clear nothing
        pre = [(m, c) for e, m, c in commands() if e == 'PreToolUse']
        self.assertEqual([m for m, c in pre], ['mcp__ccd_session__start_session|Agent'] * 2)
        self.assertIn('hooks/modele_lancement.py', pre[0][1])
        self.assertIn('hooks/bareme_modele.py', pre[1][1])
        self.assertFalse((ROOT / 'hooks' / 'remise_a_zero.py').exists())

    def test_3_the_tools_of_mon_studio_go_to_its_folder(self):
        install = load('cockpit_install', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py')
        self.assertEqual(set(install.PROJECT_TOOLS), {'lignes-brutes.py', 'question.py'})
        for name in install.PROJECT_TOOLS:
            self.assertTrue((ROOT / 'skills' / 'mon-studio' / 'scripts' / name).is_file(), name)

    def test_4_no_session_is_sent_to_a_foreman(self):
        text = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'question.py').read_text(encoding='utf-8')
        self.assertNotIn('/cockpit:suivre', text)
        self.assertNotIn('ArtifactData', text)
        self.assertNotIn('/foreman-pm', text)

    def test_5_the_way_of_working_moves_to_mon_studio(self):
        install = load('cockpit_install_5', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py')
        self.assertEqual(install.WAY_OF_WORKING.name, 'facon-de-travailler.md')
        self.assertEqual(install.WAY_OF_WORKING.parent, install.MON_STUDIO)

    def test_9_one_rule_for_the_app_folder_on_every_system(self):
        parc = load('cockpit_parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
        question = load('cockpit_question', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'question.py')
        point = load('cockpit_point', ROOT / 'skills' / 'point' / 'scripts' / 'fais_le_point.py')
        cases = [({}, 'darwin'), ({}, 'win32'), ({'APPDATA': '/appdata'}, 'win32'), ({}, 'linux'),
                 ({'XDG_CONFIG_HOME': '/xdg'}, 'linux'), ({'MON_STUDIO_APP_SESSIONS': '/x', 'APPDATA': '/y'}, 'win32'),
                 ({'MON_STUDIO_APP_SESSIONS': '/x'}, 'darwin')]
        for env, plat in cases:
            expected = point.app_sessions_dir(env=env, platform=plat, home='/h')
            self.assertEqual(question.app_sessions_dir(env=env, platform=plat, home='/h'), expected, (env, plat))
            self.assertEqual(parc.dossier_fiches(env=env, plateforme=plat, home='/h'), expected, (env, plat))


class HooksAreSilentWithoutMonStudio(unittest.TestCase):
    """A PM who installs the plugin and never runs /cockpit:mon-studio: no hook says or does anything."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name) / 'home'
        (self.home / '.claude').mkdir(parents=True)
        self.project = pathlib.Path(self.tmp.name) / 'studio'
        self.project.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('MON_STUDIO', 'CLAUDE'))}
        env.update(HOME=str(self.home), CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PROJECT_DIR=str(self.project),
                   CLAUDE_CODE_HOST_SESSION_ID='local_essai')
        return env

    def run_hook(self, command):
        payload = {'session_id': 'cli', 'cwd': str(self.project), 'hook_event_name': 'x',
                   'tool_name': 'mcp__ccd_session_mgmt__clear_session', 'tool_input': {'session_id': 'self'},
                   'prompt': 'fais le point'}
        return subprocess.run(['/bin/sh', '-c', command], input=json.dumps(payload), capture_output=True, text=True,
                              env=self.env(), cwd=str(self.project), timeout=60)

    def test_every_hook_is_gated_on_mon_studio(self):
        for event, matcher, cmd in commands():
            self.assertRegex(cmd, r'^\[ -[fd] "\$HOME/Mon Studio/', (event, matcher))
            self.assertTrue(cmd.endswith('|| true'), (event, matcher))

    def test_every_hook_says_nothing_and_never_fails(self):
        for event, matcher, cmd in commands():
            r = self.run_hook(cmd)
            self.assertEqual((r.returncode, r.stdout), (0, ''), (event, matcher, r.stderr))
        self.assertEqual(list(self.home.iterdir()), [self.home / '.claude'])   # nothing written either

    def test_the_scripts_say_nothing_either_when_called_directly(self):
        r = subprocess.run([sys.executable, str(ROOT / 'hooks' / 'regles.py')], capture_output=True, text=True,
                           env=self.env(), timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        r = subprocess.run([sys.executable, str(ROOT / 'hooks' / 'session_lourde.py')], capture_output=True, text=True,
                           env=self.env(), input=json.dumps({'session_id': 's', 'transcript_path': '/nulle/part'}), timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_every_script_a_hook_runs_is_in_the_plugin(self):
        for event, matcher, cmd in commands():
            for rel in re.findall(r'\$\{CLAUDE_PLUGIN_ROOT\}/(\S+?)"', cmd):
                self.assertTrue((ROOT / rel).is_file(), rel)


class RulesHook(unittest.TestCase):
    """With Mon Studio installed: the default rules, except those the PM's CLAUDE.md already imports; an optional rule
    only when cockpit.json turns it on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        (self.home / 'Mon Studio' / '.parc').mkdir(parents=True)
        (self.home / 'Mon Studio' / '.parc' / 'cockpit.json').write_text('{}')
        (self.home / '.claude').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_rules(self, claude_md=None, *args):
        if claude_md is not None:
            (self.home / '.claude' / 'CLAUDE.md').write_text(claude_md, encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('MON_STUDIO', 'CLAUDE'))}
        env.update(HOME=str(self.home))
        return subprocess.run([sys.executable, str(ROOT / 'hooks' / 'regles.py'), *args], capture_output=True,
                              text=True, env=env, timeout=30).stdout

    def test_the_five_rules_when_none_is_imported(self):
        out = self.run_rules()
        for rule in RULES:
            title = (ROOT / 'regles' / rule).read_text(encoding='utf-8').splitlines()[0]
            self.assertIn(title, out)
        self.assertNotIn('# Heures de publication', out)

    def test_an_optional_rule_when_the_pm_turned_it_on(self):
        (self.home / 'Mon Studio' / '.parc' / 'cockpit.json').write_text(json.dumps({'regles_optionnelles': ['heures-publication']}))
        self.assertIn('# Heures de publication', self.run_rules())
        self.assertNotIn('# Heures de publication', self.run_rules('@heures-publication.md\n'))   # imported: not twice

    def test_a_rule_already_imported_is_not_given_twice(self):
        out = self.run_rules('# Moi\n\n@modeles-effort.md\n@foreman-pm/regles/sessions.md\n')
        self.assertNotIn('# Sessions :', out)
        self.assertNotIn('# Modèle et effort', out)
        self.assertIn('# Livrables', out)
        self.assertIn('# Passation', out)

    def test_nothing_when_every_rule_is_imported(self):
        md = '\n'.join('@' + r for r in ('format-reponses.md', 'livrables.md', 'passation.md',
                                         'modeles-effort.md', 'foreman-pm/regles/sessions.md'))
        self.assertEqual(self.run_rules(md), '')
        listing = self.run_rules(md, '--liste')
        self.assertIn('données : aucune', listing)

    def test_the_hook_command_reads_the_same(self):
        (cmd,) = [c for e, m, c in commands() if 'hooks/regles.py' in c]
        env = {k: v for k, v in os.environ.items() if not k.startswith(('MON_STUDIO', 'CLAUDE'))}
        env.update(HOME=str(self.home), CLAUDE_PLUGIN_ROOT=str(ROOT))
        out = subprocess.run(['/bin/sh', '-c', cmd], capture_output=True, text=True, env=env, timeout=30).stdout
        self.assertIn('Règles de travail du PM', out)


class NoOutsideDependency(unittest.TestCase):
    # Built in pieces, so that this file does not match its own patterns.
    PERSONAL = [re.compile(p) for p in (
        '/Users/' + '(?!pm\\b)[a-z]+[a-z0-9]*/', 'eric' + 'brandenburg', 'GoogleDrive' + '-', 'Mon ' + 'Drive/',
        '@' + 'thetribe' + r'\.io', 'Studio de ' + 'test/projet', 'trial/' + 'foreman')]
    TRIBE = re.compile(r'(?<![\w-])' + 'tribe' + r'[:@]')

    def test_no_path_of_a_pm_computer(self):
        findings = []
        for f in repo_files():
            try:
                text = f.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                findings += [f'{f.relative_to(ROOT)}:{i} {rx.pattern}' for rx in self.PERSONAL if rx.search(line)]
        self.assertEqual(findings, [])

    def test_no_dependency_on_the_tribe_plugin(self):
        manifest = json.loads((ROOT / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['name'], 'cockpit')
        self.assertNotIn('dependencies', manifest)
        findings = []
        for f in repo_files():
            try:
                text = f.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            findings += [f'{f.relative_to(ROOT)}:{i}' for i, line in enumerate(text.splitlines(), 1)
                         if self.TRIBE.search(line)]
        self.assertEqual(findings, [])

    def test_the_skills_are_the_three_announced(self):
        self.assertEqual(sorted(p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md')), ['conflits', 'mon-studio', 'point'])
        allowed = (ROOT / '.github' / 'auto-invocable-skills').read_text(encoding='utf-8')
        self.assertNotRegex(allowed, r'(?m)^mon-studio\b')
        self.assertNotRegex(allowed, r'(?m)^conflits\b')


class InstallCarriesTheMove(unittest.TestCase):
    """What install.py does once for a PM coming from product-kits and the foreman-pm kit 0.7."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        with mock.patch.dict(os.environ, {'HOME': str(self.home)}):
            os.environ.pop('MON_STUDIO', None)
            self.install = load('cockpit_install_move', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py')
        self.claude_md = self.home / 'Mon Studio' / 'CLAUDE.md'
        self.claude_md.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_claude_md_naming_the_old_command_is_replaced(self):
        self.claude_md.write_text(self.install.PREVIOUS_CLAUDE_MD, encoding='utf-8')
        lines = []
        self.install.install_local_files(lines)
        self.assertEqual(self.claude_md.read_text(encoding='utf-8'), self.install.CLAUDE_MD)
        self.assertIn('/cockpit:mon-studio', self.install.CLAUDE_MD)
        self.assertNotIn('/product-kits:cockpit', self.install.CLAUDE_MD)

    def test_a_claude_md_the_pm_changed_stays(self):
        self.claude_md.write_text(self.install.PREVIOUS_CLAUDE_MD + 'Ma note.\n', encoding='utf-8')
        self.install.install_local_files([])
        self.assertTrue(self.claude_md.read_text(encoding='utf-8').endswith('Ma note.\n'))

    def test_the_way_of_working_is_copied_once_never_overwritten(self):
        before = self.home / '.claude' / 'foreman-pm' / 'facon-de-travailler.md'
        before.parent.mkdir(parents=True)
        before.write_text('# Ma façon\n', encoding='utf-8')
        self.install.install_local_files([])
        after = self.home / 'Mon Studio' / 'facon-de-travailler.md'
        self.assertEqual(after.read_text(encoding='utf-8'), '# Ma façon\n')
        self.assertTrue(before.exists())
        after.write_text('# Changée\n', encoding='utf-8')
        self.install.install_local_files([])
        self.assertEqual(after.read_text(encoding='utf-8'), '# Changée\n')


if __name__ == '__main__':
    unittest.main()
