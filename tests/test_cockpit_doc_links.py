"""Tests: user-facing files point only to documents the repository ships: python3 -m unittest discover -s tests

The internal journal (docs/mon-studio.md) left the repository; the README and the skills must not send a reader
there, nor promise the retired foreman's tools."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DocLinks(unittest.TestCase):
    def test_every_docs_pointer_exists(self):
        files = [ROOT / 'README.md'] + sorted((ROOT / 'skills').glob('*/SKILL.md'))
        for f in files:
            for target in re.findall(r'`(docs/[\w.-]+\.md)`', f.read_text(encoding='utf-8')):
                self.assertTrue((ROOT / target).is_file(), f'{f.relative_to(ROOT)} points to {target}, absent')

    def test_no_foreman_tools_promised_at_disable(self):
        self.assertNotIn('outils du contremaître', (ROOT / 'skills' / 'mon-studio' / 'SKILL.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
