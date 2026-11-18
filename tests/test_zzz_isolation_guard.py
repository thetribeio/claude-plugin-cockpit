"""Guard: the suite runs on a temporary HOME and never opens the real app folder, ~/.claude or ~/Mon Studio."""
import os
import pathlib
import unittest

import _isolation


class IsolationGuard(unittest.TestCase):
    def test_home_is_a_temporary_folder(self):
        home = pathlib.Path.home().resolve()
        self.assertEqual(str(home), _isolation.TEST_HOME)
        self.assertNotEqual(str(home), os.path.realpath(_isolation.REAL_HOME))

    def test_no_override_points_to_the_real_folders(self):
        for name, value in os.environ.items():
            if name.startswith('MON_STUDIO') or name == 'CLAUDE_CONFIG_DIR':
                self.assertTrue(value.startswith(_isolation.TEST_HOME) or not value.startswith(_isolation.REAL_HOME), name)

    def test_no_test_opened_a_real_path(self):
        self.assertEqual(_isolation.VIOLATIONS, [])


if __name__ == '__main__':
    unittest.main()
