"""Tests: the morning tasks never wait on a permission prompt nobody answers (2026-11-10): python3 -m unittest discover -s tests

On the maintainer's Mac, « Point du matin » ran in permission mode « default », met a Bash prompt for its first command,
waited 1 h 46, was cut and wrote nothing. Scheduled tasks honour ~/.claude/settings.json `permissions.allow`
(https://code.claude.com/docs/en/desktop-scheduled-tasks): `install.py apply` adds the exact rules of the plugin's three
commands, only when missing, after a dated copy; `disable` removes exactly these; the two instructions run these
commands, written exactly as the rules, and no other shell command. `matin.py ecrire` replaces the `mv` the task ran.
Everything lives in a temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
ASSETS = ROOT / 'skills' / 'mon-studio' / 'assets'
PROMPTS = {'preparer': ASSETS / 'consigne-point-du-matin.md', 'verifier': ASSETS / 'consigne-point-du-matin-verif.md'}


def load(name, path, home):
    with mock.patch.dict(os.environ, {'HOME': str(home)}):
        os.environ.pop('MON_STUDIO', None)
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.i = load('install_task_permissions', SCRIPTS / 'install.py', self.home)
        self.i.APP_SESSIONS.mkdir(parents=True, exist_ok=True)
        self.platform = mock.patch.object(self.i.sys, 'platform', 'darwin')
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def run_quiet(self, fn):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            fn()
        return out.getvalue()

    def apply_with_go(self):
        return self.i.main(['apply', '--autorisations'])

    def settings(self):
        return json.loads(self.i.CLAUDE_SETTINGS.read_text(encoding='utf-8'))


class Rules(Base):
    def test_the_rules_are_the_exact_commands_of_the_instructions(self):
        self.assertEqual(self.i.SCRIPT_RULES, [f'Bash(python3 ~/Mon\\ Studio/.parc/matin.py {c})'
                                               for c in ('preparer', 'verifier')]
                         + ['mcp__mon-studio__matin_ecrire', 'mcp__mon-studio__conflits_juger',
                            'mcp__mon-studio__slack_ouvertes', 'mcp__mon-studio__slack_juger'])
        for cmd, prompt in PROMPTS.items():
            text = prompt.read_text(encoding='utf-8')
            run = set(re.findall(r'`(python3 [^`]+)`', text))
            self.assertEqual(run, {f'python3 ~/Mon\\ Studio/.parc/matin.py {cmd}'}, prompt.name)
            self.assertIn(f'Bash(python3 ~/Mon\\ Studio/.parc/matin.py {cmd})', self.i.SCRIPT_RULES)
            self.assertIn('Aucune autre commande du shell', text)
            for forbidden in ('`cat`', '`jq`', '`grep`', '`mv`', '`|`', '`<<`'):
                self.assertIn(forbidden, text, 'named as forbidden')
            self.assertNotIn('renomme-le', text)

    def test_the_instructions_use_no_file_tool(self):
        # 2026-11-10: a file tool outside the task's folder waits on a prompt; the point goes through matin_ecrire.
        for prompt in PROMPTS.values():
            text = prompt.read_text(encoding='utf-8')
            self.assertIn('Aucun outil de fichier', text, prompt.name)
            self.assertIn("l'outil `matin_ecrire` du connecteur mon-studio", text, prompt.name)
            self.assertIn("n'est pas dans tes outils : ", text, 'no connector: the task stops, writes nothing')
            for gone in ('matin.json.tmp', "l'outil d'écriture de fichier", "l'outil de lecture de fichier",
                         'brouillons.json', 'matin.py ecrire'):
                self.assertNotIn(gone, text, (prompt.name, gone))

    def test_apply_with_go_removes_the_former_ecrire_rule(self):
        self.i.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.i.CLAUDE_SETTINGS.write_text(json.dumps({'permissions': {'allow': ['Bash(ls *)'] + self.i.FORMER_RULES}}),
                                          encoding='utf-8')
        self.run_quiet(self.apply_with_go)
        self.assertEqual(self.settings()['permissions']['allow'], ['Bash(ls *)'] + self.i.SCRIPT_RULES)
        self.run_quiet(lambda: self.i.main(['disable']))
        self.assertEqual(self.settings()['permissions']['allow'], ['Bash(ls *)'])

    def test_apply_adds_the_rules_to_a_missing_file(self):
        self.assertEqual(self.i.status()['scriptRules'], 'missing')
        self.run_quiet(self.apply_with_go)
        # Since 2026-11-26 every apply also denies the sessions the page's three action tools: that is the `deny` list.
        self.assertEqual(self.settings(), {'permissions': {'deny': self.i.ACTION_TOOLS, 'allow': self.i.SCRIPT_RULES}})
        s = self.i.status()
        self.assertEqual(s['scriptRules'], 'present')
        self.assertNotIn('allow_scripts', s['todo'])
        self.assertIn('Bash(python3 ~/Mon\\\\ Studio/.parc/matin.py preparer)',
                      self.i.CLAUDE_SETTINGS.read_text(encoding='utf-8'), 'JSON escapes the backslash')

    def test_apply_keeps_the_file_and_adds_only_the_missing_rules_after_a_copy(self):
        before = {'model': 'opus', 'permissions': {'allow': ['Bash(ls *)', self.i.SCRIPT_RULES[0]], 'deny': ['Read(x)']},
                  'hooks': {'Stop': []}}
        self.i.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.i.CLAUDE_SETTINGS.write_text(json.dumps(before), encoding='utf-8')
        out = self.run_quiet(self.apply_with_go)
        after = self.settings()
        self.assertEqual(after['permissions']['allow'], ['Bash(ls *)'] + self.i.SCRIPT_RULES)
        self.assertEqual({k: v for k, v in after.items() if k != 'permissions'}, {'model': 'opus', 'hooks': {'Stop': []}})
        self.assertEqual(after['permissions']['deny'], ['Read(x)'] + self.i.ACTION_TOOLS)
        backups = list(self.i.CLAUDE_SETTINGS.parent.glob('settings.json.avant-mon-studio-*'))
        self.assertEqual(len(backups), 2, 'one copy before each of the two changes (deny, then allow)')
        self.assertIn(before, [json.loads(b.read_text(encoding='utf-8')) for b in backups])
        self.assertIn('autorisé   5 gestes du point du matin', out)
        self.run_quiet(self.apply_with_go)
        self.assertEqual(len(list(self.i.CLAUDE_SETTINGS.parent.glob('settings.json.avant-mon-studio-*'))), 2,
                         'nothing to add: no copy, no write')

    def test_an_unreadable_file_is_never_written(self):
        self.i.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.i.CLAUDE_SETTINGS.write_text('{oops', encoding='utf-8')
        self.assertEqual(self.i.status()['scriptRules'], 'unreadable')
        self.assertIn('illisible', '\n'.join(self.i.step('matin')))
        out = self.run_quiet(self.apply_with_go)
        self.assertEqual(self.i.CLAUDE_SETTINGS.read_text(encoding='utf-8'), '{oops')
        self.assertIn('laissé', out)

    def test_the_morning_step_announces_it_in_one_line_and_the_plan_never(self):
        # 2026-11-15: the installation lays the base only; the rules come with the morning step's go.
        self.assertFalse(any('autorisation' in l and 'réglages Claude' in l for l in self.i.plan()))
        lines = [l for l in self.i.step('matin') if 'autorisations pour ces tâches dans tes réglages Claude' in l]
        self.assertEqual(len(lines), 1)
        self.run_quiet(self.apply_with_go)
        self.assertFalse(any('autorisations pour ces tâches' in l for l in self.i.step('matin')), 'already there: not announced')

    def test_repair_never_touches_the_settings(self):
        # 2026-11-10: `repair` added the rules on the maintainer's Mac without his go; only `apply` does, after it.
        self.assertFalse(self.i.CLAUDE_SETTINGS.exists())
        out = self.run_quiet(lambda: self.i.main(['repair']))
        self.assertEqual(self.settings(), {'permissions': {'deny': self.i.ACTION_TOOLS}}, out)  # the refusal only
        self.assertNotIn('autorisé', out)
        self.i.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.i.CLAUDE_SETTINGS.write_text(json.dumps({'permissions': {'allow': ['Bash(ls *)']}}), encoding='utf-8')
        self.run_quiet(lambda: self.i.main(['repair']))
        self.assertEqual(self.settings(), {'permissions': {'deny': self.i.ACTION_TOOLS, 'allow': ['Bash(ls *)']}})
        self.assertNotIn('allow_scripts', self.i.status()['todo'], 'no morning task yet: nothing asked')
        self.i.MORNING_TASK.parent.mkdir(parents=True, exist_ok=True)
        self.i.MORNING_TASK.write_text('x', encoding='utf-8')
        self.assertIn('allow_scripts', self.i.status()['todo'])

    def test_apply_without_the_flag_never_touches_the_settings(self):
        # The hook's update at each version (sync.py) and the todos `update` and `remove_server` run a bare `apply`:
        # a rule the PM removed never comes back without his go (2026-11-10, independent review).
        self.run_quiet(self.apply_with_go)
        self.i.CLAUDE_SETTINGS.write_text(json.dumps({'permissions': {'allow': []}}), encoding='utf-8')
        out = self.run_quiet(lambda: self.i.main(['apply']))
        self.run_quiet(self.i.apply)
        self.assertEqual(self.settings(), {'permissions': {'allow': [], 'deny': self.i.ACTION_TOOLS}}, out)
        sync = (SCRIPTS / 'sync.py').read_text(encoding='utf-8')
        self.assertIn("str(INSTALL), 'apply']", sync, 'the hook runs a bare apply')

    def test_the_skill_passes_the_flag_only_after_a_go(self):
        skill = (ROOT / 'skills' / 'mon-studio' / 'SKILL.md').read_text(encoding='utf-8')
        flagged = [l for l in skill.splitlines() if '--autorisations' in l]
        self.assertEqual(len([l for l in flagged if 'go' in l.lower()]), len(flagged))
        for todo in ('update', 'remove_server'):
            entry = next(l for l in skill.splitlines() if l.strip().startswith(f'- `{todo}`'))
            self.assertNotIn('--autorisations', entry, todo)

    def test_disable_removes_exactly_these_rules(self):
        self.i.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.i.CLAUDE_SETTINGS.write_text(json.dumps({'permissions': {'allow': ['Bash(ls *)']}}), encoding='utf-8')
        self.run_quiet(self.apply_with_go)
        out = self.run_quiet(self.i.disable)
        self.assertEqual(self.settings(), {'permissions': {'allow': ['Bash(ls *)'], 'deny': []}})
        self.assertIn('retiré     les autorisations des tâches du point du matin', out)

    def test_status_asks_for_the_rules_when_removed_after_install(self):
        self.run_quiet(self.apply_with_go)
        self.i.CLAUDE_SETTINGS.write_text(json.dumps({'permissions': {'allow': []}}), encoding='utf-8')
        self.i.MORNING_CHECK_TASK.parent.mkdir(parents=True, exist_ok=True)
        self.i.MORNING_CHECK_TASK.write_text('x', encoding='utf-8')
        s = self.i.status()
        self.assertEqual(s['scriptRules'], 'missing')
        self.assertIn('allow_scripts', s['todo'])


class FirstRunGesture(unittest.TestCase):
    """Right after creating or changing a task, the PM runs it once and answers « Toujours autoriser »."""
    def test_each_task_entry_of_the_skill_asks_for_the_gesture(self):
        skill = (ROOT / 'skills' / 'mon-studio' / 'SKILL.md').read_text(encoding='utf-8')
        for todo in ('create_morning_task', 'create_morning_check_task', 'set_task_models', 'update_morning_task'):
            entry = next(l for l in skill.splitlines() if l.strip().startswith(f'- `{todo}`'))
            self.assertIn('Exécuter maintenant', entry, todo)
            self.assertIn('Toujours autoriser', entry, todo)
        for doc in ('README.md', 'docs/consigne-point-du-matin.md'):
            text = (ROOT / doc).read_text(encoding='utf-8')
            self.assertIn('« Toujours autoriser »', text, doc)


class Ecrire(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = pathlib.Path(self.tmp.name) / 'Mon Studio'
        self.studio.mkdir()
        with mock.patch.dict(os.environ, {'MON_STUDIO': str(self.studio)}):
            self.m = load('matin_ecrire', SCRIPTS / 'matin.py', pathlib.Path(self.tmp.name))
        self.m.parc.SORTIE = self.studio

    def test_a_valid_point_replaces_matin_json(self):
        (self.studio / 'matin.json').write_text('{"genere_le": "2026-11-09T07:30:00"}', encoding='utf-8')
        (self.studio / 'matin.json.tmp').write_text('reste', encoding='utf-8')   # left by an older version: it goes
        self.assertEqual(self.m.ecrire('{"genere_le": "2026-11-10T07:31:00", "a": "l\'été {\\"x\\"}"}'),
                         (True, 'matin.json écrit'))
        self.assertFalse((self.studio / 'matin.json.tmp').exists())
        got = json.loads((self.studio / 'matin.json').read_text(encoding='utf-8'))
        self.assertEqual(got, {'genere_le': '2026-11-10T07:31:00', 'a': 'l\'été {"x"}'})

    def test_a_bad_point_is_refused_and_matin_json_kept(self):
        (self.studio / 'matin.json').write_text('ancien', encoding='utf-8')
        for bad in ('', '{oops', '[1]', '{"genere_le": "hier"}'):
            ok, why = self.m.ecrire(bad)
            self.assertFalse(ok, bad)
            self.assertEqual((self.studio / 'matin.json').read_text(encoding='utf-8'), 'ancien')
        with contextlib.redirect_stdout(io.StringIO()) as out, mock.patch.object(self.m.sys, 'stdin', io.StringIO('{oops')):
            self.assertEqual(self.m.main(['ecrire']), 2)
        self.assertTrue(out.getvalue().startswith('Refusé : '))

    def test_ecrire_reads_the_point_on_its_standard_input(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                mock.patch.object(self.m.sys, 'stdin', io.StringIO('{"genere_le": "2026-11-10T07:31:00"}')):
            self.assertEqual(self.m.main(['ecrire']), 0)
        self.assertEqual(out.getvalue().strip(), 'matin.json écrit')
        self.assertIn('2026-11-10', (self.studio / 'matin.json').read_text(encoding='utf-8'))

    def test_preparer_and_verifier_give_the_time_and_clear_a_stale_file(self):
        (self.studio / 'matin.json.tmp').write_text('{oops', encoding='utf-8')
        r = self.m.preparer(maintenant=1793950000)
        self.assertFalse((self.studio / 'matin.json.tmp').exists())
        self.assertEqual(r['maintenant'][:10], r['aujourdhui'])
        self.assertRegex(r['maintenant'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$')
        for prompt in PROMPTS.values():
            text = prompt.read_text(encoding='utf-8')
            self.assertIn('`maintenant`', text, prompt.name)
            self.assertNotIn("heure du système", text, prompt.name)


if __name__ == '__main__':
    unittest.main()
