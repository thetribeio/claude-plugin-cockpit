"""Tests of the conflicts journal and the first check of a Studio (PM, Q12 to Q14, 2026-11-15):
python3 -m unittest discover -s tests

- the reprise of decisions settled by hand: checked against the register's format, written as settled, never twice,
  « Dernier passage » at the date of the hand catch-up, nothing written with --sortie;
- the register's journal (settled cases, the most recent first) and « Dernier passage » for Mon Studio;
- a preview prepared ahead, summarized next to the register, forgotten once written;
- Mon Studio: the tab's three states, and one line « Vérifier les conflits » for a never-checked Studio of the PM,
  kept until done or closed, with the text to paste when the conflicts session does not exist yet.
Synthetic data only."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
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
CONFLITS = ROOT / 'skills' / 'conflits' / 'scripts'
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


conflits = charger('conflits_reprise_t', CONFLITS / 'conflits.py')
registre = conflits.registre
projets = charger('projets_reprise_t', SCRIPTS / 'projets.py')

REPONSES = """# Décisions du PM après le rattrapage

## Réponses du PM
- 2026-11-10 · Comité de pilotage : **remplacer**, le jeudi.
- 2026-11-10 · Plafond de remise : **garder**.
"""


def decision(**k):
    d = {'titre': 'Jour du comité de pilotage',
         'ancienne': {'texte': 'comité le premier mardi du mois', 'source': '2-cadrage/roadmap.md', 'date': '02/09/2026'},
         'nouvelle': {'texte': 'comité le jeudi', 'source': '1-sources/2026-10-20-mail.md', 'date': '20/10/2026'},
         'communique': False, 'choix': 'remplacer', 'reponse': 'Le jeudi, à partir de décembre.',
         'tranche_le': '10/11/2026', 'par': 'Camille',
         'tranche_dans': 'projet/rattrapage-2026-11-09/decisions-pm.md', 'reste': ''}
    d.update(k)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = pathlib.Path(self.tmp.name) / 'Studio - Projet Alpha'
        (self.studio / '.claude').mkdir(parents=True)
        (self.studio / '.claude' / '.studio-manifest.json').write_text('{}', encoding='utf-8')
        r = self.studio / 'projet' / 'rattrapage-2026-11-09'
        r.mkdir(parents=True)
        (r / 'decisions-pm.md').write_text(REPONSES, encoding='utf-8')
        (r / 'part-a-releve.md').write_text('# Relevé\n', encoding='utf-8')
        self.d = str(self.studio)
        self.reprise = conflits.reprise_module()

    def extraction(self, items):
        f = pathlib.Path(self.tmp.name) / 'extraction.json'
        f.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
        return str(f)

    def registre_texte(self):
        p = self.studio / 'projet' / 'conflits.md'
        return p.read_text(encoding='utf-8') if p.exists() else ''


class Reprise(Base):
    def test_only_the_answer_files_are_read(self):
        fs = [rel for rel, _, _ in self.reprise.fichiers(self.d)]
        self.assertEqual(fs, ['projet/rattrapage-2026-11-09/decisions-pm.md'])
        self.assertIn('===== projet/rattrapage-2026-11-09/decisions-pm.md (rattrapage du 2026-11-09) =====',
                      self.reprise.texte_entree(self.d))

    def test_without_answers_the_preview_and_the_journal(self):
        r = self.studio / 'projet' / 'rattrapage-2026-11-10'
        r.mkdir()
        (r / 'apercu.md').write_text('# Aperçu\n', encoding='utf-8')
        (r / 'journal.md').write_text('# Journal\n', encoding='utf-8')
        fs = [rel for rel, _, _ in self.reprise.fichiers(self.d, 'rattrapage-2026-11-10')]
        self.assertEqual(sorted(fs), ['projet/rattrapage-2026-11-10/apercu.md', 'projet/rattrapage-2026-11-10/journal.md'])

    def test_checks_refuse_codes_unknown_choices_and_missing_files(self):
        decisions, refus = self.reprise.verifier(self.d, [
            decision(),
            decision(titre='Règle PRJ-12 changée'),
            decision(titre='Autre sujet', choix='abandonner'),
            decision(titre='Ailleurs', tranche_dans='../hors.md'),
            decision(titre='Futur', tranche_le='01/01/2099'),
        ], registre)
        self.assertEqual([d['titre'] for d in decisions], ['Jour du comité de pilotage'])
        raisons = dict(refus)
        self.assertIn('code', raisons['Règle PRJ-12 changée'])
        self.assertIn('choix inconnu', raisons['Autre sujet'])
        self.assertIn('introuvable', raisons['Ailleurs'])
        self.assertIn('futur', raisons['Futur'])

    def test_a_value_without_date_takes_the_catch_up_date_and_says_so(self):
        d = decision(ancienne={'texte': 'comité le mardi', 'source': '2-cadrage/roadmap.md', 'date': None})
        decisions, _ = self.reprise.verifier(self.d, [d], registre)
        self.assertEqual(decisions[0]['ancienne']['date'], '09/11/2026')
        self.assertTrue(decisions[0]['ancienne']['texte'].endswith(registre.SUFFIXE_FICHIER))
        self.assertEqual(decisions[0]['detecte'], '09/11/2026')

    def test_dry_run_writes_nothing_in_the_studio(self):
        sortie = pathlib.Path(self.tmp.name) / 'apercu.txt'
        code = conflits.main(['reprendre', self.d, '--extraction', self.extraction([decision()]), '--pm', 'Camille',
                              '--sortie', str(sortie)])
        self.assertEqual(code, 0)
        self.assertFalse((self.studio / 'projet' / 'conflits.md').exists())
        self.assertFalse((self.studio / 'projet' / '.conflits').exists())
        texte = sortie.read_text(encoding='utf-8')
        self.assertIn('Studio à jour depuis le 09/11/2026', texte)
        self.assertIn('Dernier passage : 09/11/2026', texte)
        self.assertIn('- **État** : tranché le 10/11/2026 par Camille : remplacer', texte)

    def test_written_as_settled_once_with_last_pass(self):
        x = self.extraction([decision(), decision(titre='Plafond de remise', choix='simple discussion', reponse='Garder.',
                             ancienne={'texte': 'remise 10 %', 'source': 'projet/regles.md', 'date': '15/09/2026'},
                             nouvelle={'texte': 'remise 15 %', 'source': '1-sources/cr.md', 'date': '03/11/2026'})])
        args = ['reprendre', self.d, '--extraction', x, '--pm', 'Camille', '--ecrire']
        self.assertEqual(conflits.main(args), 0)
        r = registre.lire(self.registre_texte())
        self.assertEqual(r['illisibles'], [])
        self.assertEqual(r['dernier_passage'], '09/11/2026')
        self.assertEqual([(c['id'], c['etat'], c['tranche']['choix']) for c in r['cas']],
                         [('C1', 'tranché', 'remplacer'), ('C2', 'tranché', 'simple discussion')])
        self.assertEqual(r['cas'][0]['file']['ajoute_par'], 'reprise')
        self.assertEqual(r['cas'][0]['file']['tranche_dans'], 'projet/rattrapage-2026-11-09/decisions-pm.md')
        avant = self.registre_texte()
        self.assertEqual(conflits.main(args), 0)                    # a second run writes nothing
        self.assertEqual(self.registre_texte(), avant)
        self.assertIn('décisions tranchées à la main reprises',
                      (self.studio / 'projet' / 'changelog.md').read_text(encoding='utf-8'))

    def test_no_last_pass_when_the_hand_catch_up_was_not_complete(self):
        conflits.main(['reprendre', self.d, '--extraction', self.extraction([decision()]), '--pm', 'Camille', '--ecrire',
                       '--dernier-passage', 'aucun'])
        r = registre.lire(self.registre_texte())
        self.assertIsNone(r['dernier_passage'])
        self.assertEqual(len(r['cas']), 1)

    def test_the_pm_corrects_a_choice_by_words_of_its_title(self):
        decisions, _ = self.reprise.verifier(self.d, [decision(), decision(titre='Plafond de remise')], registre)
        self.assertEqual(self.reprise.changer(decisions, [{'quoi': 'plafond', 'choix': 'simple discussion'}]), [])
        self.assertEqual(decisions[1]['choix'], 'simple discussion')
        erreurs = self.reprise.changer(decisions, [{'quoi': 'de', 'choix': 'remplacer'}])
        self.assertTrue(erreurs and '2 décisions' in erreurs[0])
        self.assertEqual(decisions[0]['choix'], 'remplacer')

    def test_preview_has_no_code(self):
        decisions, refus = self.reprise.verifier(self.d, [decision(reponse='Voir PRJ-12 : le jeudi.')], registre)
        texte, _ = self.reprise.apercu(self.d, decisions, refus, registre, '09/11/2026')
        self.assertNotIn('PRJ-12', texte)
        self.assertNotIn('C1', texte)

    def test_without_a_hand_catch_up_nothing_to_take_up(self):
        shutil.rmtree(self.studio / 'projet' / 'rattrapage-2026-11-09')
        self.assertEqual(self.reprise.fichiers(self.d), [])
        self.assertIsNone(self.reprise.dernier_passage_propose(self.d, registre))


class Relecture(Base):
    """The points of the independent review of 2026-11-15."""

    def test_never_a_survey_from_the_connector(self):
        with unittest.mock.patch.object(projets, '_charger_releve') as charger_:
            projets.conflits_du_projet(self.d, [], depuis_connecteur=True)
            charger_.assert_not_called()

    def test_a_failing_first_check_costs_only_its_words(self):
        with unittest.mock.patch.object(projets, 'premiere_verification', side_effect=RuntimeError('copie cassée')):
            c = projets.conflits_du_projet(self.d, [])
        self.assertIsNone(c['premiere'])
        self.assertEqual(c['verification'], 'jamais')

    def test_a_plan_outside_the_studio_leaves_nothing(self):
        plan = Pret.plan(self)
        self.assertIsNone(conflits.noter_pret(plan, pathlib.Path(self.tmp.name) / 'ailleurs.json'))
        self.assertFalse((self.studio / 'projet' / '.conflits' / 'pret.json').exists())

    def test_a_prepared_preview_older_than_the_last_pass_is_ignored(self):
        chemin = self.studio / 'projet' / '.conflits' / 'apercu-2026-11-14.json'
        chemin.parent.mkdir(parents=True)
        plan = Pret.plan(self)
        conflits.sauver_plan(chemin, plan)
        conflits.noter_pret(plan, chemin)
        registre.poser_dernier_passage(registre.chemin_du_studio(self.d), '14/11/2026')
        self.assertIsNone(conflits.lire_pret(self.d))

    def test_last_pass_never_goes_back(self):
        registre.poser_dernier_passage(registre.chemin_du_studio(self.d), '12/11/2026')
        conflits.main(['reprendre', self.d, '--extraction', self.extraction([decision()]), '--pm', 'Camille', '--ecrire'])
        self.assertEqual(registre.lire(self.registre_texte())['dernier_passage'], '12/11/2026')

    def test_an_older_folder_alone_does_not_say_the_studio_is_checked(self):
        r = self.studio / 'projet' / 'rattrapage-2026-11-12'
        r.mkdir()
        (r / 'decisions-pm.md').write_text(REPONSES, encoding='utf-8')
        self.assertIsNone(self.reprise.dernier_passage_propose(self.d, registre, 'rattrapage-2026-11-09'))
        self.assertEqual(self.reprise.dernier_passage_propose(self.d, registre, 'rattrapage-2026-11-12'), '12/11/2026')

    def test_a_write_error_leaves_no_last_pass(self):
        with unittest.mock.patch.object(registre, 'ajouter', side_effect=registre.Change('verrou')):
            code = conflits.main(['reprendre', self.d, '--extraction', self.extraction([decision()]), '--pm', 'Camille',
                                  '--ecrire'])
        self.assertEqual(code, 1)
        self.assertIsNone(registre.lire(self.registre_texte())['dernier_passage'])

    def test_a_second_extraction_worded_otherwise_adds_nothing(self):
        conflits.main(['reprendre', self.d, '--extraction', self.extraction([decision()]), '--pm', 'Camille', '--ecrire'])
        autre = decision(ancienne={'texte': 'comité chaque premier mardi', 'source': '2-cadrage/roadmap.md',
                                   'date': '02/09/2026'})
        conflits.main(['reprendre', self.d, '--extraction', self.extraction([autre, autre]), '--pm', 'Camille', '--ecrire'])
        self.assertEqual(len(registre.lire(self.registre_texte())['cas']), 1)

    def test_dry_run_guards(self):
        x = self.extraction([decision()])
        self.assertEqual(conflits.main(['reprendre', self.d, '--extraction', x, '--sortie', str(self.studio / 'a.txt')]), 2)
        self.assertEqual(conflits.main(['reprendre', self.d, '--extraction', x, '--sortie',
                                        str(pathlib.Path(self.tmp.name) / 'a.txt'), '--ecrire', '--pm', 'Camille']), 2)
        self.assertEqual(conflits.main(['reprendre', self.d, '--extraction', x, '--dernier-passage', '2026/11/03']), 2)
        self.assertFalse((self.studio / 'projet' / 'conflits.md').exists())

    def test_a_folder_that_is_not_a_date_is_skipped(self):
        (self.studio / 'projet' / 'rattrapage-2026-02-30').mkdir()
        self.assertEqual([d.name for d, _ in self.reprise.dossiers(self.d)], ['rattrapage-2026-11-09'])

    def test_a_value_without_date_takes_its_source_file_date(self):
        (self.studio / '2-cadrage').mkdir()
        (self.studio / '2-cadrage' / 'roadmap.md').write_text('x', encoding='utf-8')
        d = decision(ancienne={'texte': 'comité le mardi', 'source': '2-cadrage/roadmap.md', 'date': None})
        decisions, _ = self.reprise.verifier(self.d, [d], registre)
        self.assertEqual(decisions[0]['ancienne']['date'], dt.date.today().strftime('%d/%m/%Y'))


class Journal(Base):
    def test_settled_cases_most_recent_first(self):
        chemin = registre.chemin_du_studio(self.d)
        a = {'texte': 'a', 'source': 'x.md', 'date': '01/10/2026'}
        b = {'texte': 'b', 'source': 'y.md', 'date': '02/10/2026'}
        registre.ajouter(chemin, 'Premier', a, b, False, '01/11/2026',
                         etat=registre.texte_etat('remplacer', 'Camille', '03/11/2026'))
        registre.ajouter(chemin, 'Deuxième', dict(a, texte='c'), b, False, '01/11/2026')
        registre.ajouter(chemin, 'Troisième', dict(a, texte='d'), b, False, '01/11/2026',
                         etat=registre.texte_etat('simple discussion', 'Camille', '05/11/2026'),
                         file={'reponse': 'On garde.'})
        j = registre.tranches(self.registre_texte())
        self.assertEqual([x['sujet'] for x in j], ['Troisième', 'Premier'])
        self.assertEqual(j[0]['reponse'], 'On garde.')
        registre.poser_dernier_passage(chemin, '06/11/2026')
        e = registre.etat_du_registre(self.registre_texte())
        self.assertEqual((e['dernier_passage'], e['tranches'], e['ouverts']), ('06/11/2026', 2, 1))

    def test_an_unknown_state_is_refused(self):
        with self.assertRaises(ValueError):
            registre.texte_etat('abandonner', 'Camille')
        with self.assertRaises(ValueError):
            registre.texte_etat('remplacer', '')


class Pret(Base):
    def plan(self, **k):
        p = {'studio': self.d, 'date': '2026-11-14', 'mode': 'rattrapage', 'dossier': None, 'sujets': [{'id': 'S1'}],
             'jugements': {'S1': {}}, 'marquages': [{}, {}], 'absences': [], 'ecrit': False,
             'decisions': [{'niveau': 'evident', 'raisons': []}, {'niveau': 'arbitrage', 'raisons': ['argent ou contrat']}]}
        p.update(k)
        return p

    def test_prepared_preview_summarized_then_forgotten(self):
        chemin = self.studio / 'projet' / '.conflits' / 'apercu-2026-11-14.json'
        chemin.parent.mkdir(parents=True)
        plan = self.plan()
        conflits.sauver_plan(chemin, plan)
        x = conflits.noter_pret(plan, chemin)
        self.assertEqual((x['marquages'], x['evidents'], x['arbitrages']), (2, 1, 1))
        self.assertEqual(x['minutes'], conflits.minutes_pm(1, 1))
        self.assertEqual(conflits.lire_pret(self.d)['plan'], str(chemin))
        self.assertIn('1 vraie question', conflits.texte_pret(x))
        conflits.oublier_pret(self.d, chemin)
        self.assertIsNone(conflits.lire_pret(self.d))

    def test_not_for_the_weekly_pass_a_folder_or_an_unjudged_plan(self):
        chemin = pathlib.Path(self.tmp.name) / 'p.json'
        self.assertIsNone(conflits.noter_pret(self.plan(mode='passe'), chemin))
        self.assertIsNone(conflits.noter_pret(self.plan(dossier='2-cadrage'), chemin))
        self.assertIsNone(conflits.noter_pret(self.plan(jugements={}), chemin))

    def test_the_cost_of_preparing_is_said(self):
        c = {'sujets': 97, 'lots': 11, 'usd_sous_agents': 2.61, 'usd_session_releve': 3.47, 'usd_session_decisions': 1.12,
             'usd_session': 4.58, 'decisions_estimees': 20}
        t = conflits.texte_preparer(c)
        self.assertNotIn('tâche planifiée', t)   # a gesture from the board (PM, Q18)
        self.assertIn('20 décisions', t)


def meta(sid, cwd, titre, activite):
    return {'id': sid, 'cwd': cwd, 'titre': titre, 'activite': activite}


class MonStudio(Base):
    def setUp(self):
        super().setUp()
        self.etat = {}
        # No survey from the tests: the estimate is given.
        p = unittest.mock.patch.object(projets, 'estimation_premiere', return_value={
            't': 0, 'sujets': 97, 'decisions': 20, 'minutes': 22, 'pourcent': 0.33, 'pourcent_preparer': 0.25,
            'au_dessus': False})
        p.start()
        self.addCleanup(p.stop)

    def test_never_checked_one_line_with_its_cost(self):
        c = projets.conflits_du_projet(self.d, [])
        self.assertEqual(c['verification'], 'jamais')
        self.assertIn("l'onglet « Conflits » de la page du projet", c['texte_premiere'])
        self.assertIn('Environ 20 questions', c['texte_premiere'])
        self.assertIn('reprises', c['texte_premiere'])                    # a hand catch-up is there
        metas = [meta('local_' + 'a' * 36, self.d, 'Projet Alpha · Compte rendu', 5)]
        l = projets.ligne_verifier_conflits(self.d, projets.conflits_du_projet(self.d, metas), self.etat, 1000, metas)
        self.assertEqual(l['type'], 'verifier')
        self.assertEqual(l['session'], 'local_' + 'a' * 36)
        self.assertEqual(l['copier'], '/cockpit:conflits rattrapage')
        self.assertEqual(registre.codes_pour_le_pm(l['titre'] + ' ' + l['detail']), [])

    def test_the_conflicts_session_when_it_exists(self):
        metas = [meta('local_' + 'b' * 36, self.d, 'Projet Alpha · Conflits Studio', 5)]
        l = projets.ligne_verifier_conflits(self.d, projets.conflits_du_projet(self.d, metas), self.etat, 1000, metas)
        self.assertEqual((l['session'], l['copier']), ('local_' + 'b' * 36, ''))

    def test_closed_by_the_pm_it_never_comes_back(self):
        c = projets.conflits_du_projet(self.d, [])
        l = projets.ligne_verifier_conflits(self.d, c, self.etat, 1000, [])
        self.etat[l['cle']].update(fermee=1001, par='main')
        self.assertIsNone(projets.ligne_verifier_conflits(self.d, c, self.etat, 1000 + 30 * 86400, []))

    def test_closed_by_its_source_once_checked(self):
        c = projets.conflits_du_projet(self.d, [])
        l = projets.ligne_verifier_conflits(self.d, c, self.etat, 1000, [])
        registre.poser_dernier_passage(registre.chemin_du_studio(self.d), '14/11/2026')
        c = projets.conflits_du_projet(self.d, [])
        self.assertEqual(c['verification'], 'verifie')
        self.assertIsNone(projets.ligne_verifier_conflits(self.d, c, self.etat, 2000, []))
        self.assertEqual(self.etat[l['cle']]['par'], 'source')

    def test_not_a_studio_no_line(self):
        (self.studio / '.claude' / '.studio-manifest.json').unlink()
        c = projets.conflits_du_projet(self.d, [])
        self.assertIsNone(projets.ligne_verifier_conflits(self.d, c, self.etat, 1000, []))

    def test_the_journal_in_the_tab(self):
        conflits.main(['reprendre', self.d, '--extraction', self.extraction([decision(reponse='Voir PRJ-3, le jeudi.')]),
                       '--pm', 'Camille', '--ecrire'])
        c = projets.conflits_du_projet(self.d, [])
        self.assertEqual(c['dernier_passage'], '09/11/2026')
        self.assertEqual(c['journal'][0]['sujet'], 'Jour du comité de pilotage')
        self.assertTrue(c['journal'][0]['reprise'])
        self.assertNotIn('PRJ-3', c['journal'][0]['reponse'])

    def test_the_closed_line_survives_the_purge(self):
        cle = projets.cle_de(self.d, 'conflits', 'verifier')
        self.etat[cle] = {'studio': self.d, 'type': 'verifier', 'titre': 't', 'premiere': 0, 'vue': 0, 'fermee': 1, 'par': 'main'}
        purgees = [k for k, l in self.etat.items() if l['type'] != 'verifier' and l['fermee']]
        self.assertEqual(purgees, [])
        self.assertIn("l['type'] != 'verifier'", (SCRIPTS / 'projets.py').read_text(encoding='utf-8'))


class LePM(unittest.TestCase):
    """Who is the PM of a project sheet (PM, Q32, 2026-11-15): a marked replacement, or « (PM) » in « Responsable »."""

    def test_the_pm_row(self):
        self.assertEqual(projets.pm_dans('| **PM** | Camille Durand |\n'), 'Camille Durand')
        self.assertIsNone(projets.pm_dans('| **PM** | _à compléter_ |\n'))

    def test_a_replaced_pm_is_the_replacement(self):
        fiche = ("| **PM** | Dominique Martin ⚠️ *Remplacé le 2026-10-28 par « PM Camille Durand, Sacha Petit sur l'infra », "
                 "source `projet/stakeholders.md` — rattrapage du 2026-11-09* |\n")
        self.assertEqual(projets.pm_dans(fiche), 'Camille Durand')
        fiche = "| **PM** | Dominique Martin ⚠️ *Remplacé le 2026-10-28 par « Camille Durand », source x — rattrapage du 2026-11-09* |\n"
        self.assertEqual(projets.pm_dans(fiche), 'Camille Durand')
        self.assertEqual(projets.pm_dans('| **PM** | Dominique Martin ⚠️ *à confirmer* |\n'), 'Dominique Martin')

    def test_the_responsible_row_marked_pm(self):
        fiche = '| **Responsable** | Camille Durand (PM), Sacha Petit (CTO, tech lead), Lou Bernard (Design) |\n'
        self.assertEqual(projets.pm_dans(fiche), 'Camille Durand')
        self.assertEqual(projets.role('/x', 'Camille Durand', projets.pm_dans(fiche)), 'pm')
        self.assertEqual(projets.role('/x', 'Sacha Petit', projets.pm_dans(fiche)), 'membre')
        self.assertIsNone(projets.pm_dans('| **Responsable** | Sacha Petit (CTO) |\n'))


class Copie(unittest.TestCase):
    def test_the_connector_accepts_only_this_text_to_paste(self):
        mcp = charger('mcp_reprise_t', SCRIPTS / 'mcp_mon_studio.py')
        motif = mcp.COPIE_MOTIF[1:-1]
        self.assertTrue(re.fullmatch(motif, '/cockpit:conflits rattrapage'))
        self.assertFalse(re.fullmatch(motif, '/cockpit:conflits rattrapage; rm -rf'))
        self.assertTrue(re.fullmatch(motif, 'Q12 go'))

    def test_install_copies_the_survey_and_it_runs_from_the_copy(self):
        install = charger('install_reprise_t', SCRIPTS / 'install.py')
        self.assertTrue(install.CONFLITS_SOURCE.is_file())
        self.assertEqual(install.CONFLITS_COPY.name, 'conflits.py')
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(CONFLITS / 'conflits.py', d)
            shutil.copy(CONFLITS / 'registre.py', pathlib.Path(d) / 'registre_conflits.py')
            copie = charger('conflits_copie_t', pathlib.Path(d) / 'conflits.py')
            self.assertTrue(hasattr(copie.registre, 'tranches'))


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    A = '/studios/Projet Alpha'

    def run_page(self, c):
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
        return json.loads(r.stdout)['projetConflits']

    def base(self, **k):
        c = {'ouverts': [], 'illisibles': 0, 'session': None, 'titre_session': 'Projet Alpha · Conflits Studio',
             'commande': '/cockpit:conflits', 'lu': True, 'nouveaux': 0, 'relance': False, 'raison': '',
             'a_traiter': {'evident': 0, 'arbitrage': 0}, 'jours': 0, 'dernier_passage': None, 'journal': [],
             'tranches': 0, 'verification': 'jamais', 'texte_premiere': 'Le premier relevé des conflits de ce Studio.'}
        c.update(k)
        return c

    def test_never_checked(self):
        html = self.run_page(self.base())
        self.assertIn('Le premier relevé des conflits de ce Studio.', html)
        self.assertNotIn('Studio à jour', html)

    def test_checked_without_conflict(self):
        html = self.run_page(self.base(verification='verifie', dernier_passage='12/11/2026'))
        # The date of the last complete pass, never « à jour » without a re-read behind it (2026-11-17).
        self.assertIn('Dernier passage complet le 12/11', html)
        self.assertNotIn('à jour', html)
        self.assertIn('Passage complet du 12/11 : aucun conflit.', html)

    def test_the_journal(self):
        j = [{'sujet': 'Jour du comité', 'date': '10/11/2026', 'par': 'Camille', 'choix': 'simple discussion',
              'reponse': 'On garde le mardi.', 'reprise': True}]
        html = self.run_page(self.base(verification='verifie', dernier_passage='09/11/2026', journal=j, tranches=1))
        self.assertIn('Dernier passage complet le 09/11', html)
        self.assertNotIn('à jour', html)
        self.assertIn('<h3>Tranché</h3>', html)
        self.assertIn('gardé tel quel, le 10/11 par Camille (tranché à la main, repris)', html)
        self.assertIn('On garde le mardi.', html)
        self.assertNotIn('aucun conflit', html)


if __name__ == '__main__':
    unittest.main()
