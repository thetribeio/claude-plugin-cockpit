"""Tests of skills/mon-studio/scripts/archive_check.py: python3 -m unittest discover -s tests."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'skills' / 'mon-studio' / 'scripts' / 'archive_check.py'


def run(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          capture_output=True, text=True, check=True).stdout


class ArchiveCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        run(self.repo, 'init', '-b', 'main')
        (self.repo / 'a.md').write_text('un\ndeux\n')
        run(self.repo, 'add', '.')
        run(self.repo, 'commit', '-m', 'base')

    def tearDown(self):
        self.tmp.cleanup()

    def worktree(self, branch):
        wt = self.root / branch
        run(self.repo, 'worktree', 'add', '-b', branch, str(wt))
        return wt

    def commit(self, wt, text, name='a.md'):
        with open(wt / name, 'a') as f:
            f.write(text)
        run(wt, 'add', '.')
        run(wt, 'commit', '-m', 'work ' + text.strip())

    def check(self, *wts):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.repo), *map(str, wts)], capture_output=True, text=True)

    def test_a_branch_merged_by_a_merge_commit_can_be_archived(self):
        wt = self.worktree('feat')
        self.commit(wt, 'trois\n')
        run(self.repo, 'merge', '--no-ff', '-m', 'merge feat', 'feat')
        r = self.check(wt)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('déjà dans l\'historique de main', r.stdout)

    def test_a_squash_merge_passes_too(self):
        wt = self.worktree('feat')
        self.commit(wt, 'trois\n')
        self.commit(wt, 'quatre\n')
        run(self.repo, 'merge', '--squash', 'feat')
        run(self.repo, 'commit', '-m', 'squash feat')
        r = self.check(wt)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('toute la branche est entrée dans main en', r.stdout)

    def test_main_reworking_the_lines_afterwards_does_not_count_as_a_gap(self):
        wt = self.worktree('feat')
        self.commit(wt, 'trois\n')
        run(self.repo, 'merge', '--no-ff', '-m', 'merge feat', 'feat')
        (self.repo / 'a.md').write_text('un\ndeux\nreprise\n')   # main drops the branch's line later
        run(self.repo, 'commit', '-am', 'rework')
        r = self.check(wt)
        self.assertEqual(r.returncode, 0, r.stdout)   # a naive diff with main as it is now would call this a gap

    def test_a_commit_that_never_reached_main_is_listed(self):
        wt = self.worktree('feat')
        self.commit(wt, 'jamais\n')
        r = self.check(wt)
        self.assertEqual(r.returncode, 1)
        self.assertIn('jamais entrées dans main : 1', r.stdout)
        self.assertIn('jamais', r.stdout.split('a.md :')[1])

    def test_an_uncommitted_or_untracked_file_blocks(self):
        wt = self.worktree('feat')
        (wt / 'brouillon.md').write_text('pas commité\n')
        r = self.check(wt)
        self.assertEqual(r.returncode, 1)
        self.assertIn('changements non commités : 1', r.stdout)

    def test_a_branch_without_new_lines_can_be_archived(self):
        wt = self.worktree('feat')
        self.assertEqual(self.check(wt).returncode, 0)

    def test_a_folder_outside_git_has_nothing_to_check(self):
        plain = self.root / 'Studio'
        plain.mkdir()
        r = self.check(plain)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('pas un dépôt git', r.stdout)

    def test_two_worktrees_one_blocked_exits_one(self):
        ok, bad = self.worktree('ok'), self.worktree('bad')
        self.commit(bad, 'jamais\n')
        r = self.check(ok, bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn('== ok', r.stdout)
        self.assertIn('== bad', r.stdout)

    def test_no_main_branch_says_it_cannot_decide(self):
        run(self.repo, 'branch', '-m', 'main', 'trunk')
        wt = self.worktree('feat')
        r = self.check(wt)
        self.assertEqual(r.returncode, 2)
        self.assertIn('Vérification impossible', r.stdout)


if __name__ == '__main__':
    unittest.main()
