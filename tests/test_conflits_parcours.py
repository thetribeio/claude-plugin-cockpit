"""Tests of /cockpit:conflits' script (skills/conflits/scripts/conflits.py): python3 -m unittest discover -s tests

The preview reads the Studio and writes nothing in it; the sub-agents judge extracts; after one grouped go the script
writes the safe markings next to the old passages (no byte changed, nothing removed, never twice), checks each passage
word for word first (a moved passage becomes a PM decision), registers the PM decisions, and writes the PM's answers in
batches. Every code the PM reads is followed by « · » and a short title. Synthetic Studio (tests/_studio_conflits.py)."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
import unittest.mock

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('conflits', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)
registre = conflits.registre

JUGEMENTS = [
    {'sujet': 'S1', 'classe': 'M', 'titre': 'Comité de pilotage le jeudi', 'passages': ['E1.1', 'E1.2']},
    {'sujet': 'S2', 'classe': 'PM', 'titre': 'Plafond de remise relevé', 'passages': ['E2.1', 'E2.2'],
     'contexte': "Les règles de septembre limitaient la remise à 10 % ; au point du 3 novembre, l'équipe l'a portée à 15 % "
                 "pour les commandes de plus de 50 pièces.",
     'recommande': 'remplacer', 'pourquoi': 'La règle PRJ-2 est écrite et plus récente que PRJ-1.'},
    {'sujet': 'S3', 'classe': 'M', 'titre': 'Format d’export des commandes', 'passages': ['E3.1']},
]


def sans_ajouts(apres, avant):
    """`apres` minus the lines it has and `avant` has not, in order: what was there before must come back intact."""
    a = apres.splitlines(keepends=True)
    b = avant.splitlines(keepends=True)
    out, j = [], 0
    for l in a:
        if j < len(b) and l == b[j]:
            out.append(l)
            j += 1
    return ''.join(out)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = F.make(pathlib.Path(self.tmp.name) / 'Studio - Projet Alpha')
        self.plan_chemin = pathlib.Path(self.tmp.name) / 'plan.json'
        env = unittest.mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-10'})
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = conflits.main([str(a) for a in args])
        return code, out.getvalue()

    def plan_juge(self, jugements=JUGEMENTS):
        plan = conflits.releve(self.studio)
        self.assertEqual(conflits.juger(plan, jugements), [])
        return plan

    def lire(self, rel):
        return (self.studio / rel).read_text(encoding='utf-8')


class Releve(Base):
    def test_preview_writes_nothing_in_the_studio(self):
        avant = F.snapshot(self.studio)
        code, out = self.run_cli('releve', self.studio, '--sortie', self.plan_chemin)
        self.assertEqual(code, 0)
        self.assertEqual(F.snapshot(self.studio), avant)
        self.assertFalse((self.studio / 'projet' / '.conflits').exists())
        self.assertIn('3 sujets', out)
        plan = json.loads(self.plan_chemin.read_text(encoding='utf-8'))
        self.assertEqual([s['genre'] for s in plan['sujets']], ['remplace', 'remplace', 'question'])

    def test_default_plan_goes_to_the_hidden_folder_of_the_studio(self):
        code, out = self.run_cli('releve', self.studio)
        self.assertTrue((self.studio / 'projet' / '.conflits' / 'apercu-2026-11-10.json').exists())

    def test_candidates_carry_short_extracts_and_the_client_flag(self):
        plan = conflits.releve(self.studio)
        s1, s2 = plan['sujets'][:2]
        self.assertEqual({x['fichier'] for x in s1['extraits']}, {'0-commerce/cahier-des-charges.md', '2-cadrage/roadmap.md'})
        self.assertTrue(s1['client'])
        self.assertEqual(s2['ancien']['code'], 'PRJ-1')
        self.assertEqual(s2['nouveau']['date'], '03/11/2026')
        for s in plan['sujets']:
            for x in s['extraits']:
                self.assertLessEqual(len(x['contexte']), 700)
                self.assertLessEqual(len(x['contexte'].splitlines()), 2 * conflits.CONTEXTE_LIGNES + 1)

    def test_not_a_studio(self):
        code, out = self.run_cli('releve', self.tmp.name)
        self.assertEqual(code, 2)

    def test_estimate_is_said_in_percent_of_the_week_and_writes_nothing(self):
        avant = F.snapshot(self.studio)
        code, out = self.run_cli('estimer', self.studio)
        self.assertEqual(F.snapshot(self.studio), avant)
        self.assertIn('% de ta semaine', out)
        self.assertIn('écrits par script, sans modèle, 0 $', out)

    def test_estimate_above_the_ceiling_proposes_one_folder_at_a_time(self):
        c = conflits.estimer_cout({'sujets': [{'extraits': [{'contexte': 'x' * 700}] * 6,
                                               'ancien': {'texte': 'a'}, 'nouveau': {'texte': 'b'}}] * 400})
        self.assertTrue(c['au_dessus_du_plafond'])
        self.assertIn('--dossier', conflits.texte_cout(c, ['0-commerce', '2-cadrage']))

    def test_a_batch_holds_ten_subjects_and_no_bare_code(self):
        plan = conflits.releve(self.studio)
        lot = conflits.texte_lot(plan, 1)
        self.assertIn('S2 · Plafond de remise', lot)
        self.assertIn('PRJ-1 · Plafond de remise', lot)
        self.assertEqual(conflits.codes_nus(lot), [])


class Apercu(Base):
    def test_table_in_words_and_no_code(self):
        plan = self.plan_juge()
        texte = conflits.apercu(plan)
        self.assertIn('| Comité de pilotage le jeudi | marquage sûr |', texte)
        self.assertIn('| Plafond de remise relevé | décision à prendre |', texte)
        self.assertIn('Décisions à prendre : 1', texte)
        self.assertIn('| oui |', texte)
        self.assertIn('% de ta semaine', texte)
        self.assertEqual(registre.codes_pour_le_pm(texte), [], texte)

    def test_the_no_code_check_catches_every_kind(self):
        self.assertEqual(registre.codes_pour_le_pm('Voir C3, PRJ-33 et D2 · Push, classe M ou PM, cause B, S1, E1.2.'),
                         ['C3', 'PRJ-33', 'D2', 'M', 'PM', 'B', 'S1', 'E1.2'])
        self.assertEqual(registre.codes_pour_le_pm("C'est à confirmer, d'abord en mars."), [])
        self.assertEqual(registre.sans_codes('remise selon PRJ-2 (PRJ-99)', {'PRJ-2': 'la remise relevée'}),
                         'remise selon la remise relevée')

    def test_a_revirement_or_a_summary_alone_is_never_a_safe_marking(self):
        plan = conflits.releve(self.studio)
        conflits.juger(plan, [dict(JUGEMENTS[0], resume_seul=True)])
        self.assertEqual(plan['jugements']['S1']['classe'], 'PM')
        self.assertEqual(plan['jugements']['S1']['recommande'], 'à confirmer avec le client')

    def test_a_bad_judgment_is_reported_not_merged(self):
        plan = conflits.releve(self.studio)
        erreurs = conflits.juger(plan, [{'sujet': 'S9', 'classe': 'M'}, {'sujet': 'S1', 'classe': 'X'}])
        self.assertEqual(len(erreurs), 2)
        self.assertEqual(plan['jugements'], {})


class Ecrire(Base):
    def test_markings_are_additive_and_next_to_the_old_text(self):
        avant = F.snapshot(self.studio)
        plan = self.plan_juge()
        r = conflits.ecrire(plan, 'Camille')
        self.assertEqual(r['marquages']['pose'], 3)
        for rel in ('0-commerce/cahier-des-charges.md', '2-cadrage/roadmap.md', 'projet/questions-ouvertes.md'):
            apres = (self.studio / rel).read_bytes().decode('utf-8')
            self.assertEqual(sans_ajouts(apres, avant[rel].decode('utf-8')), avant[rel].decode('utf-8'), rel)
            self.assertEqual(len(apres.splitlines()), len(avant[rel].decode('utf-8').splitlines()) + 1, rel)
        roadmap = self.lire('2-cadrage/roadmap.md').splitlines()
        self.assertEqual(roadmap[3], '⚠️ Remplacé le 20/10/2026 par Comité de pilotage le jeudi, source '
                                     'sources/2026-10-20-mail-atelier.md — rattrapage du 10/11/2026')
        q = self.lire('projet/questions-ouvertes.md').splitlines()
        self.assertTrue(q[3].startswith('✅ Tranchée le 25/10/2026 par Export des commandes en format tableur'), q[3])
        # The PM decision is not written in the documents before its answer.
        self.assertEqual(self.lire('2-cadrage/perimetre.md'), F.PERIMETRE)

    def test_a_table_row_is_marked_under_the_table(self):
        plan = self.plan_juge([dict(JUGEMENTS[1], classe='M')])
        conflits.ecrire(plan, 'Camille')
        cdc = self.lire('0-commerce/cahier-des-charges.md').splitlines()
        i = cdc.index('| Export | Aucune |')
        # A blank line first, so that the marking is not read as a new row; it names the row it is for.
        self.assertEqual(cdc[i + 1], '')
        self.assertTrue(cdc[i + 2].startswith('⚠️ Rangée « Standard » : Remplacé le 03/11/2026 par PRJ-2 · Remise relevée'), cdc[i + 2])
        # Marked once: a second pass finds the row's marking under the table.
        self.assertEqual(conflits.poser(self.studio, '0-commerce/cahier-des-charges.md',
                                        '| Standard | La remise est limitée à 10 % des commandes. |', 11, 'x', 'y'), 'deja')
        per = self.lire('2-cadrage/perimetre.md').splitlines()
        self.assertTrue(per[3].startswith('  ⚠️ Remplacé'), per[3])     # under a list item, indented

    def test_never_marks_twice(self):
        plan = self.plan_juge()
        conflits.ecrire(plan, 'Camille')
        une_fois = F.snapshot(self.studio)
        conflits.ecrire(plan, 'Camille')                    # same plan again
        self.assertEqual({k: v for k, v in F.snapshot(self.studio).items() if 'changelog' not in k},
                         {k: v for k, v in une_fois.items() if 'changelog' not in k})
        # A new preview another day neither finds the marked passages again nor marks them twice.
        with unittest.mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-20'}):
            plan2 = conflits.releve(self.studio)
            self.assertNotIn('remplace', [s['genre'] for s in plan2['sujets'] if s['titre'].startswith('Comité')])
            plan3 = conflits.releve(self.studio)
            plan3['jugements'] = {}
            conflits.juger(plan3, [j for j in JUGEMENTS if any(s['id'] == j['sujet'] for s in plan3['sujets'])])
            conflits.ecrire(plan3, 'Camille')
        for rel in ('2-cadrage/roadmap.md', '0-commerce/cahier-des-charges.md', 'projet/questions-ouvertes.md'):
            self.assertLessEqual(self.lire(rel).count('Comité de pilotage le jeudi, source'), 1, rel)
            self.assertLessEqual(self.lire(rel).count('✅ Tranchée'), 1, rel)

    def test_poser_twice_on_the_same_passage(self):
        args = (self.studio, '2-cadrage/roadmap.md', 'Le comité de pilotage du premier mardi du mois valide chaque lot.', 3,
                '⚠️ Remplacé le 20/10/2026 par X, source y — rattrapage du 10/11/2026', 'par X, source y')
        self.assertEqual(conflits.poser(*args), 'pose')
        self.assertEqual(conflits.poser(*args[:5], 'par X, source y'), 'deja')

    def test_a_moved_passage_becomes_a_pm_decision_and_nothing_is_written_there(self):
        plan = self.plan_juge()
        (self.studio / '2-cadrage/roadmap.md').write_text('# Roadmap\n\nLe comité de pilotage, premier mardi, valide chaque lot.\n',
                                                         encoding='utf-8')
        avant = self.lire('2-cadrage/roadmap.md')
        r = conflits.ecrire(plan, 'Camille')
        self.assertEqual(r['devenus_decisions'], ['S1'])
        self.assertEqual(self.lire('2-cadrage/roadmap.md'), avant)
        self.assertIn('S1', [d['sujet'] for d in plan['decisions']])
        cas = registre.lire_fichier(self.studio / 'projet' / 'conflits.md')['cas']
        self.assertEqual(len(cas), 2)

    def test_pm_decisions_go_to_the_register_with_the_last_pass_and_the_journal(self):
        plan = self.plan_juge()
        conflits.ecrire(plan, 'Camille')
        r = registre.lire_fichier(self.studio / 'projet' / 'conflits.md')
        self.assertEqual(r['illisibles'], [])
        self.assertEqual(r['dernier_passage'], '10/11/2026')
        c1 = r['cas'][0]
        self.assertEqual((c1['id'], c1['sujet'], c1['etat'], c1['communique']), ('C1', 'Plafond de remise relevé', 'ouvert', True))
        self.assertEqual(c1['ancienne']['source'], 'projet/regles-metier.md')
        self.assertIn('| 2026-11-10 | Conflits, rattrapage : 3 marquages', self.lire('projet/changelog.md'))

    def test_an_addition_goes_at_the_end_never_in_a_client_document(self):
        jug = [JUGEMENTS[0], JUGEMENTS[1], dict(JUGEMENTS[2], classe='absence',
                                                absence={'fichier': '2-cadrage/perimetre.md', 'texte': 'Export des commandes chaque lundi'})]
        plan = self.plan_juge(jug)
        conflits.ecrire(plan, 'Camille')
        self.assertTrue(self.lire('2-cadrage/perimetre.md').startswith(F.PERIMETRE))
        self.assertIn('➕ Ajouté le 10/11/2026 : Export des commandes chaque lundi', self.lire('2-cadrage/perimetre.md'))

    def test_an_addition_in_a_client_document_becomes_a_pm_decision(self):
        plan = conflits.releve(self.studio)
        conflits.juger(plan, [dict(JUGEMENTS[1], classe='absence',
                                   absence={'fichier': '0-commerce/cahier-des-charges.md', 'texte': 'Remise à 15 %'})])
        self.assertEqual(plan['absences'], [])
        self.assertEqual(len(plan['decisions']), 1)


class Revue(Base):
    """Review of 2026-11-10: each finding has its test."""

    def test_an_unreadable_file_is_never_written(self):
        latin = '# Historique\n\n| 2026-09-01 | Écrit en Latin-1 | x |\n'.encode('latin-1')
        (self.studio / 'projet' / 'changelog.md').write_bytes(latin)
        plan = self.plan_juge()
        (self.studio / '2-cadrage' / 'roadmap.md').write_bytes(F.ROADMAP.encode('latin-1'))   # after the preview
        r = conflits.ecrire(plan, 'Camille')
        self.assertEqual((self.studio / 'projet' / 'changelog.md').read_bytes(), latin)
        self.assertEqual((self.studio / '2-cadrage' / 'roadmap.md').read_bytes(), F.ROADMAP.encode('latin-1'))
        self.assertIn('S1', r['devenus_decisions'])
        self.assertEqual(conflits.journal(self.studio, 'x'), 'illisible')
        (self.studio / '2-cadrage' / 'perimetre.md').write_bytes(F.PERIMETRE.encode('latin-1'))
        self.assertEqual(conflits.ajouter_en_fin(self.studio, '2-cadrage/perimetre.md', 'x'), 'illisible')
        self.assertEqual((self.studio / '2-cadrage' / 'perimetre.md').read_bytes(), F.PERIMETRE.encode('latin-1'))

    def test_writes_stay_inside_the_studio_on_text_files(self):
        dehors = pathlib.Path(self.tmp.name) / 'dehors.md'
        dehors.write_text('rien\n', encoding='utf-8')
        for rel in ('../dehors.md', str(dehors), 'projet/conflits.md', '2-cadrage/story-mapping.json',
                    'projet/changelog.md', 'sources/2026-10-20-mail-atelier.md', 'projet/decisions-log.md'):
            self.assertEqual(conflits.ajouter_en_fin(self.studio, rel, '➕ x'), 'hors', rel)
        self.assertEqual(dehors.read_text(encoding='utf-8'), 'rien\n')
        self.assertIsNone(conflits.cible_refusee(self.studio, 'projet/regles-metier.md', ajout=True))
        plan = conflits.releve(self.studio)
        conflits.juger(plan, [dict(JUGEMENTS[2], classe='absence', absence={'fichier': '../dehors.md', 'texte': 'x'})])
        self.assertEqual(plan['absences'], [])
        self.assertEqual(len(plan['decisions']), 1)

    def test_replaced_rules_go_to_the_living_document_never_to_a_raw_source(self):
        plan = self.plan_juge()
        conflits.ecrire(plan, 'Camille')
        d = plan['decisions'][0]
        self.assertEqual(d['ancienne']['document'], 'projet/regles-metier.md')
        d['ancienne']['source'] = 'sources/2026-11-03-cr-point.md'           # what the old code took as its home
        r = conflits.repondre(plan, [{'cas': d['cas'], 'choix': 'remplacer'}], 'Camille')
        self.assertIn('## Règles remplacées', self.lire('projet/regles-metier.md'))
        self.assertNotIn('Règles remplacées', self.lire('sources/2026-11-03-cr-point.md'))
        d2 = dict(d, cas=None, reponse=None, ecrit=False, ancienne=dict(d['ancienne'], document=None))
        plan['decisions'].append(d2)
        d2['cas'] = registre.ajouter(self.studio / 'projet' / 'conflits.md', 'Autre cas', dict(d['ancienne'], texte='autre'),
                                     d['nouvelle'], False)
        r = conflits.repondre(plan, [{'cas': d2['cas'], 'choix': 'remplacer'}], 'Camille')
        self.assertTrue(any('Règles remplacées' in x for x in r['details']), r)

    def test_the_marking_key_does_not_depend_on_the_sub_agent_wording(self):
        plan = self.plan_juge([dict(JUGEMENTS[0], decision='Le comité passe au jeudi')])
        conflits.ecrire(plan, 'Camille')
        plan2 = conflits.releve(self.studio)
        plan2['sujets'] = plan['sujets']                     # the same subjects judged again, worded otherwise
        plan2['jugements'] = {}
        conflits.juger(plan2, [dict(JUGEMENTS[0], decision='Comité désormais le jeudi', nouvelle={'source': 'autre.md'})])
        conflits.ecrire(plan2, 'Camille')
        for rel in ('2-cadrage/roadmap.md', '0-commerce/cahier-des-charges.md'):
            self.assertEqual(self.lire(rel).count('⚠️'), 1, rel)

    def test_a_marking_belongs_to_its_own_passage(self):
        texte = '# R\n\n- Le comité se tient le mardi.\n\n- Le comité se tient le mardi.\n' \
                '  ⚠️ Remplacé le 20/10/2026 par X, source y — rattrapage du 10/11/2026\n'
        (self.studio / '2-cadrage' / 'double.md').write_text(texte, encoding='utf-8')
        self.assertEqual(conflits.poser(self.studio, '2-cadrage/double.md', '- Le comité se tient le mardi.', 3,
                                        '⚠️ Remplacé le 20/10/2026 par X, source y — rattrapage du 10/11/2026', 'par X, source y'), 'pose')
        self.assertEqual(self.lire('2-cadrage/double.md').count('⚠️'), 2)


    def test_a_case_is_registered_once_whatever_the_wording(self):
        plan = self.plan_juge()
        conflits.ecrire(plan, 'Camille')
        plan2 = conflits.releve(self.studio)
        self.assertNotIn('Plafond de remise', [x['titre'] for x in plan2['sujets']])      # known to the register
        plan2['sujets'], plan2['jugements'] = plan['sujets'], {}
        conflits.juger(plan2, [JUGEMENTS[0], dict(JUGEMENTS[1], titre='Remise relevée à 15 %',
                                                  ancienne={'texte': 'Remise plafonnée à 10 %'}), JUGEMENTS[2]])
        conflits.ecrire(plan2, 'Camille')
        self.assertEqual(len(registre.lire_fichier(self.studio / 'projet' / 'conflits.md')['cas']), 1)

    def juger_tout(self, plan, sauf=()):
        par_titre = dict(zip(('Comité de pilotage le premier mardi', 'Plafond de remise'), JUGEMENTS))
        jug = [dict(par_titre.get(x['titre'], JUGEMENTS[2]), sujet=x['id']) for x in plan['sujets'] if x['titre'] not in sauf]
        self.assertEqual(conflits.juger(plan, jug), [])

    def test_last_pass_only_after_a_complete_pass(self):
        chemin = self.studio / 'projet' / 'conflits.md'
        plan = conflits.releve(self.studio)
        self.juger_tout(plan, sauf=('Comité de pilotage le premier mardi',))      # a batch missing
        conflits.ecrire(plan, 'Camille')
        self.assertIsNone(registre.lire_fichier(chemin)['dernier_passage'])
        plan = conflits.releve(self.studio)
        self.juger_tout(plan)
        conflits.ecrire(plan, 'Camille', decisions_seules=True)
        self.assertIsNone(registre.lire_fichier(chemin)['dernier_passage'])
        plan = conflits.releve(self.studio, dossier='2-cadrage')
        self.juger_tout(plan)
        conflits.ecrire(plan, 'Camille')
        self.assertIsNone(registre.lire_fichier(chemin)['dernier_passage'])
        plan = conflits.releve(self.studio)
        self.juger_tout(plan)
        conflits.ecrire(plan, 'Camille')
        self.assertEqual(registre.lire_fichier(chemin)['dernier_passage'], '10/11/2026')

    def test_an_old_value_without_date_is_never_dated_today(self):
        plan = conflits.releve(self.studio)
        plan['sujets'][1]['ancien']['date'] = None
        conflits.juger(plan, JUGEMENTS)
        os.utime(self.studio / 'projet' / 'regles-metier.md', (1757000000, 1757000000))      # 04/09/2025
        conflits.ecrire(plan, 'Camille')
        c = registre.lire_fichier(self.studio / 'projet' / 'conflits.md')['cas'][0]
        self.assertEqual(c['ancienne']['date'], '04/09/2025')
        self.assertIn('date inconnue', c['ancienne']['texte'])

    def test_a_case_written_by_the_ingestion_gets_a_form_and_the_replace_effect(self):
        registre.ajouter(self.studio / 'projet' / 'conflits.md', 'Plafond de remise',
                         {'texte': 'remise limitée à 10 % des commandes', 'source': 'projet/regles-metier.md', 'date': '15/09/2026'},
                         {'texte': 'remise portée à 15 % selon PRJ-2', 'source': 'sources/2026-11-03-cr-point.md', 'date': '03/11/2026'},
                         True, '09/11/2026')
        code, out = self.run_cli('formulaires', self.plan_chemin, '--studio', self.studio)
        fs = json.loads(out)['formulaires']
        self.assertEqual(len(fs), 1)
        self.assertTrue(fs[0]['question'].startswith('Plafond de remise\n'))
        self.assertIn('Remise relevée pour les grosses commandes', fs[0]['question'])
        self.assertEqual(registre.codes_pour_le_pm(fs[0]['question']), [])
        self.assertTrue(fs[0]['discuter']['extraits'])
        code, out = self.run_cli('trancher', self.studio, 'C1', 'remplacer', '--pm', 'Camille')
        self.assertIn('actée par Camille', self.lire('projet/regles-metier.md'))
        self.assertIn('⚠️ Remplacé le 03/11/2026 par C1 · Plafond de remise', self.lire('2-cadrage/perimetre.md'))  # in the Studio, the code stays

    def test_no_code_for_the_pm_codes_kept_in_the_register_and_markings(self):
        registre.ajouter(self.studio / 'projet' / 'conflits.md', 'Remise selon PRJ-2',
                         {'texte': 'remise limitée à 10 % des commandes (PRJ-1)', 'source': 'projet/regles-metier.md', 'date': '15/09/2026'},
                         {'texte': 'remise portée à 15 % selon PRJ-2 et PRJ-99', 'source': 'sources/2026-11-03-cr-point.md', 'date': '03/11/2026'},
                         False)
        rendus = []
        code, out = self.run_cli('ouverts', self.studio)
        rendus.append(out)
        code, out = self.run_cli('formulaires', self.plan_chemin, '--studio', self.studio)
        for f in json.loads(out)['formulaires']:
            rendus += [f['header'], f['question'], f['discuter']['pourquoi'], f['discuter']['ancienne']['texte'],
                       f['discuter']['nouvelle']['texte'], f['discuter']['recommande'], f['depend_de'] or ''] \
                + f['discuter']['en_depend'] + [x['texte'] + ' ' + x['ou'] for x in f['discuter']['extraits']] \
                + [o['label'] + ' ' + o['description'] for o in f['options']]
        code, out = self.run_cli('trancher', self.studio, 'remise', 'remplacer', '--pm', 'Camille')
        rendus.append(out)
        for t in rendus:
            self.assertEqual(registre.codes_pour_le_pm(t), [], t)
        reg = (self.studio / 'projet' / 'conflits.md').read_text(encoding='utf-8')
        self.assertIn('### C1 · Remise selon PRJ-2', reg)                # the register keeps its codes
        self.assertIn('par C1 · Remise selon PRJ-2', self.lire('2-cadrage/perimetre.md'))   # and so do the markings

    def test_a_title_or_context_with_a_code_is_refused(self):
        plan = conflits.releve(self.studio)
        erreurs = conflits.juger(plan, [dict(JUGEMENTS[1], titre='Remise PRJ-2'),
                                        dict(JUGEMENTS[0], contexte='Voir la décision D2.')])
        self.assertEqual(len(erreurs), 2)
        self.assertEqual(plan['jugements'], {})

    def test_keep_as_is_says_the_new_information_is_ignored(self):
        self.assertEqual(conflits.DESCRIPTION_GARDER,
                         "On ignore la nouvelle information ; l'ancienne valeur reste en vigueur. Le registre garde la trace.")


class Decisions(Base):
    def prepare(self):
        plan = self.plan_juge()
        conflits.ecrire(plan, 'Camille')
        conflits.sauver_plan(self.plan_chemin, plan)
        return plan

    def test_forms_are_prepared_in_full_title_first(self):
        plan = self.prepare()
        fs = conflits.formulaires(plan)
        self.assertEqual(len(fs), 1)
        f = fs[0]
        premiere = f['question'].splitlines()
        self.assertEqual(premiere[0], 'Plafond de remise relevé')
        self.assertTrue(premiere[1].startswith('Les règles de septembre limitaient la remise'))
        labels = [o['label'] for o in f['options']]
        self.assertEqual(labels, ['Remplacer (Recommandé)', 'À confirmer avec le client', 'Garder tel quel', "Discuter d'abord"])
        self.assertEqual(f['options'][2]['description'], conflits.DESCRIPTION_GARDER)
        self.assertEqual(f['options'][3]['description'], "Tu m'expliques, on en parle, puis tu me reposes la question.")
        self.assertLessEqual(len(f['header']), 12)
        self.assertTrue(f['discuter']['extraits'])
        self.assertIn('Remise relevée pour les grosses commandes', f['discuter']['pourquoi'])
        self.assertNotIn('PRJ', f['discuter']['pourquoi'])
        self.assertIn('PRJ-2', f['references']['codes'])             # on request only

    def test_no_code_in_any_form(self):
        plan = self.prepare()
        for f in conflits.formulaires(plan):
            textes = [f['header'], f['question'], f['discuter']['pourquoi'], f['discuter']['ancienne']['texte'],
                      f['discuter']['nouvelle']['texte']] + [o['label'] + ' ' + o['description'] for o in f['options']] \
                + [x['texte'] for x in f['discuter']['extraits']]
            for t in textes:
                self.assertEqual(registre.codes_pour_le_pm(t), [], t)

    def test_keep_as_is_is_written_simple_discussion(self):
        self.prepare()
        code, out = self.run_cli('repondre', self.plan_chemin, '--pm', 'Camille',
                                 '--reponses', json.dumps([{'cas': 'C1', 'choix': 'Garder tel quel'}]))
        self.assertEqual(out.strip(), '1 faites, 0 restent.')
        c1 = registre.lire_fichier(self.studio / 'projet' / 'conflits.md')['cas'][0]
        self.assertEqual(c1['tranche'], {'date': '10/11/2026', 'par': 'Camille', 'choix': 'simple discussion'})
        self.assertEqual(self.lire('2-cadrage/perimetre.md'), F.PERIMETRE)
        self.assertEqual(conflits.formulaires(conflits.charger_plan(self.plan_chemin)), [])

    def test_replace_marks_and_keeps_the_old_rule_in_replaced_rules(self):
        self.prepare()
        regles_avant = self.lire('projet/regles-metier.md')
        self.run_cli('repondre', self.plan_chemin, '--pm', 'Camille',
                     '--reponses', json.dumps([{'cas': 'C1', 'choix': 'Remplacer (Recommandé)'}]))
        regles = self.lire('projet/regles-metier.md')
        self.assertTrue(regles.startswith(regles_avant))
        self.assertIn('## Règles remplacées', regles)
        self.assertIn('actée par Camille le 10/11/2026 (C1 · Plafond de remise relevé)', regles)
        self.assertIn('⚠️ Remplacé le 03/11/2026 par PRJ-2 · Remise relevée', self.lire('2-cadrage/perimetre.md'))
        self.assertIn('Conflit C1 · Plafond de remise relevé : tranché par Camille, remplacer', self.lire('projet/changelog.md'))
        # Answered again (a resumed session): nothing twice.
        self.run_cli('repondre', self.plan_chemin, '--pm', 'Camille', '--reponses', json.dumps([{'cas': 'C1', 'choix': 'remplacer'}]))
        self.assertEqual(self.lire('projet/regles-metier.md').count('(C1 · '), 1)
        self.assertEqual(self.lire('2-cadrage/perimetre.md').count('⚠️'), 1)

    def test_confirm_with_client_notes_the_new_value_next_to_the_old(self):
        self.prepare()
        self.run_cli('repondre', self.plan_chemin, '--pm', 'Camille',
                     '--reponses', json.dumps([{'cas': 'C1', 'choix': 'À confirmer avec le client'}]))
        per = self.lire('2-cadrage/perimetre.md')
        self.assertIn('ℹ️ À confirmer avec le client depuis le 10/11/2026', per)
        self.assertNotIn('Règles remplacées', self.lire('projet/regles-metier.md'))

    def test_voice_fallback_and_reopen(self):
        plan = self.plan_juge()
        conflits.ecrire(plan, 'Camille')
        conflits.sauver_plan(conflits.chemin_plan_defaut(self.studio), plan)
        # By its title: never an id required.
        code, out = self.run_cli('trancher', self.studio, 'plafond de remise', 'Garder tel quel', '--pm', 'Camille')
        self.assertEqual(code, 0, out)
        self.assertEqual(registre.lire_fichier(self.studio / 'projet' / 'conflits.md')['cas'][0]['tranche']['choix'],
                         'simple discussion')
        code, out = self.run_cli('rouvrir', self.studio, 'la remise')
        self.assertIn('« Plafond de remise relevé » : rouvert', out)
        self.assertEqual(registre.lire_fichier(self.studio / 'projet' / 'conflits.md')['cas'][0]['etat'], 'ouvert')
        # By its id, when the PM says it.
        code, out = self.run_cli('trancher', self.studio, 'C1', 'remplacer', '--pm', 'Camille')
        self.assertEqual(code, 0, out)
        self.run_cli('rouvrir', self.studio, 'C1')
        code, out = self.run_cli('trancher', self.studio, 'livraison', 'remplacer', '--pm', 'Camille')
        self.assertEqual(code, 2)
        self.assertIn('Aucun conflit ne répond', out)
        code, out = self.run_cli('ouverts', self.studio)
        self.assertTrue(out.startswith('« Plafond de remise relevé » :'), out)
        self.assertEqual(registre.codes_pour_le_pm(out), [], out)

    def test_a_dependent_decision_comes_right_after(self):
        plan = conflits.releve(self.studio)
        conflits.juger(plan, [dict(JUGEMENTS[0], classe='PM', depend_de='S2'), JUGEMENTS[1]])
        self.assertEqual([d['sujet'] for d in plan['decisions']], ['S2', 'S1'])


class Incremental(Base):
    def test_the_reread_reads_only_what_changed_since_the_last_pass(self):
        plan = self.plan_juge()
        conflits.ecrire(plan, 'Camille')
        with unittest.mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-12'}):
            self.assertEqual(conflits.releve(self.studio, incremental=True)['sujets'], [])
            p = self.studio / 'projet' / 'decisions-log.md'
            p.write_text(p.read_text(encoding='utf-8') + """
### 2026-11-11 : Visio du comité supprimée

- **Statut :** actif
- **Décision :** le comité de pilotage se tient sur place, dans les locaux.
- **Source :** `sources/2026-11-11-cr.md`

### 2026-10-01 : Comité en visio

- **Statut :** superseded
- **Remplacé par :** 2026-11-11 — Visio du comité supprimée
- **Décision :** le comité de pilotage se tient en visio.
""", encoding='utf-8')
            plan2 = conflits.releve(self.studio, incremental=True)
            self.assertEqual(plan2['mode'], 'relecture')
            self.assertEqual([s['titre'] for s in plan2['sujets']], ['Comité en visio'])


if __name__ == '__main__':
    unittest.main()
