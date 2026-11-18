"""A chantier covers a Studio folder only: one with `.claude/.studio-manifest.json` or `projet/fiche-projet.md`, holding
no other Studio. A folder the connector may not read (macOS refuses the Drive to the app) is a Studio when the snapshot
projets.py writes outside the connector knows it."""
import json
import _isolation
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'skills' / 'mon-studio' / 'scripts'))
import parc  # noqa: E402


class ChantierFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_studio_folder_is_covered(self):
        d = _isolation.make_studio(self.root / 'Alpha')
        self.assertEqual(parc.dossier_du_chantier(str(d)), [str(d)])

    def test_a_folder_without_manifest_is_refused(self):
        (self.root / 'Vrac').mkdir()
        self.assertEqual(parc.dossier_du_chantier(str(self.root / 'Vrac')), [])
        self.assertEqual(parc.dossier_du_chantier(str(self.root / 'absent')), [])

    def test_a_folder_holding_other_studios_is_refused(self):
        _isolation.make_studio(self.root / 'Clients')
        _isolation.make_studio(self.root / 'Clients' / 'Sous' / 'Beta')
        self.assertEqual(parc.dossier_du_chantier(str(self.root / 'Clients')), [])
        self.assertEqual(parc.dossier_du_chantier(str(self.root / 'Clients' / 'Sous' / 'Beta')),
                         [str(self.root / 'Clients' / 'Sous' / 'Beta')])

    def test_the_home_and_nothing_are_refused(self):
        self.assertEqual(parc.dossier_du_chantier(''), [])
        self.assertEqual(parc.dossier_du_chantier(str(parc.HOME)), [])


    def test_a_project_card_alone_marks_a_studio(self):
        d = self.root / 'Gamma'
        (d / 'projet').mkdir(parents=True)
        (d / 'projet' / 'fiche-projet.md').write_text('# Gamma\n')
        self.assertEqual(parc.dossier_du_chantier(str(d)), [str(d)])
        _isolation.make_studio(self.root / 'Groupe' / 'Delta')
        (self.root / 'Groupe' / 'projet').mkdir(parents=True)
        (self.root / 'Groupe' / 'projet' / 'fiche-projet.md').write_text('# Groupe\n')
        self.assertEqual(parc.dossier_du_chantier(str(self.root / 'Groupe')), [])

    @unittest.skipIf(os.geteuid() == 0, 'root reads everything: the refusal cannot be played')
    def test_a_refused_folder_is_a_studio_when_the_snapshot_knows_it(self):
        d = _isolation.make_studio(self.root / 'Drive' / 'Alpha')
        other = _isolation.make_studio(self.root / 'Drive' / 'Beta')
        interne = self.root / 'Mon Studio' / '.parc'
        interne.mkdir(parents=True)
        (interne / 'projets-sources.json').write_text(json.dumps({'version': 1, 'dossiers': {str(d): {'passages': []}}}))
        saved = parc.INTERNE
        parc.INTERNE = interne
        for x in (d, other):
            os.chmod(x, 0)
        try:
            self.assertEqual(parc.dossier_du_chantier(str(d)), [str(d)])
            self.assertEqual(parc.dossier_du_chantier(str(other)), [])   # refused and unknown to the snapshot
        finally:
            for x in (d, other):
                os.chmod(x, 0o755)
            parc.INTERNE = saved

if __name__ == '__main__':
    unittest.main()
