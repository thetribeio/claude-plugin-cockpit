"""Scope of the connector tools: `ouvrir` is not read-only, a session-launched instance (CLAUDE_PROJECT_DIR) reads and
opens only inside its own Studio and never calls `decider` nor `repondre` (page only). Synthetic folders only."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import os
import unittest
from unittest import mock

from test_cockpit_permission_hook import Base, load_connector


class Scope(Base):
    def setUp(self):
        super().setUp()
        self.m = load_connector(self.mon_studio, self.root / 'app', self.root / 'tr')
        self.p = self.m.charger_projets()
        patcher = mock.patch.object(self.p, 'lire_fichier', lambda d, f, metas=None: {'dossier': d, 'fichier': f, 'texte': 'x'})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.m.AUTORISATIONS.arreter)

    def session(self, dossier):
        patcher = mock.patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': dossier})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ouvrir_is_declared_as_writing(self):
        ann = {t['name']: t['annotations'] for t in self.m.OUTILS}['ouvrir']
        self.assertIs(ann['readOnlyHint'], False)
        self.assertIs(ann['destructiveHint'], False)

    def test_the_page_instance_reads_any_known_studio(self):
        os.environ.pop('CLAUDE_PROJECT_DIR', None)
        self.assertEqual(self.m.lire({'dossier': '/studios/B', 'fichier': 'a.md'})['dossier'], '/studios/B')

    def test_a_session_reads_only_its_own_studio(self):
        self.session('/studios/A')
        self.assertEqual(self.m.lire({'dossier': '/studios/A', 'fichier': 'a.md'})['dossier'], '/studios/A')
        with self.assertRaises(ValueError):
            self.m.lire({'dossier': '/studios/B', 'fichier': 'a.md'})

    def test_a_session_opens_a_file_only_in_its_own_studio(self):
        self.session('/studios/A')
        with mock.patch.object(self.m, 'ouvrir_fichier') as o:
            with self.assertRaises(ValueError):
                self.m.ouvrir({'dossier': '/studios/B', 'fichier': 'a.md'})
            o.assert_not_called()
            self.m.ouvrir({'dossier': '/studios/A', 'fichier': 'a.md'})
            o.assert_called_once()

    def test_a_session_never_calls_decider_nor_repondre(self):
        self.session('/studios/A')
        with self.assertRaises(ValueError) as e:
            self.m.decider({'id': 'a' * 32, 'decision': 'allow'})
        self.assertIn('page', str(e.exception))
        with self.assertRaises(ValueError) as e:
            self.m.repondre_attente({'id': 'a' * 32, 'choix': 'go'})
        self.assertIn('page', str(e.exception))


if __name__ == '__main__':
    unittest.main()
