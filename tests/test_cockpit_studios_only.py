"""The PM's working rules and their controls apply to sessions opened in a Studio only (hooks/perimetre.py)."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / 'hooks'
sys.path.insert(0, str(HOOKS))
import perimetre  # noqa: E402

HOST = 'local_00000000-0000-0000-0000-0000000000a1'


class StudiosOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(os.path.realpath(self.tmp.name))
        self.parc = self.home / 'Mon Studio' / '.parc'
        self.parc.mkdir(parents=True)
        self.etat = {'page': 'x'}
        self.save()
        self.studio = self.home / 'Drive' / 'Studio - Alpha'
        (self.studio / 'sous' / 'dossier').mkdir(parents=True)
        self.dev = self.home / 'code' / 'un-plugin'
        self.dev.mkdir(parents=True)
        self.old = {k: os.environ.get(k) for k in ('HOME', 'MON_STUDIO', 'CLAUDE_PROJECT_DIR')}
        os.environ['HOME'] = str(self.home)
        os.environ.pop('MON_STUDIO', None)
        os.environ.pop('CLAUDE_PROJECT_DIR', None)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def save(self):
        (self.parc / 'cockpit.json').write_text(json.dumps(self.etat), encoding='utf-8')

    def known(self, *folders):
        (self.home / 'Mon Studio' / 'projets.json').write_text(
            json.dumps({'studios': [{'nom': 'Alpha', 'dossier': str(f)} for f in folders]}), encoding='utf-8')

    # --- the definition -------------------------------------------------------------------------------------
    def test_session_in_a_known_studio(self):
        self.known(self.studio)
        self.assertTrue(perimetre.session_de_studio(str(self.studio)))

    def test_session_in_a_subfolder_of_a_studio(self):
        self.known(self.studio)
        self.assertTrue(perimetre.session_de_studio(str(self.studio / 'sous' / 'dossier')))

    def test_session_in_a_worktree_of_a_studio(self):
        self.known(self.studio)
        wt = self.studio / '.claude' / 'worktrees' / 'essai'
        self.assertTrue(perimetre.session_de_studio(str(wt)))

    def test_session_outside_any_studio(self):
        self.known(self.studio)
        self.assertFalse(perimetre.session_de_studio(str(self.dev)))
        self.assertFalse(perimetre.session_de_studio(str(self.home)))

    def test_studio_unknown_to_mon_studio_but_with_a_manifest(self):
        self.known()
        other = self.home / 'ailleurs' / 'Studio - Beta'
        (other / 'x').mkdir(parents=True)
        self.assertFalse(perimetre.session_de_studio(str(other / 'x')))
        _isolation.make_studio(other)
        self.assertTrue(perimetre.session_de_studio(str(other / 'x')))

    def test_mon_studio_folder_itself(self):
        self.known()
        self.assertTrue(perimetre.session_de_studio(str(self.home / 'Mon Studio')))

    def test_project_dir_variable_when_the_input_has_no_folder(self):
        self.known(self.studio)
        os.environ['CLAUDE_PROJECT_DIR'] = str(self.studio)
        self.assertTrue(perimetre.session_de_studio(None))
        os.environ['CLAUDE_PROJECT_DIR'] = str(self.dev)
        self.assertFalse(perimetre.session_de_studio(None))

    def test_extra_folder_of_the_list(self):
        self.known(self.studio)
        self.etat['regles_dossiers'] = [str(self.dev)]
        self.save()
        self.assertTrue(perimetre.session_de_studio(str(self.dev)))
        self.assertTrue(perimetre.session_de_studio(str(self.dev / 'src')))
        self.assertFalse(perimetre.session_de_studio(str(self.home / 'code' / 'autre')))

    def test_the_home_folder_in_the_list_is_not_everything(self):
        self.known()
        self.etat['regles_dossiers'] = [str(self.home)]
        self.save()
        self.assertFalse(perimetre.session_de_studio(str(self.dev)))

    def test_switch_back_to_everywhere(self):
        self.known(self.studio)
        self.etat['regles_partout'] = True
        self.save()
        self.assertTrue(perimetre.session_de_studio(str(self.dev)))

    def test_unreadable_files_keep_the_rules(self):
        (self.home / 'Mon Studio' / 'projets.json').write_text('{pas du json', encoding='utf-8')
        self.assertTrue(perimetre.session_de_studio(str(self.dev)))
        self.known(self.studio)
        (self.parc / 'cockpit.json').write_text('[1, 2', encoding='utf-8')
        self.assertTrue(perimetre.session_de_studio(str(self.dev)))

    def test_unusable_folder_keeps_the_rules(self):
        self.known(self.studio)
        self.assertTrue(perimetre.session_de_studio(12345))

    # --- the hooks ---------------------------------------------------------------------------------------------
    def run_py(self, script, payload, *args):
        env = dict(os.environ, HOME=str(self.home), CLAUDE_CODE_HOST_SESSION_ID=HOST)
        env.pop('MON_STUDIO', None)
        return subprocess.run([sys.executable, str(HOOKS / script), *args], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30, cwd=str(self.home))

    def test_garde_exit_codes(self):
        self.known(self.studio)
        self.assertEqual(self.run_py('perimetre.py', {'cwd': str(self.studio)}, '--garde').returncode, 0)
        self.assertEqual(self.run_py('perimetre.py', {'cwd': str(self.dev)}, '--garde').returncode, 1)
        self.etat['regles_partout'] = True
        self.save()
        self.assertEqual(self.run_py('perimetre.py', {'cwd': str(self.dev)}, '--garde').returncode, 0)

    def test_rules_given_in_a_studio_not_elsewhere(self):
        self.known(self.studio)
        self.assertIn('Règles de travail du PM', self.run_py('regles.py', {'cwd': str(self.studio)}).stdout)
        self.assertEqual(self.run_py('regles.py', {'cwd': str(self.dev)}).stdout, '')
        self.etat['regles_dossiers'] = [str(self.dev)]
        self.save()
        self.assertIn('Règles de travail du PM', self.run_py('regles.py', {'cwd': str(self.dev)}).stdout)

    def test_agent_without_model_refused_in_a_studio_only(self):
        self.known(self.studio)
        call = {'tool_name': 'Agent', 'tool_input': {'description': 'x', 'prompt': 'y'}}
        self.assertIn('deny', self.run_py('modele_lancement.py', dict(call, cwd=str(self.studio))).stdout)
        self.assertEqual(self.run_py('modele_lancement.py', dict(call, cwd=str(self.dev))).stdout, '')

    def test_heavy_session_told_in_a_studio_only(self):
        self.known(self.studio)
        t = self.home / 't.jsonl'
        t.write_text(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 400000}}}) + '\n',
                     encoding='utf-8')
        base = {'session_id': 's1', 'transcript_path': str(t)}
        self.assertEqual(self.run_py('session_lourde.py', dict(base, cwd=str(self.dev))).stdout, '')
        self.assertIn('tokens', self.run_py('session_lourde.py', dict(base, cwd=str(self.studio))).stdout)

    def test_hooks_json_guards_the_format_reminder(self):
        data = json.loads((HOOKS / 'hooks.json').read_text(encoding='utf-8'))
        cmds = [h['command'] for g in data['hooks']['UserPromptSubmit'] for h in g['hooks'] if 'echo' in h['command']]
        self.assertEqual(len(cmds), 1)
        self.assertIn('perimetre.py" --garde', cmds[0])
        self.assertLess(cmds[0].index('--garde'), cmds[0].index('echo'))


if __name__ == '__main__':
    unittest.main()
