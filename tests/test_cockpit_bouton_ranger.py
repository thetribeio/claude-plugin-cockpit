"""Tests: « Ranger » on Mon Studio (PM, Q5, 2026-11-18): python3 -m unittest discover -s tests

The app refuses archive_session in auto mode when the order comes from a hook's text handed to an unrelated session.
So the sessions to put away (finished ones from hooks/rangement.py, and those the PM abandoned) are a line of the
board, whose « Ranger » button copies a request in the PM's words; he pastes it in a session of his. Nothing is
archived by the page, the connector or a hook. Sessions, Studios and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import pathlib
import shutil
import tempfile
import time
import unittest

from test_cockpit_board_lighter import SID, charger, ligne, run_page

parc = charger('parc_ranger', 'parc.py')

A = 'local_00000000-0000-0000-0000-0000000000a1'
B = 'local_00000000-0000-0000-0000-0000000000b2'
C = 'local_00000000-0000-0000-0000-0000000000c3'
JOUR = 86400


class Liste(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d)
        ancien = parc.INTERNE
        parc.INTERNE = self.d
        self.addCleanup(setattr, parc, 'INTERNE', ancien)
        self.t = time.time()
        self.ecrire('cockpit.json', {})
        self.ecrire('rangement.json', {'a_ranger': [{'id': A, 'titre': 'vieux titre', 'raison': 'r'},
                                                    {'id': B, 'titre': 'Beta', 'raison': 'r'}]})
        self.metas = [{'id': A, 'titre': 'Alpha · Vérifier un lien', 'archivee': False},
                      {'id': B, 'titre': 'Beta · Essai', 'archivee': False},
                      {'id': C, 'titre': 'Gamma · Arrêtée', 'archivee': False}]

    def ecrire(self, nom, objet):
        (self.d / nom).write_text(json.dumps(objet), encoding='utf-8')

    def test_finished_sessions_with_their_current_title(self):
        r = parc.a_ranger(self.metas, self.t)
        self.assertEqual([x['id'] for x in r], [A, B])
        self.assertEqual(r[0]['titre'], 'Alpha · Vérifier un lien')
        self.assertFalse(r[0]['abandon'])

    def test_archived_unknown_or_scheduled_sessions_leave_the_line(self):
        self.metas[0]['archivee'] = True
        self.metas[1]['tache'] = 'point-du-matin'
        self.assertEqual(parc.a_ranger(self.metas, self.t), [])
        self.assertEqual(parc.a_ranger([], self.t), [])   # a card not on this Mac: a doubt

    def test_abandoned_sessions_first_once_and_for_seven_days(self):
        self.ecrire('abandonnees.json', {C: {'titre': 'Gamma', 'quand': self.t - 60}, B: {'titre': 'Beta', 'quand': self.t - 60}})
        r = parc.a_ranger(self.metas, self.t)
        self.assertEqual([(x['id'], x['abandon']) for x in r], [(C, True), (B, True), (A, False)])
        self.assertEqual([x['id'] for x in parc.a_ranger(self.metas, self.t + 8 * JOUR)], [A, B])

    def test_switch_off_keeps_only_the_abandoned(self):
        self.ecrire('cockpit.json', {'rangement_auto': False})
        self.ecrire('abandonnees.json', {C: {'titre': 'Gamma', 'quand': self.t}})
        self.assertEqual([x['id'] for x in parc.a_ranger(self.metas, self.t)], [C])

    def test_at_most_twenty(self):
        ids = [f'local_00000000-0000-0000-0000-{i:012d}' for i in range(25)]
        self.ecrire('rangement.json', {'a_ranger': [{'id': i} for i in ids]})
        self.assertEqual(len(parc.a_ranger([{'id': i, 'titre': 'Essai'} for i in ids], self.t)), parc.RANGER_MAX)

    def test_the_request_is_the_pm_asking_for_these_sessions_only(self):
        texte = parc.texte_a_ranger(parc.a_ranger(self.metas, self.t))
        self.assertIn('mcp__ccd_session_mgmt__archive_session', texte)
        self.assertIn(f'- {A} (Alpha · Vérifier un lien)', texte)
        self.assertIn(f'- {B} (Beta · Essai)', texte)
        self.assertNotIn(C, texte)
        self.assertTrue(texte.startswith('Range ces sessions'))
        self.assertEqual(parc.texte_a_ranger([]), '')

    def test_the_page_payload(self):
        p = parc.a_ranger_pour_la_page(self.metas, self.t)
        self.assertEqual([x['id'] for x in p['a_ranger']], [A, B])
        self.assertIn(A, p['ranger_texte'])


class Connecteur(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.m = charger('mcp_ranger', 'mcp_mon_studio.py')
        self.m.charger_parc()
        p = self.m.parc
        for k in ('INTERNE', 'fiches', 'charger_cache'):
            self.addCleanup(setattr, p, k, getattr(p, k))
        p.INTERNE = pathlib.Path(tmp.name)
        self.metas = [{'id': A, 'titre': 'Alpha · Essai', 'archivee': False}]
        p.fiches = lambda cache: self.metas
        p.charger_cache = lambda: {'fiches': {}}
        (p.INTERNE / 'cockpit.json').write_text('{}', encoding='utf-8')
        (p.INTERNE / 'rangement.json').write_text(json.dumps({'a_ranger': [{'id': A}]}), encoding='utf-8')
        self.copies = []
        ancien_run = self.m.subprocess.run
        self.addCleanup(setattr, self.m.subprocess, 'run', ancien_run)

        def run(cmd, **kw):   # never the real clipboard nor `open`
            self.copies.append((cmd, kw.get('input')))
            return type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
        self.m.subprocess.run = run

    def test_ranger_copies_the_mac_s_request_and_notes_the_click(self):
        r = self.m.ouvrir({'ranger': True})
        self.assertEqual(r['sessions'], [A])
        self.assertIn(A, r['copie'])
        self.assertEqual(self.copies, [(['pbcopy'], r['copie'].encode())])
        clics = json.loads((self.m.parc.INTERNE / 'ranger.json').read_text(encoding='utf-8'))
        self.assertEqual(clics[A]['titre'], 'Alpha · Essai')

    def test_nothing_to_put_away_is_refused_and_nothing_copied(self):
        self.metas[0]['archivee'] = True
        with self.assertRaises(ValueError):
            self.m.ouvrir({'ranger': True})
        self.assertEqual(self.copies, [])

    def test_the_tool_declares_it_and_never_archives(self):
        outil = next(o for o in self.m.OUTILS if o['name'] == 'ouvrir')
        self.assertEqual(outil['inputSchema']['properties']['ranger'], {'type': 'boolean'})
        src = (pathlib.Path(self.m.__file__)).read_text(encoding='utf-8')
        self.assertNotIn("'archive_session'", src)

    def test_an_abandoned_session_joins_the_line(self):
        ligne_ = {'retrait': 'r0123456789ac', 'cle': B, 'affiche_suite': 'Session arrêtée', 'session': 'Beta · Essai'}
        self.m._retirables.update(t=time.time(), lignes={'r0123456789ac': self.m.a_prevenir(ligne_)})
        self.m.clore({'cle': 'r0123456789ac', 'abandon': True})
        self.metas.append({'id': B, 'titre': 'Beta · Essai', 'archivee': False})
        self.assertEqual([(x['id'], x['abandon']) for x in self.m.parc.a_ranger(self.metas, time.time())],
                         [(B, True), (A, False)])


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    LISTE = [{'id': A, 'titre': 'Alpha · Vérifier un lien', 'abandon': False},
             {'id': B, 'titre': 'Beta · Essai', 'abandon': True}]

    def test_the_line_its_titles_and_its_button(self):
        r = run_page(lignes=[ligne()], a_ranger=self.LISTE, ranger_texte='Range ces sessions…')
        self.assertFalse(r['aRangerHidden'])
        self.assertEqual(r['aRangerTitre'], '2 sessions finies à ranger')
        self.assertIn('Alpha · Vérifier un lien', r['aRanger'])
        self.assertIn('data-sid="' + B + '"', r['aRanger'])
        self.assertIn('abandonnée', r['aRanger'])
        self.assertIn('>Ranger</button>', r['aRanger'])
        self.assertNotIn('ouvrir', [a[0] for a in r['appels']])   # nothing before the click

    def test_the_click_asks_the_connector_to_copy_and_says_where_to_paste(self):
        r = run_page(lignes=[ligne()], a_ranger=self.LISTE[:1], ranger_texte='Range ces sessions…',
                     cliquer=[['data-ranger', '1']])
        self.assertIn(['ouvrir', {'ranger': True}], r['appels'])
        self.assertEqual(r['aRangerTitre'], '1 session finie à ranger')
        self.assertIn('Copié : colle-le dans une nouvelle session (Cmd+N)', r['aRanger'])

    def test_the_request_is_visible_and_selectable_even_without_a_working_clipboard(self):
        # PM, 2026-11-20: nothing to copy in sight. The text is in a read-only box under the list, whatever the clipboard does.
        r = run_page(lignes=[ligne()], a_ranger=self.LISTE[:1], ranger_texte='Range ces sessions <vite>…')
        self.assertIn('<textarea readonly class="demande-ranger"', r['aRanger'])
        self.assertIn('Range ces sessions &lt;vite&gt;…</textarea>', r['aRanger'])
        r = run_page(lignes=[ligne()], a_ranger=self.LISTE[:1], ranger_texte='Range ces sessions…', outils=['lignes'])
        self.assertIn('data-demande-archivage', r['aRanger'])   # even a page without the connector's tools

    def test_a_failed_copy_never_says_copied(self):
        r = run_page(lignes=[ligne()], a_ranger=self.LISTE[:1], ranger_texte='Range ces sessions…',
                     cliquer=[['data-ranger', '1']], ouvrirErreur='tool_error')
        self.assertNotIn('Copié', r['aRanger'])
        self.assertIn('Copie impossible', r['alerte'])

    def test_nothing_to_put_away_no_block(self):
        r = run_page(lignes=[ligne()])
        self.assertTrue(r['aRangerHidden'])
        self.assertEqual(r['aRanger'], '')

    def test_abandon_says_where_the_session_goes(self):
        arretee = ligne(arret='interrupted', depuis=int((time.time() - 3 * JOUR) * 1000), cle=SID)
        r = run_page(lignes=[arretee], cliquer=[['data-abandonner', 'r00000000000a']])
        self.assertIn('« À ranger »', r['tableau'])
        self.assertNotIn('sera archivée', r['tableau'])


if __name__ == '__main__':
    unittest.main()
