"""Tests of the « Conflits » tab of a project view in Mon Studio: python3 -m unittest discover -s tests

Read-only and without LLM: the open cases of the Studio's register (projet/conflits.md), with their old and new value,
source and date, and whether the client already heard of it; no answer button; one button that opens the session
« <Projet> · Conflits Studio » (found by its title, the most recent; a title that starts so counts), or, when there is
none, how to create it. The project view also shows one line with that session when cases are open. Synthetic data."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
spec = importlib.util.spec_from_file_location('projets_conflits', SCRIPTS / 'projets.py')
projets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projets)
spec = importlib.util.spec_from_file_location('conflits_codes', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)

REGISTRE = """# Registre des conflits

Dernier passage : 10/11/2026

### C1 · Jour du comité de pilotage
- **Détecté le** : 10/11/2026
- **Ancienne valeur** : comité le premier mardi du mois (source : 2-cadrage/roadmap.md, 02/09/2026)
- **Nouvelle valeur** : comité le jeudi (source : sources/2026-10-20-mail.md, 20/10/2026)
- **Déjà communiqué au client** : oui
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : ouvert

### C2 · Plafond de remise
- **Détecté le** : 10/11/2026
- **Ancienne valeur** : remise à 10 % (source : projet/regles-metier.md, 15/09/2026)
- **Nouvelle valeur** : remise à 15 % (source : sources/2026-11-03-cr.md, 03/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : tranché le 10/11/2026 par Camille : remplacer

### C3 · Cas abîmé
- **Détecté le** : hier
"""


def meta(sid, cwd, titre, activite, archivee=False):
    return {'id': sid, 'cwd': cwd, 'titre': titre, 'activite': activite, 'archivee': archivee}


class Lecture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = pathlib.Path(self.tmp.name) / 'Studio - Projet Alpha'
        (self.studio / 'projet').mkdir(parents=True)
        (self.studio / 'projet' / 'conflits.md').write_text(REGISTRE, encoding='utf-8')
        self.d = str(self.studio)

    def test_open_cases_only_and_unreadable_counted(self):
        c = projets.conflits_du_projet(self.d, [])
        self.assertEqual([x['id'] for x in c['ouverts']], ['C1'])
        self.assertEqual(c['ouverts'][0]['nouvelle'], {'texte': 'comité le jeudi', 'source': 'sources › 2026 10 20 mail',
                                                       'date': '20/10/2026'})
        self.assertTrue(c['ouverts'][0]['communique'])
        self.assertEqual(c['illisibles'], 1)
        self.assertEqual(c['titre_session'], 'Projet Alpha · Conflits Studio')
        self.assertIsNone(c['session'])

    def test_no_register_no_case(self):
        (self.studio / 'projet' / 'conflits.md').unlink()
        c = projets.conflits_du_projet(self.d, [])
        self.assertEqual((c['ouverts'], c['illisibles'], c['lu']), ([], 0, True))

    def test_the_session_is_found_by_its_title_most_recent_first(self):
        metas = [meta('local_a', self.d, 'Projet Alpha · Conflits Studio', 10),
                 meta('local_b', self.d, 'Projet Alpha · Conflits Studio (rattrapage)', 20),
                 meta('local_c', self.d, 'Projet Alpha · Compte rendu', 30),
                 meta('local_d', '/ailleurs/Beta', 'Beta · Conflits Studio', 40)]
        self.assertEqual(projets.conflits_du_projet(self.d, metas)['session']['sessionId'], 'local_b')

    def test_studio_folder_first(self):
        metas = [meta('local_a', '/ailleurs', 'Projet Alpha · Conflits Studio', 50),
                 meta('local_b', self.d, 'projet alpha · conflits studio', 5)]
        self.assertEqual(projets.session_conflits(self.d, metas)['sessionId'], 'local_b')
        self.assertFalse(projets.est_session_conflits('Projet Alpha · Compte rendu des conflits', self.d))
        self.assertFalse(projets.est_session_conflits('Conflits Studio', self.d))

    def test_refused_read_falls_back_on_the_snapshot(self):
        with unittest.mock.patch.object(projets, 'lire_texte', side_effect=PermissionError()):
            c = projets.conflits_du_projet(self.d, [], instantane={self.d: {'conflits': REGISTRE}})
            self.assertEqual([x['id'] for x in c['ouverts']], ['C1'])
            c = projets.conflits_du_projet(self.d, [], instantane={})
            self.assertFalse(c['lu'])

    def test_no_code_in_the_tab_values(self):
        (self.studio / 'projet' / 'regles-metier.md').write_text('# Règles\n\n### PRJ-2 : Remise relevée\n', encoding='utf-8')
        texte = REGISTRE.replace('comité le jeudi (source', 'comité le jeudi, voir PRJ-2 et PRJ-99 (source')
        (self.studio / 'projet' / 'conflits.md').write_text(texte, encoding='utf-8')
        c = projets.conflits_du_projet(self.d, [])
        self.assertIn('voir Remise relevée', c['ouverts'][0]['nouvelle']['texte'])
        montre = [x['sujet'] + ' ' + x['ancienne']['texte'] + ' ' + x['ancienne']['source'] + ' ' + x['nouvelle']['texte']
                  + ' ' + x['nouvelle']['source'] for x in c['ouverts']]      # what the tab shows; `id` is never shown
        self.assertEqual(conflits.registre.codes_pour_le_pm(' '.join(montre)), [])

    def test_an_unreadable_register_costs_only_the_tab(self):
        vrai = projets.lire_texte

        def lire(chemin):
            if str(chemin).endswith('conflits.md'):
                raise PermissionError()
            return vrai(chemin)
        with unittest.mock.patch.object(projets, 'lire_texte', side_effect=lire):
            s = projets.lire_sources(self.d, 0)
        self.assertFalse(s['refus'])
        self.assertIsNone(s['conflits'])

    def test_a_studio_never_takes_the_session_of_a_longer_name(self):
        metas = [meta('local_x', '/ailleurs/Studio - Client Alpha', 'Client Alpha · Conflits Studio', 50)]
        studio_court = pathlib.Path(self.tmp.name) / 'Studio - Alpha'
        self.assertIsNone(projets.session_conflits(str(studio_court), metas))
        self.assertFalse(projets.est_session_conflits('Alpha · Conflits Studio', self.d))     # « Projet Alpha »
        self.assertTrue(projets.est_session_conflits('Projet Alpha · Conflits Studio (rattrapage)', self.d))

    def test_the_calculation_keeps_the_register_in_the_snapshot(self):
        s = projets.lire_sources(self.d, 0)
        self.assertEqual(s['conflits'], REGISTRE)

    def test_the_copy_next_to_projets_is_used_in_mon_studio(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ('projets.py', 'parc.py', 'matin.py'):
                shutil.copy(SCRIPTS / f, d)
            shutil.copy(ROOT / 'skills' / 'conflits' / 'scripts' / 'registre.py', pathlib.Path(d) / 'registre_conflits.py')
            sp = importlib.util.spec_from_file_location('projets_copie', pathlib.Path(d) / 'projets.py')
            copie = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(copie)
            self.assertEqual(len(copie.conflits_du_projet(self.d, [])['ouverts']), 1)

    def test_install_copies_the_reader(self):
        sp = importlib.util.spec_from_file_location('install_conflits', SCRIPTS / 'install.py')
        install = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(install)
        self.assertTrue(install.REGISTRE_SOURCE.is_file())
        self.assertEqual(install.REGISTRE_COPY.name, 'registre_conflits.py')


@unittest.skipUnless(shutil.which('node'), 'node absent : la page épinglée n\'est pas essayée')
class Page(unittest.TestCase):
    A = '/studios/Projet Alpha'

    def run_page(self, conflits_vue, cliquer=()):
        vue = {'dossier': self.A, 'nom': 'Projet Alpha', 'genere': 0, 'questions': [], 'anciennes': [], 'sujets': [],
               'tiers': [], 'journal': [], 'conflits': conflits_vue}
        payload = {'lignes': [], 'projets': [{'studio': 'Projet Alpha', 'dossier': self.A, 'nom': 'Projet Alpha'}],
                   'projet': vue, 'cliquer': [['data-projet', self.A]] + list(cliquer)}
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def vue(self, session=True):
        with tempfile.TemporaryDirectory() as d:
            s = pathlib.Path(d) / 'Projet Alpha'
            (s / 'projet').mkdir(parents=True)
            (s / 'projet' / 'conflits.md').write_text(REGISTRE, encoding='utf-8')
            metas = [meta('local_' + '1' * 36, str(s), 'Projet Alpha · Conflits Studio', 1)] if session else []
            return projets.conflits_du_projet(str(s), metas)

    def test_the_tab_shows_open_cases_read_only(self):
        out = self.run_page(self.vue(), [['data-vue-conflits', 'conflits']])
        html = out['projetConflits']
        self.assertTrue(out['projetPrincipalHidden'])
        self.assertIn('<strong>Jour du comité de pilotage</strong>', html)
        self.assertNotIn('C1', html)
        # Settled: not among the open cases, but in the journal below them (PM, Q12, 2026-11-15).
        ouverts, _, journal = html.partition('<h3>Tranché</h3>')
        self.assertNotIn('Plafond de remise', ouverts)
        self.assertIn('Plafond de remise', journal)
        self.assertIn('comité le premier mardi du mois</strong> (2 cadrage › roadmap, 02/09/2026)', html)
        self.assertIn('comité le jeudi</strong> (sources › 2026 10 20 mail, 20/10/2026)', html)
        self.assertIn('Déjà communiqué au client : <strong>oui</strong>', html)
        self.assertIn('1 cas illisible', html)
        self.assertIn('data-sid="local_' + '1' * 36 + '"', html)
        self.assertIn('Ouvrir « Projet Alpha · Conflits Studio » ↗', html)
        for interdit in ('data-repondre', 'data-reveil', 'data-clore', 'data-decider', 'data-matin-fait'):
            self.assertNotIn(interdit, html)
        self.assertIn('pastille">1<', out['ongletConflits'])

    def test_no_code_in_the_tab(self):
        out = self.run_page(self.vue(), [['data-vue-conflits', 'conflits']])
        texte = re.sub(r'<[^>]+>', ' ', out['projetConflits'] + ' ' + out['projetLigneConflits'] + ' ' + out['ongletConflits'])
        texte = re.sub(r'local_\w+', '', texte)
        self.assertEqual(conflits.registre.codes_pour_le_pm(texte), [], texte)

    def test_the_project_tab_has_a_line_to_the_session_when_cases_are_open(self):
        out = self.run_page(self.vue())
        self.assertFalse(out['projetPrincipalHidden'])
        self.assertIn('1 conflit ouvert', out['projetLigneConflits'])
        self.assertIn('data-sid="local_' + '1' * 36 + '"', out['projetLigneConflits'])

    def test_without_session_the_button_says_how_to_create_it(self):
        out = self.run_page(self.vue(session=False), [['data-vue-conflits', 'conflits']])
        self.assertIn('Pas encore de session « Projet Alpha · Conflits Studio »', out['projetConflits'])
        self.assertIn('<code>/cockpit:conflits</code>', out['projetConflits'])
        self.assertNotIn('data-sid', out['projetConflits'])

    def test_nothing_open_no_line_and_a_quiet_tab(self):
        out = self.run_page({'ouverts': [], 'illisibles': 0, 'session': None, 'titre_session': 'Projet Alpha · Conflits Studio',
                             'commande': '/cockpit:conflits', 'lu': True}, [['data-vue-conflits', 'conflits']])
        self.assertEqual(out['projetLigneConflits'], '')
        self.assertIn('Aucun conflit ouvert', out['projetConflits'])
        self.assertNotIn('pastille', out['ongletConflits'])

    def test_a_connector_without_conflicts_breaks_nothing(self):
        out = self.run_page(None, [['data-vue-conflits', 'conflits']])
        self.assertIn('pas encore lu', out['projetConflits'])
        out = self.run_page(None)
        self.assertEqual(out['projetLigneConflits'], '')
        self.assertFalse(out['projetPrincipalHidden'])


if __name__ == '__main__':
    unittest.main()
