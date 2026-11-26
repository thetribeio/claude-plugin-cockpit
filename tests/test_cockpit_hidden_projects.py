"""Tests: projects the PM no longer follows (`projets_masques` in cockpit.json, 2026-11-24) are never read by Mon
Studio, while their sessions stay in the app. python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

HIDDEN = '/Users/pm/Clients/SEO'


def card(sid, cwd):
    return {'sessionId': sid, 'cwd': cwd, 'title': sid}


class HiddenProjects(unittest.TestCase):
    def setUp(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.app, self.interne = tmp / 'app' / 'a' / 'b', tmp / 'parc'
        self.app.mkdir(parents=True)
        self.interne.mkdir()
        sessions = {'local_seo': HIDDEN, 'local_wt': HIDDEN + '/.claude/worktrees/x', 'local_sub': HIDDEN + '/lot',
                    'local_seo_ef': HIDDEN + ' EF', 'local_alpha': '/Users/pm/Clients/Alpha'}
        for sid, cwd in sessions.items():
            (self.app / f'{sid}.json').write_text(json.dumps(card(sid, cwd)))
        patches = [mock.patch.object(parc, 'APP', tmp / 'app'), mock.patch.object(parc, 'INTERNE', self.interne)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def ids(self, masques):
        (self.interne / 'cockpit.json').write_text(json.dumps({'projets_masques': masques}))
        return sorted(m['id'] for m in parc.fiches({'fiches': {}}))

    def test_nothing_hidden_by_default(self):
        self.assertEqual(len(self.ids([])), 5)

    def test_a_hidden_folder_takes_its_worktrees_and_subfolders_not_its_namesakes(self):
        self.assertEqual(self.ids([HIDDEN]), ['local_alpha', 'local_seo_ef'])

    def test_trailing_slash(self):
        self.assertEqual(self.ids([HIDDEN + '/']), ['local_alpha', 'local_seo_ef'])

    def test_unhidden_comes_back(self):
        self.ids([HIDDEN])
        self.assertEqual(len(self.ids([])), 5)


if __name__ == '__main__':
    unittest.main()
