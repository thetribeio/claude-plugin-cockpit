"""Tests of .github/scripts/check_skills.py: python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_skills', ROOT / '.github' / 'scripts' / 'check_skills.py')
check_skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_skills)

LOCKED = '---\nname: demo\ndescription: Un skill.\ndisable-model-invocation: true\n---\n\n# Demo\n'


class CheckSkills(unittest.TestCase):
    def plugin(self, skills, allowed=None):
        root = pathlib.Path(tempfile.mkdtemp())
        for name, text in skills.items():
            (root / 'skills' / name).mkdir(parents=True)
            (root / 'skills' / name / 'SKILL.md').write_text(text, encoding='utf-8')
        if allowed is not None:
            (root / '.github').mkdir()
            (root / '.github' / 'auto-invocable-skills').write_text(allowed, encoding='utf-8')
        return root

    def test_this_repository_passes(self):
        self.assertEqual(check_skills.check(ROOT), [])

    def test_locked_skill_passes(self):
        self.assertEqual(check_skills.check(self.plugin({'demo': LOCKED})), [])

    def test_missing_lock_fails(self):
        errors = check_skills.check(self.plugin({'demo': '---\nname: demo\ndescription: Un skill.\n---\n'}))
        self.assertEqual(len(errors), 1)
        self.assertIn('il manque « disable-model-invocation: true »', errors[0])

    def test_misspelled_lock_fails_twice(self):
        text = LOCKED.replace('disable-model-invocation', 'disable_model_invocation')
        errors = check_skills.check(self.plugin({'demo': text}))
        self.assertTrue(any('champ inconnu « disable_model_invocation »' in e for e in errors))
        self.assertTrue(any('il manque' in e for e in errors))

    def test_false_value_fails(self):
        errors = check_skills.check(self.plugin({'demo': LOCKED.replace(': true', ': false')}))
        self.assertIn('il doit valoir « true »', errors[0])

    def test_quoted_true_passes(self):
        self.assertEqual(check_skills.check(self.plugin({'demo': LOCKED.replace(': true', ': "true"')})), [])

    def test_declared_exception_passes_but_still_checks_fields(self):
        text = '---\nname: demo\ndescription: Un skill.\nmodle: opus\n---\n'
        errors = check_skills.check(self.plugin({'demo': text}, allowed='demo  # se déclenche sur « revue de sprint »\n'))
        self.assertEqual(len(errors), 1)
        self.assertIn('champ inconnu « modle »', errors[0])

    def test_nested_keys_are_not_top_level_fields(self):
        text = LOCKED.replace('---\n\n', 'metadata:\n  owner: pm\n  custom-key: x\n---\n\n')
        self.assertEqual(check_skills.check(self.plugin({'demo': text})), [])

    def test_missing_header_fails(self):
        errors = check_skills.check(self.plugin({'demo': '# Demo\n'}))
        self.assertIn("pas d'en-tête", errors[0])


if __name__ == '__main__':
    unittest.main()
