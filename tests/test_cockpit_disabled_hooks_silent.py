"""Once Mon Studio is disabled, every hook of hooks.json stays silent and runs nothing (rules, reminder line, heavy
session, question register, notices, project snapshot...): each one carries the same guard on cockpit.json."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / 'hooks' / 'hooks.json'


GUARD = ('[ -f \"$HOME/Mon Studio/.parc/cockpit.json\" ] && ! grep -q \'"disabled": true\' '
         '\"$HOME/Mon Studio/.parc/cockpit.json\" && ').replace('\\"', '"')
STUB = 'import os, sys\nopen(os.path.join(os.environ["HOME"], "ran.txt"), "a").write(" ".join([__file__] + sys.argv[1:]) + "\\n")\n'


def commands():
    """Every hook command of hooks.json, guarded or not: a new hook cannot slip past the test."""
    data = json.loads(HOOKS.read_text(encoding='utf-8'))
    for groups in data['hooks'].values():
        for group in groups:
            for hook in group['hooks']:
                yield hook['command']


class DisabledHooksSilent(unittest.TestCase):
    def run_all(self, state):
        with tempfile.TemporaryDirectory() as home:
            parc = Path(home) / 'Mon Studio' / '.parc'
            parc.mkdir(parents=True)
            (parc / 'cockpit.json').write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
            env = dict(os.environ, HOME=home, CLAUDE_PLUGIN_ROOT='/nonexistent')
            out = ''
            for command in commands():
                out += subprocess.run(['bash', '-c', command], env=env, input='{}', capture_output=True,
                                      text=True, timeout=20).stdout
            return out

    def test_every_hook_starts_with_the_disabled_guard(self):
        listed = list(commands())
        self.assertGreaterEqual(len(listed), 10)
        for command in listed:
            self.assertTrue(command.startswith(GUARD), command)

    def run_stubs(self, state):
        """Runs every hook against a plugin root whose scripts only note that they ran; returns what ran."""
        with tempfile.TemporaryDirectory() as home:
            ms = Path(home) / 'Mon Studio'
            (ms / '.parc').mkdir(parents=True)
            (ms / 'chantiers').mkdir()
            (ms / '.parc' / 'projets.py').write_text('')
            (ms / 'projets.json').write_text('{}')
            (ms / '.parc' / 'cockpit.json').write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
            root = Path(home) / 'plugin'
            for command in commands():
                for rel in re.findall(r'\$\{CLAUDE_PLUGIN_ROOT\}/([\w/.-]+\.py)', command):
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root / rel).write_text(STUB)
            env = dict(os.environ, HOME=home, CLAUDE_PLUGIN_ROOT=str(root))
            for command in commands():
                subprocess.run(['bash', '-c', command], env=env, input='{}', capture_output=True, text=True, timeout=20)
            ran = Path(home) / 'ran.txt'
            return ran.read_text().splitlines() if ran.exists() else []

    def test_no_hook_runs_anything_once_disabled(self):
        self.assertGreaterEqual(len(self.run_stubs({'page': 'x'})), len(list(commands())) - 1)   # all but the echo
        self.assertEqual(self.run_stubs({'page': 'x', 'disabled': True}), [])

    def test_reminder_line_silent_once_disabled(self):
        self.assertIn('À trancher', self.run_all({'page': 'x'}))
        self.assertEqual(self.run_all({'page': 'x', 'disabled': True}), '')


if __name__ == '__main__':
    unittest.main()
