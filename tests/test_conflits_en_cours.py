"""The « Conflits » tab shows what a session is settling now (2026-11-19): python3 -m unittest discover -s tests

The tab read only the register (projet/conflits.md), but /backlog:nettoyer settles contradictions elsewhere: it writes
backlog/_contexte/contradictions.md, records each PM decision in decisions-pm.md and asks its questions one at a time
in its session, which the board already holds as a question line. The tab now lists those pending questions (with the
session to answer in), the settling sessions active within a day, the backlog's decisions in « Tranché », and a header
built from the data that never speaks of the Monday re-read. Synthetic data, temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'

TRI = 'local_00000000-0000-0000-0000-00000000000a'
AUTRE = 'local_00000000-0000-0000-0000-00000000000b'
AILLEURS = 'local_00000000-0000-0000-0000-00000000000c'
CONFLITS = 'local_00000000-0000-0000-0000-00000000000d'

CONTRADICTIONS = """# Contradictions entre sources (relevé du 2026-11-10)

### 1. Plafond de remise
- Ana : 10 %
- Léo : 15 %

### 2. Jour du comité
Camille dit jeudi.

### 3. Export des commandes
Robin : tableur.
"""

DECISIONS = """# Décisions du PM

1. 2026-11-10 · Bloc « Derniers RDV » : côté mentor (contradiction 4) : **penchant de Sam, à confirmer**. Citation : « jeudi ».
   - 2026-11-10 · Décision 1, suite : à vérifier avec Alex.
