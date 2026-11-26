"""Before archiving a session: is anything in its worktree or branch missing from main?

Usage: archive_check.py <repo> <worktree> [<worktree> ...]     (exit 0 when every worktree can be archived)

Archiving removes the session's working folder, not its branch. For each worktree this checks, read only:
  1. uncommitted changes (modified or untracked files: they would be lost with the folder);
  2. every line the branch added (merge-base..tip): is there one commit of main that contains all of them, in the
     same files? Looking for the commit where the branch entered main, not comparing with main as it is now, because
     main may have reworked those lines since (a squash merge, or a merge followed by other work, both pass).
A branch whose lines never all reached main is listed with the lines missing: it was either dropped by a decision
traced somewhere (look for it), or it must not be archived. A folder that is not a git repository
has nothing to check here. Used by hooks/rangement.py (`confirmer`) just before a session is archived: a worktree that fails is kept.

Origin: first version by the product-kits foreman (2026-10-20); hardened here (no `main`, folder
outside git, very long branches).
"""
import subprocess
import sys

MAX_COMMITS = 500   # a branch that diverged from main by more commits than this is for a human to look at


class NotGit(Exception):
    pass


def git(cwd, *args, check=True):
    r = subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r.stdout


def main_ref(repo):
    for name in ('main', 'master'):
        if git(repo, 'rev-parse', '--verify', '--quiet', name, check=False).strip():
            return name
    head = git(repo, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD', check=False).strip()
    if head:
        return head
    raise NotGit('no main branch')


def check(repo, wt):
    name = wt.rstrip('/').rsplit('/', 1)[-1]
    if git(wt, 'rev-parse', '--is-inside-work-tree', check=False).strip() != 'true':
        print(f'== {name} : pas un dépôt git, rien à vérifier côté git')
        return True
    main = main_ref(repo)
    dirty = [l for l in git(wt, 'status', '--porcelain').splitlines() if l.strip()]
    tip = git(wt, 'rev-parse', 'HEAD').strip()
    branch = git(wt, 'rev-parse', '--abbrev-ref', 'HEAD').strip()
    base = git(repo, 'merge-base', main, tip).strip()
    added = {}
    for path in git(repo, 'diff', '--name-only', base, tip).splitlines():
        lines = [l[1:] for l in git(repo, 'diff', '-U0', base, tip, '--', path).splitlines()
                 if l.startswith('+') and not l.startswith('+++') and l[1:].strip()]
        if lines:
            added[path] = lines

    def missing_at(commit):
        out = []
        for path, lines in added.items():
            try:
                there = set(git(repo, 'show', f'{commit}:{path}').splitlines())
            except subprocess.CalledProcessError:
                there = set()
            out += [(path, l.strip()) for l in lines if l not in there]
        return out

    best, landed, too_many = None, None, False
    commits = git(repo, 'rev-list', '--reverse', f'{base}..{main}').splitlines() if added else []
    if len(commits) > MAX_COMMITS:
        commits, too_many = commits[-MAX_COMMITS:], True
    for commit in commits:
        m = missing_at(commit)
        if not m:
            landed = commit
            break
        if best is None or len(m) < len(best):
            best = m
    if added and landed is None and best is None:
        best = missing_at(main)   # main has no commit since the branch left it: nothing of the branch is there
    print(f'== {name} (branche {branch}, {tip[:7]}, main = {main})')
    print(f'   changements non commités : {len(dirty)}')
    for l in dirty[:5]:
        print(f'     {l.strip()[:110]}')
    if base == tip:
        print('   la branche est déjà dans l\'historique de main (aucun commit à elle seule)')
    elif not added:
        print('   la branche n\'apporte aucune ligne')
    elif landed:
        print(f'   toute la branche est entrée dans main en {git(repo, "log", "-1", "--format=%h %s", landed).strip()}')
    else:
        print(f'   lignes de la branche jamais entrées dans main : {len(best or [])}'
              + (f' (seuls les {MAX_COMMITS} derniers commits de main ont été regardés)' if too_many else ''))
        for path, text in (best or [])[:8]:
            print(f'     {path} : {text[:110]}')
    return not dirty and (not added or landed is not None)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip().split('\n')[2])
    repo, worktrees = sys.argv[1], sys.argv[2:]
    try:
        results = [check(repo, wt) for wt in worktrees]
    except (NotGit, subprocess.CalledProcessError) as e:
        print(f'Vérification impossible : {e}. Ne pas archiver sans regarder à la main.')
        sys.exit(2)
    sys.exit(0 if all(results) else 1)
