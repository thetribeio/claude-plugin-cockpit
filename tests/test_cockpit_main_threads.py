"""Tests of the « Fils rouges » line of Mon Studio: python3 -m unittest discover -s tests

In a Studio that has a foreman, every top-level session where the PM typed at least 3 messages is a main thread, without
anyone declaring it: its non-archived sessions, except a title that starts with « ᐅ », a session another session
launched (unless moved up to the top level), a scheduled task and a 📬 thread; the foreman always. The mirror's « piliers » and the local list stay on top of that. A Studio without a
foreman does not change. Mirrors and session cards here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

STUDIO, OTHER = '/studios/Studio-Essai', '/studios/Autre'
FOREMAN, OTHER_FOREMAN = 'local_foreman', 'local_other_foreman'


def card(sid, title, cwd=STUDIO, parent=None, archived=False, task=None, detached=False):
    return {'id': sid, 'titre': title, 'cwd': cwd, 'parent': parent, 'archivee': archived, 'tache': task,
            'detachee': detached}


class MainThreads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _studio = unittest.mock.patch.object(parc, 'est_un_studio', lambda d: True)   # synthetic folders: no manifest on disk
        _studio.start()
        self.addCleanup(_studio.stop)
        self.saved = parc.CHANTIERS, parc.FILS_ROUGES, parc.INTERNE
        parc.CHANTIERS = pathlib.Path(self.tmp.name)
        parc.INTERNE = pathlib.Path(self.tmp.name) / '.parc'   # never the real cockpit.json (tableau_publie)
        parc.FILS_ROUGES = pathlib.Path(self.tmp.name) / 'fils-rouges.json'

    def tearDown(self):
        parc.CHANTIERS, parc.FILS_ROUGES, parc.INTERNE = self.saved
        self.tmp.cleanup()

    def mirror(self, name, foreman, pillars=(), **more):
        (parc.CHANTIERS / f'{name}.json').write_text(json.dumps(dict(
            {'chantier': name, 'sessionId': foreman, 'piliers': [{'titre': t, 'sessionId': s} for s, t in pillars]}, **more)))

    def threads(self, cards, local=None, ecrits=None):
        if local is not None:
            parc.FILS_ROUGES.write_text(json.dumps([{'titre': t, 'sessionId': s} for s, t in local]))
        return {b['studio']: [f['titre'] for f in b['sessions']] for b in parc.fils_rouges([], cards, [], ecrits)}

    def test_every_session_of_the_studio_except_the_micro_sessions(self):
        self.mirror('essai', FOREMAN)
        found = self.threads([
            card(FOREMAN, 'Contremaître'),
            card('local_by_hand', 'Réflexion produit'),
            card('local_micro', 'ᐅ Kit A · réparer le calcul'),
            card('local_launched', 'Kit A · tâche', parent=FOREMAN),
            card('local_from_chip', 'Kit B', parent='local_by_hand'),
            card('local_moved_up', 'Kit D', parent='local_by_hand', detached=True),
            card('local_archived', 'Ancien sujet', archived=True),
            card('local_task', 'Kit-qg : satisfaction (hebdo)', task='kit-qg-satisfaction'),
            card('local_news', '📬 Kit-qg · nouvelles'),
            card('local_worktree', 'Skill C', cwd=STUDIO + '/.claude/worktrees/elated-mestorf-f04140'),
            card('local_subfolder', 'Atelier', cwd=STUDIO + '/projet'),
            card('local_neighbour', 'Voisin', cwd=STUDIO + '-bis'),
        ])
        # A session launched by another one is work, not a main thread, unless the PM moved it up (2026-11-17).
        self.assertEqual(found['Essai'], ['Contremaître', 'Kit D', 'Réflexion produit', 'Skill C'])
        self.assertEqual(found['projet'], ['Atelier'])  # under the Studio of its card, as its lines
        self.assertNotIn('Essai bis', found)

    def test_only_sessions_where_the_pm_typed_three_messages(self):
        self.mirror('essai', FOREMAN, pillars=[('local_pillar', 'Pilier déclaré')])
        cards = [card(FOREMAN, 'Contremaître'), card('local_talk', 'Discussion'), card('local_two', 'Deux mots'),
                 card('local_none', 'Jamais écrit'), card('local_pillar', 'Pilier déclaré')]
        found = self.threads(cards, ecrits={'local_talk': 3, 'local_two': 2})
        # the foreman and a declared pillar stay whatever the count
        self.assertEqual(found['Essai'], ['Contremaître', 'Discussion', 'Pilier déclaré'])

    def test_messages_of_the_pm_are_counted_once_then_on_what_was_added(self):
        def user(text, **more):
            return json.dumps(dict({'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': text}}, **more))
        tool = json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'x', 'content': 'ok'}]}})
        other = json.dumps({'type': 'user', 'origin': {'kind': 'peer'}, 'message': {'content': 'brief from a session'}})
        t = pathlib.Path(self.tmp.name) / 'session.jsonl'
        t.write_text('\n'.join([other, user('premier'), tool, user('[Request interrupted by user]'), user('deuxième')]) + '\n')
        cache = {}
        self.assertEqual(parc.messages_du_pm(str(t), cache), 2)
        with open(t, 'a') as f:
            f.write(user('troisième') + '\n' + user('à moitié écrit')[:20])   # the last line is still being written
        self.assertEqual(parc.messages_du_pm(str(t), cache), 3)
        with open(t, 'a') as f:
            f.write(user('à moitié écrit')[20:] + '\n')
        self.assertEqual(parc.messages_du_pm(str(t), cache), 4)
        t.write_text(user('repris') + '\n')   # a file that shrank is counted again
        self.assertEqual(parc.messages_du_pm(str(t), cache), 1)

    def test_launched_by_any_active_foreman_is_not_a_main_thread(self):
        self.mirror('essai', FOREMAN)
        self.mirror('autre', OTHER_FOREMAN)
        found = self.threads([card(FOREMAN, 'Contremaître'), card(OTHER_FOREMAN, 'Autre contremaître', cwd=OTHER),
                              card('local_crossed', 'Kit A', parent=OTHER_FOREMAN)])
        self.assertEqual(found['Essai'], ['Contremaître'])

    def test_the_foreman_is_always_a_main_thread(self):
        self.mirror('essai', FOREMAN)
        self.mirror('autre', OTHER_FOREMAN)
        found = self.threads([card(FOREMAN, 'ᐅ Contremaître', parent=OTHER_FOREMAN),
                              card(OTHER_FOREMAN, 'Autre contremaître', cwd=OTHER)])
        self.assertEqual(found['Essai'], ['ᐅ Contremaître'])
        self.assertEqual(found['Autre'], ['Autre contremaître'])

    def test_ordered_by_title_as_the_sidebar(self):
        self.mirror('essai', FOREMAN, pillars=[('local_z', 'Zeta')])
        found = self.threads([card(FOREMAN, 'Foreman PM'), card('local_z', 'zeta'), card('local_e', 'Étude'),
                              card('local_a', 'atelier'), card('local_p', 'plugin & skill')])
        self.assertEqual(found['Essai'], ['atelier', 'Étude', 'Foreman PM', 'plugin & skill', 'zeta'])

    def test_declared_threads_stay_on_top_of_the_rule(self):
        self.mirror('essai', FOREMAN, pillars=[('local_micro', 'ᐅ Kit A · fil rouge')])
        found = self.threads([card(FOREMAN, 'Contremaître'), card('local_micro', 'ᐅ Kit A · fil rouge'),
                              card('local_elsewhere', 'Ailleurs', cwd=OTHER)],
                             local=[('local_elsewhere', 'Ailleurs')])
        self.assertEqual(found['Essai'], ['Contremaître', 'ᐅ Kit A · fil rouge'])
        self.assertEqual(found['Autre'], ['Ailleurs'])

    def test_studio_without_foreman_is_unchanged(self):
        cards = [card('local_b', 'Beta', cwd=OTHER), card('local_a', 'Alpha', cwd=OTHER), card('local_c', 'Gamma', cwd=OTHER)]
        found = self.threads(cards, local=[('local_b', 'Beta'), ('local_a', 'Alpha')])
        self.assertEqual(found, {'Autre': ['Beta', 'Alpha']})  # declared ones only, in the order of the list
        self.assertEqual(self.threads(cards, local=[]), {})

    def test_an_archived_anchor_session_keeps_its_project_rule(self):
        # No foreman since 2026-11-03: the session that anchors a project may be archived, its folder still says which
        # sessions are the project's; the archived session itself is no main thread.
        self.mirror('essai', FOREMAN, registre=True)
        found = self.threads([card(FOREMAN, 'Contremaître', archived=True), card('local_by_hand', 'Réflexion produit')])
        self.assertEqual(found, {'Essai': ['Réflexion produit']})

    def test_a_mirror_from_before_with_an_archived_foreman_stays_hidden(self):
        # As main wrote it (no `registre`): the upgrade does not bring an ended chantier back.
        self.mirror('essai', FOREMAN, tableau='https://claude.ai/artifact/AbCdEf')
        self.assertEqual(parc.chantiers_actifs([card(FOREMAN, 'Contremaître', archived=True)]), [])
        self.assertEqual(parc.chantiers_actifs([]), [])   # its foreman's card is gone
        self.assertEqual([c['chantier'] for c in parc.chantiers_actifs([card(FOREMAN, 'Contremaître')])], ['essai'])

    def test_page_and_markdown_get_the_same_line(self):
        self.mirror('essai', FOREMAN)
        cards = [card(FOREMAN, 'Contremaître'), card('local_by_hand', 'Réflexion produit'), card('local_micro', 'ᐅ Kit A')]
        fils = parc.fils_rouges([], cards, [])
        e = {'genere': 1_760_400_000.0, 'pastilles_lues': True, 'tableau': [], 'fils_rouges': fils,
             'sans_action': [{'studio': 'Essai', 'titre': 'Contremaître', 'sessionId': FOREMAN, 'non_lue': False,
                              'derniere': 1_760_400_000.0, 'etat': ''}]}
        page = parc.pour_la_page(e)['fils_rouges']
        self.assertEqual([f['sessionId'] for f in page[0]['sessions']], [FOREMAN, 'local_by_hand'])
        self.assertEqual(set(page[0]['sessions'][0]), {'titre', 'sessionId', 'non_lue', 'derniere'})   # ms, for the page
        self.assertIn('| Fils rouges | [Contremaître](#local_foreman) · [Réflexion produit](#local_by_hand) |',
                      parc.rendre_md(e))


if __name__ == '__main__':
    unittest.main()