2. 2026-11-12 · Plafond de remise : **15 %**. Citation : « remise relevée ».
n'importe quoi
3. pas de date · Sujet : **gras**
"""


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        racine = pathlib.Path(self.tmp.name)
        self.mon_studio = racine / 'Mon Studio'
        (self.mon_studio / '.parc').mkdir(parents=True)
        self.studio = F.make(racine / 'Studio - Projet Alpha')
        self.autre_studio = F.make(racine / 'Studio - Projet Beta')
        env = mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-19', 'MON_STUDIO': str(self.mon_studio)})
        env.start()
        self.addCleanup(env.stop)
        self.p = charger('projets_en_cours', SCRIPTS / 'projets.py')
        self.p.parc.SORTIE, self.p.parc.INTERNE = self.mon_studio, self.mon_studio / '.parc'
        self.d = str(self.studio)
        self.maintenant = time.time()

    def metas(self):
        m = lambda i, titre, cwd, **k: dict({'id': i, 'titre': titre, 'cwd': cwd, 'archivee': False,
                                             'activite': self.maintenant - 600}, **k)
        return [m(TRI, 'Alpha · Nettoyage du contexte backlog (/backlog:nettoyer)', self.d),
                m(AUTRE, 'Alpha · Compte rendu du kick-off', self.d),
                m(AILLEURS, 'Beta · Nettoyage du contexte backlog', str(self.autre_studio))]

    def ligne(self, sid, texte='Compte archivé en lecture seule ?', options='Écran d’attente (recommandé) · Historique en lecture',
              projet=None):
        return {'type': 'question', 'cle': 'q-' + sid[-1], 'titre': texte, 'detail': options, 'session': sid,
                'session_titre': 'x', 'projet': projet or self.d, 'depuis': self.maintenant - 300}

    def ecrire(self, rel, texte):
        p = self.studio / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte, encoding='utf-8')

    def onglet(self, questions=(), **k):
        return self.p.conflits_du_projet(self.d, self.metas(), questions=list(questions), maintenant=self.maintenant, **k)


class EnCours(Base):
    def test_a_pending_question_of_a_backlog_cleaning_session_is_listed_with_its_session(self):
        c = self.onglet([self.ligne(TRI)])
        self.assertEqual(len(c['en_cours']), 1)
        x = c['en_cours'][0]
        self.assertEqual((x['question'], x['session']), ('Compte archivé en lecture seule ?', TRI))
        self.assertIn('Écran d’attente', x['options'])
        self.assertEqual(x['session_titre'], 'Alpha · Nettoyage du contexte backlog (/backlog:nettoyer)')
        self.assertEqual(x['depuis'], self.maintenant - 300)

    def test_a_line_of_the_parc_board_is_read_too(self):
        parc_ligne = {'cle': TRI, 'ouvrir': TRI, 'projet': self.d, 'type': 'decision', 'session': 'Nettoyage du contexte',
                      'complet': 'Q3 · Compte archivé', 'detail': 'Q3 · Que montrer au compte archivé en lecture seule ?',
                      'depuis': self.maintenant - 60}
        c = self.onglet([parc_ligne])
        self.assertEqual([x['session'] for x in c['en_cours']], [TRI])
        self.assertIn('Que montrer', c['en_cours'][0]['question'])

    def test_a_menu_statement_is_split_into_its_question_and_its_answers(self):
        parc_ligne = {'cle': TRI, 'ouvrir': TRI, 'projet': self.d, 'type': 'decision', 'session': 'Nettoyage du contexte',
                      'detail': "Compte archivé : que voit-il ? Écran d'attente (recommandé) : un message. Historique : "
                                'ses anciens RDV.', 'depuis': self.maintenant - 60}
        x = self.onglet([parc_ligne])['en_cours'][0]
        self.assertEqual(x['question'], 'Compte archivé : que voit-il ?')
        self.assertEqual(x['options'], "Écran d'attente (recommandé) : un message. Historique : ses anciens RDV.")

    def test_a_question_of_an_unrelated_session_of_the_same_studio_is_not(self):
        self.assertEqual(self.onglet([self.ligne(AUTRE)])['en_cours'], [])

    def test_a_session_of_another_studio_is_not(self):
        c = self.onglet([self.ligne(AILLEURS)])
        self.assertEqual(c['en_cours'], [])
        self.assertEqual([x['sessionId'] for x in c['sessions_actives']], [TRI])

    def test_the_register_s_session_counts_and_an_archived_one_does_not(self):
        metas = self.metas() + [{'id': CONFLITS, 'titre': 'Alpha · Conflits Studio', 'cwd': self.d, 'archivee': False,
                                 'activite': self.maintenant - 5}]
        c = self.p.conflits_du_projet(self.d, metas, questions=[self.ligne(CONFLITS)], maintenant=self.maintenant)
        self.assertEqual([x['session'] for x in c['en_cours']], [CONFLITS])
        self.assertEqual([x['sessionId'] for x in c['sessions_actives']], [CONFLITS, TRI])    # most recent first
        metas[-1]['archivee'] = True
        c = self.p.conflits_du_projet(self.d, metas, questions=[self.ligne(CONFLITS)], maintenant=self.maintenant)
        self.assertEqual(c['en_cours'], [])

    def test_a_settling_session_idle_for_more_than_a_day_is_not_active(self):
        metas = self.metas()
        metas[0]['activite'] = self.maintenant - 2 * 86400
        c = self.p.conflits_du_projet(self.d, metas, maintenant=self.maintenant)
        self.assertEqual(c['sessions_actives'], [])

    def test_without_questions_nothing_changes(self):
        c = self.onglet()
        self.assertEqual((c['en_cours'], c['backlog'], c['journal']), ([], None, []))

    def test_the_global_tab_lists_a_studio_with_only_a_question_open(self):
        studios = [{'nom': 'Projet Alpha', 'dossier': self.d, 'role': 'pm'}]
        sans = self.p.conflits_global(studios, self.metas(), {}, [])
        avec = self.p.conflits_global(studios, self.metas(), {}, [self.ligne(TRI)])
        self.assertEqual((sans, [(x['nom'], x['en_cours']) for x in avec]), ([], [('Projet Alpha', 1)]))


class UneTache(Base):
    def test_a_task_line_shows_its_subject_never_its_instruction(self):
        # PM, 2026-11-20: under « En cours » the title was « Nouvelle session sur le dossier Studio, coller le prompt
        # donné dans la session… », the instruction (`detail`) of a task line, not its subject.
        tache = {'type': 'task', 'titre': None, 'affiche_titre': '', 'affiche_suite': 'Q29 · Alpha · Conflits : Lancer la passe',
                 'complet': 'Q29 · Alpha · Conflits : Lancer la passe', 'detail': 'Nouvelle session sur le dossier Studio, coller le prompt.',
                 'session': 'x', 'source': TRI, 'projet': self.d, 'depuis': self.maintenant - 300}
        r = self.onglet(questions=[tache])['en_cours']
        self.assertEqual([x['question'] for x in r], ['Q29 · Alpha · Conflits : Lancer la passe'])
        self.assertNotIn('coller le prompt', str(r))


class Backlog(Base):
    def test_the_survey_and_the_decisions_are_counted_and_the_decisions_join_the_journal(self):
        self.ecrire('backlog/_contexte/contradictions.md', CONTRADICTIONS)
        self.ecrire('backlog/_contexte/decisions-pm.md', DECISIONS)
        c = self.onglet()
        self.assertEqual(c['backlog'], {'releve': '10/11/2026', 'contradictions': 3, 'decisions': 2})
        self.assertEqual(c['tranches'], 2)
        self.assertEqual(c['journal'][0], {'sujet': 'Plafond de remise', 'date': '12/11/2026', 'par': 'le PM', 'choix': '15 %',
                                           'reponse': '', 'reprise': False, 'origine': 'backlog'})
        self.assertEqual(c['journal'][1]['sujet'], 'Bloc « Derniers RDV » : côté mentor')
        self.assertEqual(c['journal'][1]['choix'], 'penchant de Sam, à confirmer')
        self.assertNotIn('contradiction', c['journal'][1]['sujet'])

    def test_a_decision_marked_not_settled_stays_open_and_is_not_in_the_journal(self):
        # PM, 2026-11-20: « Présentation en cinq cartes : **pas tranchée** » was listed under « Tranché ».
        self.ecrire('backlog/_contexte/decisions-pm.md', DECISIONS + "4. 2026-11-19 · Présentation en cinq cartes (contradiction 43) : **pas tranchée**. Suite : voir.\n")
        c = self.onglet()
        self.assertEqual(c['backlog']['decisions'], 2)
        self.assertEqual([x['sujet'] for x in c['en_attente']], ['Présentation en cinq cartes'])
        self.assertEqual(c['en_attente'][0]['date'], '19/11/2026')
        self.assertNotIn('Présentation en cinq cartes', [x['sujet'] for x in c['journal']])

    def test_a_garbage_decisions_file_never_raises(self):
        self.ecrire('backlog/_contexte/decisions-pm.md', '\x00\x01 ?! ** ** \n1. · · **\n\n9. 2026-13-99 · **\n' + 'é' * 10)
        (self.studio / 'backlog' / '_contexte' / 'contradictions.md').write_bytes(b'\xff\xfe### \n###  x\n')
        c = self.onglet()
        self.assertIsNotNone(c)
        self.assertEqual(c['tranches'], len(c['journal']))

    def test_unreadable_files_give_none_and_the_snapshot_fills_in(self):
        self.ecrire('backlog/_contexte/decisions-pm.md', DECISIONS)
        gardee = self.p.lire_backlog(self.d)
        with mock.patch.object(self.p, 'lire_texte', side_effect=PermissionError('Drive')):
            self.assertIsNone(self.onglet(instantane={})['backlog'])
            c = self.onglet(instantane={self.d: {'backlog': gardee}})
        self.assertEqual(c['backlog']['decisions'], 2)

    def test_the_snapshot_keeps_the_parsed_backlog(self):
        self.ecrire('backlog/_contexte/decisions-pm.md', DECISIONS)
        s = self.p.lire_sources(self.d, self.maintenant)
        self.assertEqual(len(s['backlog']['decisions']), 2)
        self.assertIsNone(self.p.lire_sources(str(self.autre_studio), self.maintenant)['backlog'])


class Entete(Base):
    def test_no_text_of_the_tab_speaks_of_monday(self):
        self.p.conflits_du_projet(self.d, self.metas(), maintenant=self.maintenant)
        for etat in ('ingestion', 'aucune'):
            r = self.p.relecture_du_studio(self.d, '10/11/2026', {}, self.maintenant)
            self.assertNotIn('lundi', r['texte'].lower())
        c = self.onglet([self.ligne(TRI)])
        self.assertNotIn('lundi', json.dumps(c, ensure_ascii=False).lower())


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    A = '/studios/Projet Alpha'

    def run_page(self, **k):
        c = {'ouverts': [], 'illisibles': 0, 'session': None, 'titre_session': 'Projet Alpha · Conflits Studio',
             'commande': '/cockpit:conflits', 'lu': True, 'nouveaux': 0, 'relance': False, 'raison': '',
             'a_traiter': {'evident': 0, 'arbitrage': 0}, 'jours': 0, 'dernier_passage': '09/11/2026', 'journal': [],
             'tranches': 0, 'verification': 'verifie', 'en_cours': [], 'sessions_actives': [], 'backlog': None}
        c.update(k)
        vue = {'dossier': self.A, 'nom': 'Projet Alpha', 'genere': 0, 'questions': [], 'anciennes': [], 'sujets': [],
               'tiers': [], 'journal': [], 'conflits': c}
        payload = {'lignes': [], 'projets': [{'studio': 'Projet Alpha', 'dossier': self.A, 'nom': 'Projet Alpha'}],
                   'projet': vue, 'cliquer': [['data-projet', self.A], ['data-vue-conflits', 'conflits']]}
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / 'payload.json'
            data.write_text(json.dumps(payload, ensure_ascii=False))
            r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), str(data)], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_the_header_is_built_from_the_data_and_never_says_monday(self):
        sortie = self.run_page(
            backlog={'releve': '10/11/2026', 'contradictions': 41, 'decisions': 3},
            sessions_actives=[{'sessionId': TRI, 'titre': 'Alpha · Nettoyage du contexte backlog', 'activite': 1}],
            en_cours=[{'question': 'Compte archivé ?', 'options': 'Écran d’attente · Historique', 'session': TRI,
                       'session_titre': 'Alpha · Nettoyage du contexte backlog', 'depuis': 1}])
        html = sortie['projetConflits']
        self.assertIn('<strong>Dernier passage complet le 09/11</strong> · Contradictions du backlog relevées le 10/11 (41), '
                      '3 tranchées · Tri en cours dans « Alpha · Nettoyage du contexte backlog » · 1 question de la session', html)
        self.assertNotIn('lundi', html.lower())
        self.assertNotIn('à jour', html)
        self.assertNotIn('Pas encore de session', html)

    def test_a_case_not_settled_is_listed_as_not_settled_not_under_tranche(self):
        html = self.run_page(en_attente=[{'sujet': 'Présentation en cinq cartes', 'date': '19/11/2026', 'note': 'pas tranchée'}],
                             journal=[], tranches=0)['projetConflits']
        self.assertIn('<h3>Pas encore tranché</h3>', html)
        self.assertIn('<strong>Présentation en cinq cartes</strong>', html)
        self.assertNotIn('<h3>Tranché</h3>', html)
        self.assertNotIn('Aucun conflit', html)

    def test_the_open_question_has_its_text_options_and_a_button_to_its_session(self):
        html = self.run_page(
            en_cours=[{'question': 'Compte archivé ?', 'options': 'Écran d’attente · Historique', 'session': TRI,
                       'session_titre': 'Alpha · Nettoyage', 'depuis': 1}],
            sessions_actives=[{'sessionId': TRI, 'titre': 'Alpha · Nettoyage', 'activite': 1}])['projetConflits']
        self.assertIn('<h3>Questions de la session</h3>', html)
        self.assertIn('<strong>Compte archivé ?</strong>', html)
        self.assertIn('<small>Écran d’attente · Historique</small>', html)
        self.assertIn('data-sid="' + TRI + '"', html)
        self.assertIn('Répondre dans « Alpha · Nettoyage » ↗', html)
        self.assertIn('Lecture seule : tu réponds dans la session indiquée, une décision à la fois.', html)
        self.assertNotIn('tu tranches dans la session des conflits', html)
        self.assertEqual(html.count('Tri en cours dans'), 1)     # the active session asks: no second line for it

    def test_an_active_session_without_a_question_gets_an_open_button_and_no_read_only_sentence(self):
        html = self.run_page(sessions_actives=[{'sessionId': TRI, 'titre': 'Alpha · Nettoyage', 'activite': 1}])['projetConflits']
        self.assertIn('Tri en cours dans « Alpha · Nettoyage » <button', html)
        self.assertIn('Ouvrir ↗', html)
        self.assertNotIn('Lecture seule', html)
        self.assertNotIn('Studio à jour', html)

    def test_the_tab_counts_the_questions_with_the_register_s_cases(self):
        sortie = self.run_page(en_cours=[{'question': 'Q ?', 'options': '', 'session': TRI, 'session_titre': 'S', 'depuis': 1}])
        self.assertIn('1 conflit ouvert', sortie['projetLigneConflits'] if 'projetLigneConflits' in sortie else sortie['projetConflits'])

    def test_the_backlog_decisions_are_marked_in_the_journal(self):
        html = self.run_page(tranches=1, journal=[{'sujet': 'Plafond de remise', 'date': '12/11/2026', 'par': 'le PM',
                                                   'choix': '15 %', 'reponse': '', 'reprise': False,
                                                   'origine': 'backlog'}])['projetConflits']
        self.assertIn('15 %, le 12/11 par le PM (backlog)', html)


if __name__ == '__main__':
    unittest.main()
