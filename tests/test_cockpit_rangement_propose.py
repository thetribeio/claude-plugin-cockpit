"""Tests of the daily rangement proposal (hooks/rangement.py, 0.3.19, PM, Q7, 2026-11-25): python3 -m unittest discover -s tests

Once a day, in a top-level session of the desktop app, the hook asks the session to end its answer with one numbered
question whose text it gives; it never orders an archive. On the PM's yes, `confirmer` checks the list again and notes
it in ranger.json. Sessions, titles and folders are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hooks'))


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = charger('rangement_propose', ROOT / 'hooks' / 'rangement.py')
fq = charger('format_questions_propose', ROOT / 'hooks' / 'format_questions.py')
parc = charger('parc_propose', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')

NOW = 2_000_000_000.0
ICI = 'local_00000000-0000-0000-0000-0000000000e1'
A = 'local_00000000-0000-0000-0000-0000000000a1'
B = 'local_00000000-0000-0000-0000-0000000000b2'
MERE = 'local_00000000-0000-0000-0000-0000000000f0'


class Base(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d)
        parc_dir = self.d / 'parc'
        parc_dir.mkdir()
        self.cartes = self.d / 'app' / 'compte' / 'org'
        self.cartes.mkdir(parents=True)
        for nom, val in (('INTERNAL', parc_dir), ('STATE', parc_dir / 'cockpit.json'),
                         ('OUT', parc_dir / 'rangement.json'), ('PROPOSE', parc_dir / 'rangement-propose.json'),
                         ('RANGER_CLICS', parc_dir / 'ranger.json')):
            ancien = getattr(rg, nom)
            setattr(rg, nom, val)
            self.addCleanup(setattr, rg, nom, ancien)
        self.parc_dir = parc_dir
        env = {'MON_STUDIO_APP_SESSIONS': str(self.d / 'app'), 'CLAUDE_CODE_HOST_SESSION_ID': ICI}
        anciens = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.addCleanup(self.restaurer, anciens)
        self.ecrire('cockpit.json', {})
        self.ecrire('rangement.json', {'calcule': NOW - 600, 'a_ranger': [
            {'id': A, 'titre': 'Alpha · Vérifier un lien',
             'raison': 'lancée par « Alpha · Suivi », rapport rendu, rien à trancher, inactive depuis 30 h'},
            {'id': B, 'titre': 'Beta · Relire une note',
             'raison': 'marquée [jetable], rapport rendu, rien à trancher, inactive depuis 50 h'}]})
        self.carte(ICI, title='Alpha · Fil rouge', lastActivityAt=NOW * 1000)
        self.carte(A, title='Alpha · Vérifier un lien', lastActivityAt=(NOW - 30 * 3600) * 1000,
                   spawnedFrom={'sessionId': MERE})
        self.carte(B, title='Beta · Relire une note', lastActivityAt=(NOW - 50 * 3600) * 1000)

    @staticmethod
    def restaurer(anciens):
        for k, v in anciens.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def ecrire(self, nom, objet):
        (self.parc_dir / nom).write_text(json.dumps(objet), encoding='utf-8')

    def carte(self, sid, **kw):
        (self.cartes / f'{sid}.json').write_text(json.dumps(dict({'sessionId': sid}, **kw)), encoding='utf-8')

    def proposer(self, entree=None, maintenant=NOW):
        return rg.proposer(entree if entree is not None else {'prompt': 'Fais le point sur Alpha.'}, maintenant)


class Proposition(Base):
    def test_asks_a_question_never_orders_an_archive(self):
        t = self.proposer()
        self.assertIn('Qn · Ranger 2 sessions finies ? :', t)
        self.assertIn("N'archive rien de toi-même", t)
        self.assertIn(f'[Alpha · Vérifier un lien](#{A})', t)
        self.assertIn(f'[Beta · Relire une note](#{B})', t)
        self.assertIn('1) **Les ranger** (recommandé)', t)
        self.assertIn('2) **Les garder**', t)
        self.assertIn("Elles restent récupérables dans les archivées", t)
        self.assertIn('rangement.py" confirmer', t)

    def test_the_tone_the_pm_asked_for(self):
        t = self.proposer()
        for morceau in ("lancées par moi (ou par d'autres sessions)", "ne font plus rien depuis plus d'un jour",
                        "tout ce qu'elles ont produit est enregistré au Studio",
                        "aucune n'attend de réponse de ta part", 'On les archive pour alléger ta liste ?'):
            self.assertIn(morceau, t)

    def test_reasons_in_plain_words(self):
        t = self.proposer()
        self.assertIn('lancée par « Alpha · Suivi », a rendu son rapport, sans activité depuis plus d\'un jour', t)
        self.assertIn('lancée comme une tâche ponctuelle (« [jetable] »), a rendu son rapport, sans activité '
                      'depuis 2 jours', t)

    def test_one_session_in_the_singular(self):
        self.ecrire('rangement.json', {'calcule': NOW - 600, 'a_ranger': [{'id': A, 'titre': 'x', 'raison': 'r'}]})
        t = self.proposer()
        self.assertIn('Qn · Ranger 1 session finie ? :', t)
        self.assertIn('1) **La ranger** (recommandé)', t)
        self.assertIn('Elle reste récupérable', t)

    def test_the_question_passes_the_format_check(self):
        for ids in ([A], [A, B]):
            liste = [{'id': i, 'titre': 'Alpha · Une tâche assez longue pour voir', 'raison': 'r',
                      'inactif': 40 * 3600} for i in ids]
            msg = 'Fait.\n\nÀ trancher\n\n' + rg.question(liste).replace('Qn', 'Q7')
            items = [it for it in parc.a_trancher(msg)[0] if it.get('num')]
            self.assertEqual(len(items), 1)
            self.assertEqual(fq.ecarts(parc, items[0]), [])

    def test_once_a_day(self):
        self.assertTrue(self.proposer())
        self.assertEqual(self.proposer(maintenant=NOW + 60), '')
        etat = json.loads((self.parc_dir / 'rangement-propose.json').read_text())
        self.assertEqual(etat['ids'], [A, B])
        self.assertEqual(etat['session'], ICI)
        self.ecrire('rangement.json', dict(json.loads((self.parc_dir / 'rangement.json').read_text()),
                                           calcule=NOW + 86400 - 60))
        self.assertTrue(self.proposer(maintenant=NOW + 86400))

    def test_preview_notes_nothing(self):
        self.assertTrue(rg.proposer({}, NOW, apercu=True))
        self.assertFalse((self.parc_dir / 'rangement-propose.json').exists())

    def test_silent_outside_the_desktop_app(self):
        os.environ.pop('CLAUDE_CODE_HOST_SESSION_ID')
        self.assertEqual(self.proposer(), '')

    def test_silent_when_switched_off(self):
        for etat in ({'rangement_propose': False}, {'rangement_auto': False}, {'disabled': True}):
            self.ecrire('cockpit.json', etat)
            self.assertEqual(self.proposer(), '', etat)
        self.assertFalse((self.parc_dir / 'rangement-propose.json').exists())

    def test_silent_in_a_session_started_by_another(self):
        self.carte(ICI, title='x', lastActivityAt=NOW * 1000, spawnedFrom={'sessionId': MERE})
        self.assertEqual(self.proposer(), '')
        self.carte(ICI, title='x', lastActivityAt=NOW * 1000, spawnedFrom={'sessionId': MERE}, lineageDetached=True)
        self.assertTrue(self.proposer())

    def test_silent_on_a_message_from_another_session_or_the_app(self):
        for p in ('<cross-session-message from="x">fini</cross-session-message>', '<side-sessions-event>…',
                  '<task-notification>…'):
            self.assertEqual(self.proposer({'prompt': p}), '', p)

    def test_silent_in_a_scheduled_run_or_an_unknown_card(self):
        self.carte(ICI, title='x', scheduledTaskId='point-du-matin')
        self.assertEqual(self.proposer(), '')
        (self.cartes / f'{ICI}.json').unlink()
        self.assertEqual(self.proposer(), '')

    def test_drops_archived_active_or_own_session(self):
        self.carte(A, title='x', isArchived=True)
        self.carte(B, title='x', lastActivityAt=NOW * 1000)   # active since the list was computed
        self.assertEqual(self.proposer(), '')

    def test_this_session_is_never_proposed(self):
        self.ecrire('rangement.json', {'calcule': NOW - 600, 'a_ranger': [{'id': ICI, 'titre': 'x', 'raison': 'r'}]})
        self.assertEqual(self.proposer(), '')

    def test_old_list_is_not_proposed(self):
        self.ecrire('rangement.json', dict(json.loads((self.parc_dir / 'rangement.json').read_text()),
                                           calcule=NOW - 2 * 86400))
        self.assertEqual(self.proposer(), '')

    def test_without_asking_mode(self):
        self.ecrire('cockpit.json', {'rangement_sans_demander': True})
        t = self.proposer()
        self.assertIn('accord permanent', t)
        self.assertNotIn('Qn ·', t)
        self.assertIn('rangement.py" confirmer', t)
        self.assertIn('Rangé :', t)
        self.assertIn(f'confirmer --ids {A}', t)
        self.assertIn('#' + B, t)   # every checked session since Q4 (2026-11-25)
        etat = json.loads((self.parc_dir / 'rangement-propose.json').read_text())
        self.assertEqual(etat['mode'], 'sans_demander')

    def test_a_session_the_pm_kept_is_never_archived_without_asking(self):
        self.assertTrue(self.proposer())                      # question mode: A and B put to the PM, he keeps them
        self.ecrire('cockpit.json', {'rangement_sans_demander': True})
        self.ecrire('rangement.json', dict(json.loads((self.parc_dir / 'rangement.json').read_text()),
                                           calcule=NOW + 86400 - 60))
        self.assertEqual(self.proposer(maintenant=NOW + 86400), '')

    def test_question_mode_names_the_sessions_for_the_check(self):
        self.assertIn(f'confirmer --ids {A},{B}', self.proposer())

    def test_hook_entry_point_prints_the_proposal(self):
        self.ecrire('rangement.json', dict(json.loads((self.parc_dir / 'rangement.json').read_text()),
                                           calcule=NOW - 60))
        self.assertIn('Ranger 2 sessions finies', rg.hook({'prompt': 'Bonjour', 'cwd': str(pathlib.Path.home() / 'Mon Studio')}, NOW))


class Confirmer(Base):
    def test_notes_the_sessions_in_ranger_json_like_the_button(self):
        r = rg.confirmer(NOW)
        self.assertEqual([x['id'] for x in r['a_archiver']], [A, B])
        clics = json.loads((self.parc_dir / 'ranger.json').read_text())
        self.assertEqual(set(clics), {A, B})
        self.assertEqual(clics[A]['quand'], NOW)

    def test_a_session_active_again_leaves_the_list(self):
        self.carte(A, title='x', lastActivityAt=NOW * 1000)
        r = rg.confirmer(NOW)
        self.assertEqual([x['id'] for x in r['a_archiver']], [B])
        self.assertIn('redevenue active', r['gardees'][0]['raison'])

    def test_only_the_named_sessions(self):
        self.assertEqual([x['id'] for x in rg.confirmer(NOW, ids=[B])['a_archiver']], [B])

    def test_maximum_one_for_the_trial(self):
        self.assertEqual(len(rg.confirmer(NOW, maximum=1)['a_archiver']), 1)

    def test_a_worktree_with_unmerged_work_is_kept(self):
        repo = self.d / 'depot'
        repo.mkdir()

        def git(*a, cwd=repo):
            subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@t', *a],
                           check=True, capture_output=True)
        git('init', '-b', 'main')
        (repo / 'a.md').write_text('un\n')
        git('add', '.')
        git('commit', '-m', 'base')
        wt = self.d / 'wt'
        git('worktree', 'add', '-b', 'essai', str(wt))
        (wt / 'a.md').write_text('un\ndeux\n')
        git('commit', '-am', 'travail', cwd=wt)
        self.carte(A, title='x', lastActivityAt=(NOW - 30 * 3600) * 1000, worktreePath=str(wt))
        r = rg.confirmer(NOW)
        self.assertEqual([x['id'] for x in r['a_archiver']], [B])
        self.assertIn('main', r['gardees'][0]['raison'])
        git('merge', 'essai')
        self.assertEqual([x['id'] for x in rg.confirmer(NOW)['a_archiver']], [A, B])

    def test_unknown_card_is_kept(self):
        (self.cartes / f'{A}.json').unlink()
        r = rg.confirmer(NOW)
        self.assertEqual([x['id'] for x in r['a_archiver']], [B])
        self.assertIn('doute', r['gardees'][0]['raison'])


class Interrupteurs(unittest.TestCase):
    def test_install_switches(self):
        src = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py').read_text(encoding='utf-8')
        self.assertIn("'rangement-propose': 'rangement_propose'", src)
        self.assertIn("'rangement-sans-demander': 'rangement_sans_demander'", src)


if __name__ == '__main__':
    unittest.main()
