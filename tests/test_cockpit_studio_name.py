"""Tests of the Studio name Mon Studio gives a session's folder: python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)


class StudioName(unittest.TestCase):
    def test_studio_folder_is_lightened(self):
        self.assertEqual(parc.nom_projet('/Drive/Clients/Studio - Projet Alpha'), 'Projet Alpha')
        self.assertEqual(parc.nom_projet('/Drive/Clients/Studio-Projet-Alpha'), 'Projet Alpha')

    def test_app_worktree_belongs_to_its_repository(self):
        repo = '/Users/pm/Documents/plugins/product-kits'
        self.assertEqual(parc.nom_projet(repo + '/.claude/worktrees/elated-mestorf-f04140'), parc.nom_projet(repo))
        self.assertEqual(parc.nom_projet(repo + '/.claude/worktrees/elated-mestorf-f04140/skills'), parc.nom_projet(repo))

    def test_worktree_of_a_studio_keeps_the_studio_name(self):
        self.assertEqual(parc.nom_projet('/Drive/Clients/Studio - Projet Alpha/.claude/worktrees/quirky-elbakyan-fb2666'),
                         'Projet Alpha')

    def test_session_title_beside_its_studio_drops_the_studio_prefix(self):
        self.assertEqual(parc.titre_lien('Alpha · Compte rendu du kick-off', 'Projet Alpha'), 'Compte rendu du kick-off')
        self.assertEqual(parc.titre_lien('projet alpha · Backlog', 'Projet Alpha'), 'Backlog')
        self.assertEqual(parc.titre_lien('Beta · Backlog', 'Projet Alpha'), 'Beta · Backlog')
        self.assertEqual(parc.titre_lien('Alpha · ', 'Projet Alpha'), 'Alpha · ')
        self.assertEqual(parc.titre_lien('Alpha · Backlog [lot 2]'), 'Alpha · Backlog (lot 2)')
        self.assertEqual(parc.titre_lien(None, 'Projet Alpha'), 'Session sans titre')

    def test_other_folders_are_untouched(self):
        self.assertEqual(parc.nom_projet('/Users/pm/Documents/CLIENTS/SEO'), 'SEO')
        self.assertEqual(parc.nom_projet('/Users/pm/.claude/worktrees'), 'worktrees')


if __name__ == '__main__':
    unittest.main()
