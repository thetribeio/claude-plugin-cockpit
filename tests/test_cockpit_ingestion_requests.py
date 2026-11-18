"""Tests: the ingestion's « À toi de jouer » requests in the main table (PM, Q21 of 2026-11-06), the « Today » tab
(Q24) and the relay marker for the ingestion kit (Q22): python3 -m unittest discover -s tests

A request is noted while its run is less than 14 days old, then stays open until it is settled at its source
(`reglees`) or closed by hand. Its key compares the bullet without the kit's suffixes (` (échéance AAAA-MM-JJ)`,
` ([source](<lien>))`), the same on both sides: the run's bullet and `reglees[].texte`. The page shows each open request
as a row of its main table, with its project, age and due date, soonest due date first, then the oldest."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import time
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from test_cockpit_projets import Base, MAIL, MONDAY, FRIDAY, REPORT, local, utc

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
SKILL = ROOT / 'skills' / 'mon-studio' / 'SKILL.md'
INSTALL = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py'

DUE = 'Répondre au client sur le planning (échéance 2026-11-09) ([source](https://mail.google.com/mail/u/0/#inbox/abc))'


def report(*requests, entries=()):
    return ('📬 Alpha · nouveautés\nÀ toi de jouer :\n' + ''.join(f'- {r}\n' for r in requests)
            + ('Ce qui est entré :\n' + ''.join(f'- {e}\n' for e in entries) if entries else ''))


def state(mon_studio):
    return json.loads((mon_studio / '.parc' / 'projets-etat.json').read_text(encoding='utf-8'))['lignes']


class Suffixes(Base):
    def test_the_bullet_is_split_into_body_due_date_and_link(self):
        self.assertEqual(self.p.decouper_puce(DUE), ('Répondre au client sur le planning', '2026-11-09',
                                                     'https://mail.google.com/mail/u/0/#inbox/abc'))
        self.assertEqual(self.p.decouper_puce('Relire (v2) ([source](3-dev/reunions/a (copie).md))'),
                         ('Relire (v2)', None, '3-dev/reunions/a (copie).md'))
        self.assertEqual(self.p.decouper_puce('Voir ([la note](a.md)) puis répondre.'), ('Voir ([la note](a.md)) puis répondre.', None, ''))
        self.assertEqual(self.p.decouper_puce('Caler le point (échéance 2026-02-30)'), ('Caler le point', None, ''))
        self.assertEqual(self.p.decouper_puce('Sans suffixe.'), ('Sans suffixe.', None, ''))

    def test_the_key_ignores_the_suffixes(self):
        self.assertEqual(self.p.cle_a_toi(DUE), self.p.cle_a_toi('Répondre au client sur le planning.'))
        self.assertNotEqual(self.p.cle_a_toi(DUE), self.p.cle_a_toi('Répondre au client sur le budget'))


class Window(Base):
    def test_a_request_is_noted_within_14_days_and_not_after(self):
        self.runs(self.alpha, (local(2026, 10, 20), report('Envoyer le devis')),
                  (local(2026, 10, 18), report('Relancer le client')))
        out = self.compute()
        self.assertEqual([l['titre'] for l in self.block(out)['lignes']], ['Envoyer le devis'])

    def test_a_noted_request_stays_open_past_14_days(self):
        self.runs(self.alpha, (local(2026, 10, 20), report('Envoyer le devis')))
        self.compute()
        out = self.compute(local(2026, 11, 20))
        self.assertEqual(self.types(out), ['a_toi'])

    def test_a_closed_request_is_kept_while_its_run_is_read(self):
        # Purged after 8 days closed, it would be noted again, open, by its run still in the 14 days.
        self.runs(self.alpha, (MONDAY, report('Envoyer le devis')))
        cle = self.block(self.compute())['lignes'][0]['cle']
        self.p.fermer(cle, MONDAY + 60)
        self.assertIsNone(self.block(self.compute(local(2026, 11, 12))))
        self.assertIn(cle, state(self.mon_studio))
        self.compute(local(2026, 11, 20))
        self.assertNotIn(cle, state(self.mon_studio), 'purged once its run is no longer read')

    def test_an_alert_block_closes_the_requests(self):
        text = ('À toi de jouer :\n- Valider la maquette\nAlerte du kit :\n- Gmail à reconnecter\n'
                'Ce qui est entré :\n- CR du COPIL : rangé.\n')
        entries, actions = self.p.sections_nouvelle(text)
        self.assertEqual((entries, actions), (['CR du COPIL : rangé.'], ['Valider la maquette']))
        self.runs(self.alpha, (MONDAY, text))
        self.assertNotIn('Gmail', json.dumps(self.compute(), ensure_ascii=False))


class Key(Base):
    def test_settled_at_the_source_with_the_suffixes_word_for_word(self):
        self.runs(self.alpha, (FRIDAY, report(DUE)))
        self.compute()
        self.runs(self.alpha, (FRIDAY, report(DUE)), reglees=[{'ts': utc(MONDAY + 60), 'texte': DUE, 'preuve': 'mail parti'}])
        self.assertEqual(self.types(self.compute(MONDAY + 120)), [])
        self.assertEqual([l['par'] for l in state(self.mon_studio).values()], ['source'])

    def test_settled_without_the_suffixes_and_a_later_run_with_a_new_link(self):
        self.runs(self.alpha, (FRIDAY, report(DUE)), (MONDAY - 600, report('Répondre au client sur le planning ([source](https://x.slack.com/a))')))
        out = self.compute()
        self.assertEqual(len(self.block(out)['lignes']), 1, 'one request, whatever its suffixes')
        self.runs(self.alpha, (FRIDAY, report(DUE)), reglees=[{'ts': utc(MONDAY + 60), 'texte': 'Répondre au client sur le planning'}])
        self.assertEqual(self.types(self.compute(MONDAY + 120)), [])

    def test_reopened_by_the_kit_with_the_suffixes(self):
        self.runs(self.alpha, (FRIDAY, report(DUE)), reglees=[{'ts': utc(MONDAY - 60), 'texte': DUE}])
        self.assertEqual(self.types(self.compute()), [])
        self.runs(self.alpha, (FRIDAY, report(DUE)), reglees=[{'ts': utc(MONDAY - 60), 'texte': DUE},
                                                             {'ts': utc(MONDAY), 'texte': DUE, 'rouverte': True}])
        self.assertEqual(self.types(self.compute(MONDAY + 60)), ['a_toi'])

    def test_a_line_noted_under_the_old_key_keeps_its_age_and_closing(self):
        self.runs(self.alpha, (FRIDAY, report(DUE)))
        old = self.p.cle_de(self.alpha, 'a_toi', self.p.normaliser(DUE))
        (self.mon_studio / '.parc' / 'projets-etat.json').write_text(json.dumps({'version': 1, 'lignes': {old: {
            'studio': self.alpha, 'type': 'a_toi', 'titre': 'Répondre (source)', 'premiere': FRIDAY - 86400, 'vue': FRIDAY,
            'fermee': None, 'par': None}}}), encoding='utf-8')
        line = self.block(self.compute())['lignes'][0]
        self.assertEqual((line['titre'], line['depuis']), ('Répondre au client sur le planning', int(FRIDAY - 86400) * 1000))
        self.assertNotIn(old, state(self.mon_studio))


class DueDate(Base):
    def test_the_title_has_no_raw_suffix_and_the_due_date_is_apart(self):
        self.runs(self.alpha, (FRIDAY, report(DUE)))
        line = self.block(self.compute())['lignes'][0]
        self.assertEqual((line['titre'], line['echeance'], line['lien']),
                         ('Répondre au client sur le planning', '2026-11-09', 'https://mail.google.com/mail/u/0/#inbox/abc'))
        self.assertEqual(line['dossier'], self.alpha)
        md = (self.mon_studio / 'projets.md').read_text(encoding='utf-8')
        self.assertIn('- Répondre au client sur le planning (échéance 09/11) · à toi de jouer (ingestion)', md)
        self.assertNotIn('mail.google.com', md)

    def test_soonest_due_date_first_then_the_oldest(self):
        self.runs(self.alpha, (FRIDAY, report('Relire le planning', 'Valider la maquette (échéance 2026-11-10)')),
                  (FRIDAY + 60, report('Envoyer le devis (échéance 2026-11-03)', 'Caler le point')))
        titles = [l['titre'] for l in self.block(self.compute())['lignes']]
        self.assertEqual(titles, ['Envoyer le devis', 'Valider la maquette', 'Relire le planning', 'Caler le point'])

    def test_old_without_a_due_date_goes_to_anciennes_a_late_one_never(self):
        # A passed due date used to fold the request into « Anciennes »; it now keeps it in sight, « en retard »
        # (PM, 2026-11-17), until it is closed.
        self.runs(self.alpha, (local(2026, 10, 23), report('Relire le planning', 'Valider (échéance 2026-11-04)')))
        lines = {l['titre']: l['ancienne'] for l in self.block(self.compute())['lignes']}
        self.assertEqual(lines, {'Relire le planning': True, 'Valider': False})
        late = {l['titre']: (l['ancienne'], l['impact'], l['raison']) for l in self.block(self.compute(local(2026, 11, 5)))['lignes']}
        self.assertEqual(late, {'Relire le planning': (True, 'normal', ''), 'Valider': (False, 'fort', 'en retard')})


@unittest.skipUnless(shutil.which('node'), 'node absent : la page épinglée n\'est pas essayée')
class Page(unittest.TestCase):
    def line(self, cle, titre, depuis, echeance=None, ancienne=False, lien=''):
        return {'cle': cle, 'type': 'a_toi', 'titre': titre, 'detail': '', 'depuis': depuis, 'session': MAIL, 'repli': False,
                'echeance': echeance, 'lien': lien, 'dossier': '/S/Alpha', 'ancienne': ancienne}

    def liste(self, now):
        day = 86400000
        return {'genere': now, 'page': None, 'studios': [], 'projets': [
            {'nom': 'Alpha', 'dossier': '/S/Alpha', 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': [
                self.line('aaaaaaaaaaa1', 'Relire <le> planning', now - 2 * day),
                self.line('aaaaaaaaaaa2', 'Valider la maquette', now - day, '2099-01-10', lien='https://mail.google.com/x'),
                self.line('aaaaaaaaaaa4', 'Vieille demande', now - 9 * day, ancienne=True)]},
            {'nom': 'Beta', 'dossier': '/S/Beta', 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': [
                self.line('aaaaaaaaaaa3', 'Envoyer le devis', now - 3600000, '2099-01-05'),
                self.line('aaaaaaaaaaa5', 'Caler le point', now - 3 * day)]}]}

    def run_page(self, **entree):
        import time
        now = int(time.time() * 1000)
        entree.setdefault('lignes', [])
        entree.setdefault('liste_projets', self.liste(now))
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(entree, f)
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_each_request_is_a_main_table_row_sorted_close_due_date_then_newest(self):
        # PM, Q37 of 2026-11-06: a close deadline first, then the newest; a far deadline does not reorder.
        out = self.run_page(outils=['lignes', 'clore'])
        t = out['tableau']
        order = [t.index(x) for x in ('Envoyer le devis', 'Valider la maquette', 'Relire &lt;le&gt; planning', 'Caler le point')]
        self.assertEqual(order, sorted(order))
        import datetime as dt
        demain = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        import time
        now = int(time.time() * 1000)
        liste = self.liste(now)
        liste['projets'][0]['lignes'].append(self.line('aaaaaaaaaaa6', 'Payer la facture', now - 5 * 86400000, demain))
        out5 = self.run_page(outils=['lignes', 'clore'], liste_projets=liste)
        t5 = out5['tableau']
        self.assertLess(t5.index('Payer la facture'), t5.index('Envoyer le devis'))
        # Five fresh requests: the old one stays folded in « Anciennes ».
        self.assertNotIn('Vieille demande', t5)
        self.assertIn('Vieille demande', out5['anciennes'])
        # Four: it comes up under them, marked « ancienne » (PM, 2026-11-12).
        self.assertLess(t.index('Caler le point'), t.index('Vieille demande'))
        self.assertIn('<span class="marque-ancienne">ancienne</span><span class="titre">Vieille demande', t)
        self.assertIn('<td class="studio">Beta</td>', t)
        self.assertIn('avant le 05/01', t)
        self.assertIn('<span class="elapsed', t.split('Envoyer le devis', 1)[1].split('</tr>', 1)[0], 'its age too')
        self.assertIn(f'data-sid="{MAIL}"', t)
        self.assertIn('data-retirer="aaaaaaaaaaa3"', t)
        self.assertIn('Fait / Retirer du tableau', t)
        self.assertIn('href="https://mail.google.com/x"', t)
        self.assertIn('>Mail<', t, 'the session column names where the request came from')
        self.assertNotIn('À toi de jouer', t)

    def test_fait_closes_the_row_through_clore(self):
        out = self.run_page(outils=['lignes', 'clore'], cliquer=[['data-clore', 'aaaaaaaaaaa3']])
        self.assertIn(['clore', {'cle': 'aaaaaaaaaaa3'}], out['appels'])
        self.assertEqual([a for a in out['appels'] if a[0] == 'clore'], [['clore', {'cle': 'aaaaaaaaaaa3'}]], 'called once')
        self.assertIn('Envoyer le devis', out['tableauAvant'])
        self.assertNotIn('Envoyer le devis', out['tableau'])

    def test_a_request_appears_once_on_the_main_page(self):
        out = self.run_page(outils=['lignes', 'clore'])
        for title in ('Envoyer le devis', 'Caler le point', 'Relire &lt;le&gt; planning'):
            self.assertEqual(out['tableau'].count('<span class="titre">' + title), 1)
            self.assertNotIn(title, out['projets'])
        self.assertTrue(out['projetsHidden'], 'a project with requests only leaves the Projets block')

    def test_ouvrir_only_to_the_mail_session_of_its_studio(self):
        liste = self.liste(int(time.time() * 1000))
        liste['projets'][1]['lignes'][0].update(repli=True, session='local_00000000-0000-0000-0000-0000000000ff')
        out = self.run_page(outils=['lignes', 'clore'], liste_projets=liste)
        row = out['tableau'].split('Envoyer le devis', 1)[1].split('</tr>', 1)[0]
        self.assertNotIn('data-sid', row)
        self.assertNotIn('chip', row)
        self.assertIn('data-retirer="aaaaaaaaaaa3"', row)
        self.assertIn(f'data-sid="{MAIL}"', out['tableau'].split('Caler le point', 1)[1].split('</tr>', 1)[0])

    def test_the_project_view_and_the_project_page_show_their_requests(self):
        vue = {'nom': 'Beta', 'questions': [], 'sujets': [], 'anciennes': [], 'journal': [], 'tiers': []}
        out = self.run_page(outils=['lignes', 'projet'], projet=vue, cliquer=[['data-projet', '/S/Beta']])
        self.assertIn('Envoyer le devis', out['projetQuestions'])
        self.assertIn('Caler le point', out['projetQuestions'])
        self.assertNotIn('Valider la maquette', out['projetQuestions'], 'another project')
        out = self.run_page(outils=['lignes', 'projet'], projet=vue, projetFixe='/S/Beta')
        self.assertIn('Envoyer le devis', out['projetQuestions'])
        self.assertTrue(out['boiteCachee'])

    def test_no_clore_tool_no_button(self):
        self.assertNotIn('data-clore', self.run_page(outils=['lignes'])['tableau'])

    def test_today_tab_is_discreet_and_lists_new_requests_live(self):
        html = PAGE.read_text(encoding='utf-8')
        self.assertIn('class="discret">Today</button>', html)
        self.assertNotIn('Ce matin', html)
        matin = {'etat': 'pas_passe', 'entre_studio': [{'cle': 'e1', 'projet': 'Alpha', 'phrase': 'CR rangé.', 'lien': 'a.md', 'dossier': '/S/Alpha'}],
                 'demandes': [{'cle': 'aaaaaaaaaaa3', 'titre': 'Envoyer le devis', 'projet': 'Beta', 'echeance': '2099-01-05',
                               'lien': '', 'dossier': '/S/Beta', 'depuis': 0}]}
        out = self.run_page(matin=matin, outils=['lignes', 'clore'], cliquer=[['data-onglet', 'matin']])
        # 0.2.17: the new requests are rows of the board; Today says how many, outside its count.
        self.assertEqual((out['ongletTableauSelected'], out['ongletMatinLabel']), ('false', 'Today'))
        h = out['matin']
        self.assertIn('Point du matin pas encore passé.', h)
        self.assertNotIn("nouvelle demande", h)   # the board carries them, Today does not repeat them (PM, 2026-11-17)
        self.assertNotIn('data-clore="aaaaaaaaaaa3"', h)
        self.assertIn('Pour info : ce qui est entré au Studio', h)
        out = self.run_page(matin=matin, outils=['lignes', 'clore'], cliquer=[['data-onglet', 'matin'], ['data-clore', 'aaaaaaaaaaa3']])
        self.assertNotIn('nouvelle demande', out['matin'])

    def test_the_skill_names_the_tab_today(self):
        self.assertNotIn('Ce matin', SKILL.read_text(encoding='utf-8'))


class RelayMarker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = pathlib.Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {'MON_STUDIO': str(home / 'Mon Studio')})
        env.start()
        self.addCleanup(env.stop)
        with mock.patch.object(pathlib.Path, 'home', return_value=home):
            spec = importlib.util.spec_from_file_location('install_relais_essai', INSTALL)
            self.i = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.i)
        self.i.INTERNAL.mkdir(parents=True)

    def quiet(self, fn, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            r = fn(*args)
        return r, out.getvalue()

    def test_the_page_poses_it_and_disable_removes_it(self):
        self.i.STATE.write_text('{}', encoding='utf-8')
        self.assertFalse(self.i.status()['newsRelayed'])
        r, out = self.quiet(self.i.record_page, 'https://claude.ai/artifact/abc123')
        self.assertEqual(r, 0)
        marker = json.loads(self.i.RELAY_MARKER.read_text(encoding='utf-8'))
        self.assertEqual(marker['par'], 'cockpit')
        self.assertRegex(marker['depuis'], r'^\d{4}-\d{2}-\d{2}T')
        self.assertEqual(self.i.RELAY_MARKER, self.i.MON_STUDIO / '.parc' / 'nouvelles-relayees.json')
        self.assertTrue(self.i.status()['newsRelayed'])
        self.i.pose_relay_marker()
        self.assertEqual(json.loads(self.i.RELAY_MARKER.read_text(encoding='utf-8'))['depuis'], marker['depuis'], 'kept')
        with mock.patch.object(self.i, 'remove_server'), mock.patch.object(self.i, 'remove_connector', return_value=False):
            self.quiet(self.i.disable)
        self.assertFalse(self.i.RELAY_MARKER.exists())

    def test_apply_poses_it_only_with_a_published_page(self):
        status = {'todo': [], 'disabled': False, 'page': None}
        with mock.patch.object(self.i, 'status', return_value=status), mock.patch.object(self.i, 'remove_server'), \
                mock.patch.object(self.i, 'install_local_files'), mock.patch.object(self.i, 'install_copies', return_value=True):
            self.quiet(self.i.apply)
            self.assertFalse(self.i.RELAY_MARKER.exists())
            status['page'] = 'https://claude.ai/artifact/abc123'
            self.quiet(self.i.apply)
            self.assertTrue(self.i.RELAY_MARKER.exists())


if __name__ == '__main__':
    unittest.main()
