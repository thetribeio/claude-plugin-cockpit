"""« Pour info : ce qui est entré au Studio » (PM, Q34 of 2026-11-06): python3 -m unittest discover -s tests

Grouped by project, one short line per entry (its own short title, else its first twelve words), its origin (« Slack
#canal · Alex », « Mail · Robin », « Drive », « Fichier du Studio »), the detail on a click, one button: the task it
created (« Voir la tâche », the board's line highlighted), else its source link, else the Studio's file unfolded in the
page (« Lire », read-only tool `lire`: text only, capped, escaped, never raw HTML), else the Studio's session. « Fait »
hides it for good (`clore`), « Tout vu » the whole group. Studios, files and pages here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from test_cockpit_projets import Base, MONDAY, FRIDAY, THURSDAY, MAIL, local

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'

NOUVEAU = ("📬 Alpha · 2 nouveautés · 1 action pour toi\nÀ toi de jouer :\n"
           "- Répondre à Robin sur le devis ([source](https://mail.google.com/m1))\n"
           "Ce qui est entré :\n"
           "- Devis de Robin reçu : Mail de Robin (30/10) avec le devis signé ([source](https://mail.google.com/m1))\n"
           "- CR du COPIL rangé : #alpha-interne (Alex, Robin, 30/10) le compte rendu est au Studio ([source](3-dev/cr.md))\n"
           "- Slack #alpha-interne (Alex, 30/10 10:12) : la recette commence lundi, Sam prépare les jeux de données "
           "et Léo relit les cas de test avant vendredi\n")


class Titles(Base):
    def test_short_title_or_first_twelve_words(self):
        t = self.p.titre_et_detail
        self.assertEqual(t('Devis reçu', 'le détail'), ('Devis reçu', 'le détail'))
        titre, detail = t('Slack #alpha (Alex, 30/10 10:12)', 'la recette commence lundi, Sam prépare les jeux de données et Léo relit')
        self.assertEqual(titre, 'la recette commence lundi, Sam prépare les jeux de données et Léo …')
        self.assertTrue(detail.startswith('Slack #alpha'))
        long = ' '.join(f'mot{i}' for i in range(20))
        self.assertEqual(t(long, '')[0], ' '.join(f'mot{i}' for i in range(12)) + ' …')

    def test_origin(self):
        o = self.p.origine_entree
        self.assertEqual(o('https://acme.slack.com/archives/C1/p2', '#alpha-interne (Alex, 04/11 16:09) : x'), 'Slack #alpha-interne · Alex')
        self.assertEqual(o('3-dev/cr.md', 'Slack #alpha-interne (Alex, Robin, Charlie, 05/11) : x'), 'Slack #alpha-interne · Alex, Robin')
        self.assertEqual(o('https://mail.google.com/m1', 'Devis reçu : Mail de Robin (30/10) avec le devis'), 'Mail · Robin')
        self.assertEqual(o('https://docs.google.com/d/1', 'Maquette v2 : nouvelle version'), 'Drive')
        self.assertEqual(o('2-cadrage/notes.md', 'Notes rangées : le plan'), 'Fichier du Studio')
        self.assertEqual(o('', 'Rien ne dit d’où'), '')


class Entries(Base):
    def test_live_entries_carry_title_origin_and_the_task_they_created(self):
        self.runs(self.alpha, (FRIDAY, NOUVEAU))
        out = self.compute()
        m = self.p.matin_pour_la_page(MONDAY, self.metas, out)
        e = {x['titre']: x for x in m['entre_studio']}
        tache = next(l['cle'] for l in self.block(out)['lignes'] if l['type'] == 'a_toi')
        self.assertEqual(e['Devis de Robin reçu']['tache'], tache)
        self.assertEqual(e['Devis de Robin reçu']['origine'], 'Mail · Robin')
        self.assertEqual(e['CR du COPIL rangé']['tache'], None)
        self.assertEqual(e['CR du COPIL rangé']['lien'], '3-dev/cr.md')
        self.assertEqual(e['CR du COPIL rangé']['origine'], 'Slack #alpha-interne · Alex, Robin')
        vieux = next(x for x in m['entre_studio'] if x['detail'].startswith('Slack #alpha-interne (Alex, 30/10 10:12)'))
        self.assertTrue(vieux['titre'].startswith('la recette commence lundi'))

    def test_seen_entries_leave_and_are_not_counted_as_closed(self):
        self.runs(self.alpha, (FRIDAY, NOUVEAU))
        out = self.compute()
        cle = self.p.matin_pour_la_page(MONDAY, self.metas, out)['entre_studio'][0]['cle']
        self.p.fermer(cle, MONDAY + 60)
        out = self.compute(MONDAY + 120)
        m = self.p.matin_pour_la_page(MONDAY + 120, self.metas, out)
        self.assertNotIn(cle, [x['cle'] for x in m['entre_studio']])
        self.assertEqual(self.block(out)['fermees_depuis_hier'], 0)


def rapport(*puces):
    return "📬 Alpha · nouveautés\nÀ toi de jouer :\nCe qui est entré :\n" + '\n'.join(f'- {p}' for p in puces) + '\n'


class Fresh(Base):
    """« Pour info » shows only fresh news: the fact is of the working day before or today (A), and the run is later than
    the last visit of the page made before today (B)."""

    def titres(self, when=MONDAY, vu_avant=None):
        out = self.p.calculer(e={'tableau': [], 'lecture_app': {'etat': 'ok', 'raison': ''}}, maintenant=when,
                              metas=self.metas, ecrire=False, vu_avant=vu_avant)
        bloc = self.block(out)
        return sorted(l['titre'] for l in (bloc or {}).get('lignes', []) if l['type'] == 'entree')

    def test_date_du_fait(self):
        d = self.p.date_du_fait
        passage = local(2026, 11, 20, 10, 28)
        self.assertEqual(d('Slack #alpha (Alex, 30/10 10:12) : la recette', passage), local(2026, 10, 30, 0))
        self.assertEqual(d('Daily du 19/11', passage), local(2026, 11, 19, 0))
        self.assertEqual(d('Slack #alpha (Léo, Sam, 19/11 18:05) : fil du 18/11', passage), local(2026, 11, 19, 0))
        self.assertEqual(d('Un compte rendu sans date', passage), passage)
        self.assertEqual(d('Rendez-vous le 31/02', passage), passage)   # not a date
        self.assertEqual(d('Livraison prévue le 25/11, relevé du 19/11', passage), local(2026, 11, 19, 0))   # the future is not a fact
        self.assertEqual(d('Mail de Tom (30/12)', local(2027, 1, 2, 9)), local(2026, 12, 30, 0))   # year before

    def test_monday_a_thursday_fact_is_old_a_friday_fact_is_fresh(self):
        self.runs(self.alpha, (FRIDAY, rapport('Daily du jeudi : Slack #a (Alex, 29/10 18:05) : vieux', 'Daily du vendredi : Slack #a (Alex, 30/10 09:10) : frais')))
        self.assertEqual(self.titres(), ['Daily du vendredi'])

    def test_seen_on_a_previous_day_leaves(self):
        puce = 'Devis reçu : Mail de Robin (30/10) avec le devis'
        self.runs(self.alpha, (local(2026, 10, 30, 10), rapport(puce)))
        self.assertEqual(self.titres(vu_avant=local(2026, 10, 30, 18)), [])                 # seen Friday 18h, run at 10h
        self.runs(self.alpha, (local(2026, 10, 30, 19), rapport(puce)))
        self.assertEqual(self.titres(vu_avant=local(2026, 10, 30, 18)), ['Devis reçu'])     # run after the visit

    def test_a_visit_of_today_hides_nothing(self):
        puce = 'Devis reçu : Mail de Robin (02/11) avec le devis'
        self.runs(self.alpha, (local(2026, 11, 2, 7), rapport(puce)))
        self.p.noter_visite(local(2026, 11, 2, 8, 30))
        vu = self.p.derniere_visite_avant_aujourdhui(local(2026, 11, 2, 9))
        self.assertIsNone(vu)
        self.assertEqual(self.titres(vu_avant=vu), ['Devis reçu'])

    def test_visits_are_kept_14_days_and_read_before_today(self):
        for jour in (1, 2, 20):
            self.p.noter_visite(local(2026, 10, jour, 12))
        self.p.noter_visite(local(2026, 11, 2, 8))
        self.p.noter_visite(local(2026, 11, 2, 9))
        self.assertEqual(self.p.lire_visites(), [local(2026, 10, 20, 12), local(2026, 11, 2, 9)])
        self.assertEqual(self.p.derniere_visite_avant_aujourdhui(local(2026, 11, 2, 10)), local(2026, 10, 20, 12))

    def test_five_days_away_shows_only_the_working_day_before_and_today(self):
        wed = local(2026, 11, 11, 9)   # window from Tuesday 10/11
        self.runs(self.alpha, (local(2026, 11, 10, 17), rapport('Vieux : Slack #a (Alex, 05/11 10:00) : lundi dernier',
                                                                  'Veille : Slack #a (Alex, 10/11 16:00) : hier',
                                                                  'Ce matin : Slack #a (Alex, 11/11 08:00) : aujourd\'hui')))
        self.assertEqual(self.titres(when=wed, vu_avant=local(2026, 11, 5, 18)), ['Ce matin', 'Veille'])

    def test_the_files_read_follow_the_entries_shown(self):
        d = pathlib.Path(self.alpha) / '3-dev'
        d.mkdir()
        (d / 'vieux.md').write_text('vieux', encoding='utf-8')
        (d / 'frais.md').write_text('frais', encoding='utf-8')
        passages = [{'ts': FRIDAY, 'entres': ['Vieux : Slack #a (Alex, 29/10) : x ([source](3-dev/vieux.md))',
                                              'Frais : Slack #a (Alex, 30/10) : x ([source](3-dev/frais.md))'], 'actions': []}]
        self.assertEqual(list(self.p.textes_des_entrees(self.alpha, passages, MONDAY)), ['3-dev/frais.md'])


class ReadAFile(Base):
    def setUp(self):
        super().setUp()
        (pathlib.Path(self.alpha) / '3-dev').mkdir()
        (pathlib.Path(self.alpha) / '3-dev' / 'cr.md').write_text('# CR\n\n- point **un**\n<script>x</script>\n', encoding='utf-8')

    def read(self, fichier, dossier=None):
        return self.p.lire_fichier(dossier or self.alpha, fichier, self.metas)

    def test_a_text_file_of_the_studio(self):
        r = self.read('3-dev/cr.md')
        self.assertEqual((r['fichier'], r['tronque']), ('3-dev/cr.md', False))
        self.assertIn('<script>x</script>', r['texte'])   # raw text: the page escapes it

    def test_refused(self):
        (pathlib.Path(self.alpha) / 'a.pdf').write_bytes(b'%PDF')
        dehors = pathlib.Path(self.root) / 'secret.md'
        dehors.write_text('secret', encoding='utf-8')
        os.symlink(dehors, pathlib.Path(self.alpha) / 'lien.md')
        for fichier in ('a.pdf', '../secret.md', '/etc/hosts', 'lien.md', '3-dev', 'absent.md'):
            with self.assertRaises(ValueError, msg=fichier):
                self.read(fichier)
        with self.assertRaises(ValueError):
            self.read('3-dev/cr.md', dossier=str(self.root))   # not a known Studio

    def test_capped(self):
        (pathlib.Path(self.alpha) / 'long.txt').write_text('é' * (self.p.LIRE_MAX), encoding='utf-8')
        r = self.read('long.txt')
        self.assertTrue(r['tronque'])
        self.assertLessEqual(len(r['texte'].encode('utf-8')), self.p.LIRE_MAX + 3)

    def test_from_the_snapshot_when_the_drive_refuses(self):
        self.runs(self.alpha, (FRIDAY, NOUVEAU))
        self.compute()   # outside the connector: the snapshot keeps the text of the day's entry files
        lu = self.p.lire_instantane()
        self.assertIn('3-dev/cr.md', next(iter(lu.values()))['fichiers'])
        with mock.patch.object(self.p, 'lire_texte', side_effect=PermissionError('refusé')):
            r = self.p.lire_fichier(self.alpha, '3-dev/cr.md', self.metas)
        self.assertIn('point **un**', r['texte'])

    def test_the_connector_declares_lire_read_only(self):
        src = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'mcp_mon_studio.py').read_text(encoding='utf-8')
        self.assertIn("{'name': 'lire'", src)
        bloc = src[src.index("{'name': 'lire'"):src.index("{'name': 'clore'")]
        self.assertIn("'readOnlyHint': True", bloc)
        install = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'install.py').read_text(encoding='utf-8')
        self.assertIn("'clore', 'lire', 'gabarit']", install)


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    def run_page(self, **entree):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'p.json'
            data.write_text(json.dumps(entree, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def payload(self, **more):
        now = int(time.time() * 1000)
        liste = {'genere': now, 'page': None, 'studios': [], 'projets': [
            {'nom': 'Alpha', 'dossier': '/S/Alpha', 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': [
                {'cle': 'aaaaaaaaaaa1', 'type': 'a_toi', 'titre': 'Répondre à Robin', 'detail': '', 'depuis': now - 3600000,
                 'session': MAIL, 'repli': False, 'echeance': None, 'lien': 'https://mail.google.com/m1', 'dossier': '/S/Alpha'}]}]}
        entrees = [
            {'cle': 'eeeeeeeeeee1', 'projet': 'Alpha', 'titre': 'Devis de Robin reçu', 'detail': 'Mail de Robin avec le devis',
             'origine': 'Mail · Robin', 'lien': 'https://mail.google.com/m1', 'tache': 'aaaaaaaaaaa1', 'dossier': '/S/Alpha'},
            {'cle': 'eeeeeeeeeee2', 'projet': 'Alpha', 'titre': 'CR rangé', 'detail': 'le CR', 'origine': 'Fichier du Studio',
             'lien': '3-dev/cr.md', 'tache': None, 'dossier': '/S/Alpha'},
            {'cle': 'eeeeeeeeeee3', 'projet': 'Beta', 'titre': 'Maquette v2', 'detail': 'nouvelle version', 'origine': 'Drive',
             'lien': 'https://docs.google.com/d/1', 'tache': None, 'dossier': '/S/Beta'},
            {'cle': 'eeeeeeeeeee4', 'projet': 'Beta', 'titre': 'Sans source', 'detail': 'rien', 'origine': '',
             'lien': '', 'tache': None, 'dossier': '/S/Beta', 'session': MAIL}]
        return dict({'lignes': [], 'liste_projets': liste, 'outils': ['lignes', 'clore', 'lire'],
                     'matin': {'etat': 'pas_passe', 'entre_studio': entrees, 'demandes': []}}, **more)

    def test_one_button_per_entry(self):
        h = self.run_page(**self.payload())['matin']
        rows = {r.split('</span>')[0].split('>')[-1]: r for r in h.split('<li class="entree">')[1:]}
        self.assertIn('data-voir-tache="aaaaaaaaaaa1"', rows['Devis de Robin reçu'])
        self.assertNotIn('Gmail ↗', rows['Devis de Robin reçu'])
        self.assertIn('data-lire="eeeeeeeeeee2"', rows['CR rangé'])
        self.assertNotIn('data-fichier', rows['CR rangé'])
        self.assertIn('>Drive ↗</a>', rows['Maquette v2'])
        self.assertIn(f'data-sid="{MAIL}"', rows['Sans source'])
        for r in rows.values():
            self.assertEqual(r.count('data-clore='), 1)   # « Fait »
        self.assertIn('data-tout-vu="Alpha"', h)
        self.assertIn('<span class="source">· Mail · Robin</span>', h)

    def test_the_task_button_goes_to_the_board_line(self):
        out = self.run_page(**self.payload(cliquer=[['data-onglet', 'matin'], ['data-voir-tache', 'aaaaaaaaaaa1']]))
        self.assertEqual(out['ongletTableauSelected'], 'true')
        self.assertIn('class="nouveau-studio surligne" data-demande="aaaaaaaaaaa1"', out['tableau'])

    def test_a_task_closed_meanwhile_falls_back_to_the_source(self):
        p = self.payload()
        p['liste_projets']['projets'][0]['lignes'] = []
        h = self.run_page(**p)['matin']
        self.assertNotIn('data-voir-tache', h)
        self.assertIn('Gmail ↗', h)

    def test_read_unfolds_the_file_escaped(self):
        texte = "# CR du COPIL\n\n- point **un**\n- point deux\n\n<script>alert(1)</script> et `code`\n"
        out = self.run_page(**self.payload(cliquer=[['data-lire', 'eeeeeeeeeee2']], lire={'texte': texte, 'tronque': True}))
        self.assertIn(['lire', {'dossier': '/S/Alpha', 'fichier': '3-dev/cr.md'}], out['appels'])
        h = out['matin']
        self.assertIn('<div class="lu"><h4>CR du COPIL</h4><ul><li>point <strong>un</strong></li><li>point deux</li></ul>', h)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt; et <code>code</code>', h)
        self.assertNotIn('<script>', h)
        self.assertIn('seul le début est affiché', h)
        self.assertIn('>Replier</button>', h)

    def test_a_bullet_that_opens_in_bold_is_a_plain_line_not_a_grid(self):
        # PM, 2026-11-20: « - **09:41, Ana S.** : annonce son retour » rendered the bold part one character per line.
        # Cause: « #bloc-matin ul.liste li » (a two-column grid for the rows of the page) also matched the bullets of the
        # file read in the page, so the bold part and the text became two grid cells. The bullets must be plain items.
        texte = "## Échanges\n\n- **09:41, Ana S.** : annonce son retour sur le projet.\n- **11:57, Léo B.** : *[Usage]* demande une relecture.\n"
        out = self.run_page(**self.payload(cliquer=[['data-lire', 'eeeeeeeeeee2']], lire={'texte': texte}))
        self.assertIn('<li><strong>09:41, Ana S.</strong> : annonce son retour sur le projet.</li>', out['matin'])
        css = PAGE.read_text(encoding='utf-8')
        regle = [l for l in css.split('\n') if 'ul.liste .lu li' in l]
        self.assertTrue(regle, 'no rule makes the bullets of a read file plain items')
        self.assertIn('display:list-item', regle[0])
        self.assertIn('#bloc-matin ul.liste .lu li', regle[0])   # three classes and ids deep: it wins over « #bloc-matin ul.liste li »

    def test_read_error_says_so(self):
        out = self.run_page(**self.payload(cliquer=[['data-lire', 'eeeeeeeeeee2']], lireErreur='tool_error'))
        self.assertIn('Fichier illisible depuis la page', out['matin'])

    def test_without_the_tool_no_read_button(self):
        h = self.run_page(**self.payload(outils=['lignes', 'clore']))['matin']
        self.assertNotIn('data-lire', h)

    def test_seen_and_all_seen(self):
        out = self.run_page(**self.payload(cliquer=[['data-clore', 'eeeeeeeeeee3']]))
        self.assertIn(['clore', {'cle': 'eeeeeeeeeee3'}], out['appels'])
        self.assertNotIn('Maquette v2', out['matin'])
        out = self.run_page(**self.payload(cliquer=[['data-tout-vu', 'Alpha']]))
        self.assertEqual([a for a in out['appels'] if a[0] == 'clore'],
                         [['clore', {'cle': 'eeeeeeeeeee1'}], ['clore', {'cle': 'eeeeeeeeeee2'}]])
        self.assertNotIn('Devis de Robin reçu', out['matin'])
        self.assertIn('Maquette v2', out['matin'])

    def test_the_line_unfolds_its_detail(self):
        h = self.run_page(**self.payload(cliquer=[['data-entre', 'eeeeeeeeeee3']]))['matin']
        self.assertIn('<span class="plus">nouvelle version</span>', h)
        self.assertNotIn('<span class="plus">le CR</span>', h)


if __name__ == '__main__':
    unittest.main()
