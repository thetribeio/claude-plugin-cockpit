"""Tests of the three levels of /cockpit:conflits (PM, 2026-11-10): python3 -m unittest discover -s tests

- safe markings, written on one grouped go, with a recap by file;
- obvious cases, pre-answered: one list, one form; the PM can take one out (it joins the real questions) or change an
  answer, in free text; a word that points at no case or at several writes nothing;
- real decisions, one form each: text gone to the client, money or contract, a source only oral, the PM's own knowledge.
The queue shared with /studio:auto-ingest: optional fields of a register case (Niveau, Recommandé, Pourquoi, Contexte,
Raisons, Ajouté par). The weekly pass: only what is new, no question, nothing marked in the documents. Mon Studio: the
new cases not seen (dot), the reminder from 10 cases or 14 days (per Studio), the global tab. Synthetic data."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import datetime as dt
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
spec = importlib.util.spec_from_file_location('conflits_niveaux', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)
registre = conflits.registre
spec = importlib.util.spec_from_file_location('projets_niveaux', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'projets.py')
projets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projets)
spec = importlib.util.spec_from_file_location('question_niveaux', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'question.py')
question = importlib.util.module_from_spec(spec)
spec.loader.exec_module(question)
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'

# S1: a safe marking. S2: an obvious case (written rule, no money, no client text). S3: a real decision (the sub-agent
# says only the PM knows).
JUGEMENTS = [
    {'sujet': 'S1', 'classe': 'M', 'titre': 'Comité de pilotage le jeudi', 'passages': ['E1.1', 'E1.2']},
    {'sujet': 'S2', 'classe': 'PM', 'titre': 'Plafond de remise relevé', 'passages': ['E2.2'],
     'contexte': "Les règles de septembre limitaient la remise à 10 % ; au point du 3 novembre, l'équipe l'a portée à 15 %.",
     'recommande': 'remplacer', 'pourquoi': 'La nouvelle règle est écrite et plus récente.'},
    {'sujet': 'S3', 'classe': 'PM', 'titre': 'Format d’export des commandes', 'passages': ['E3.1'],
     'contexte': "La question de l'export restait ouverte ; le point du 25 octobre a choisi un fichier tableur.",
     'recommande': 'à confirmer avec le client', 'pourquoi': 'Seul le PM sait ce que la comptabilité a accepté.',
     'savoir_pm': True},
]

CAS = """### C{n} · {sujet}
- **Détecté le** : {detecte}
- **Ancienne valeur** : ancienne {n} (source : projet/regles-metier.md, 15/09/2026)
- **Nouvelle valeur** : nouvelle {n} (source : sources/2026-11-0{n}-cr.md, 0{n}/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
{extra}- **État** : {etat}
"""


def registre_texte(*cas):
    return '# Registre des conflits\n\n' + '\n'.join(CAS.format(**c) for c in cas)


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

    def plan_ecrit(self):
        plan = conflits.releve(self.studio)
        self.assertEqual(conflits.juger(plan, JUGEMENTS), [])
        r = conflits.ecrire(plan, 'Camille')
        conflits.sauver_plan(self.plan_chemin, plan)
        return plan, r


class Niveaux(Base):
    def test_levels_from_the_studio_and_the_sub_agent(self):
        plan, _ = self.plan_ecrit()
        par = {d['sujet']: d for d in plan['decisions']}
        self.assertEqual(par['S2']['niveau'], 'evident')
        self.assertEqual(par['S3']['niveau'], 'arbitrage')
        self.assertEqual(par['S3']['raisons'], [conflits.RAISON_SAVOIR])

    def test_money_contract_client_and_oral_make_a_real_decision(self):
        s = {'client': False, 'extraits': []}
        base = {'ancienne': {'texte': 'remise à 10 %', 'source': 'projet/regles-metier.md'}, 'titre': 'Remise',
                'nouvelle': {'texte': 'remise à 15 %', 'source': 'sources/2026-11-03-mail.md'}, 'contexte': ''}
        self.assertEqual(conflits.niveau_de({}, s, base), ('evident', []))
        argent = dict(base, nouvelle={'texte': 'budget porté à 130 k€', 'source': 'sources/mail.md'})
        self.assertIn(conflits.RAISON_ARGENT, conflits.niveau_de({}, s, argent)[1])
        signe = dict(base, contexte='Le contrat signé du 6 novembre fixe autre chose.')
        self.assertIn(conflits.RAISON_ARGENT, conflits.niveau_de({}, s, signe)[1])
        oral = dict(base, nouvelle={'texte': 'remise à 15 %', 'source': '2-cadrage/reunions/2026-11-09-debrief.md'})
        self.assertEqual(conflits.niveau_de({}, s, oral), ('arbitrage', [conflits.RAISON_ORAL]))
        self.assertIn(conflits.RAISON_ORAL, conflits.niveau_de({}, s, dict(base, resume_seul=True))[1])
        client = conflits.niveau_de({}, s, base, [{'client': True, 'passage': 'remise à 10 %'}])
        self.assertEqual(client, ('arbitrage', [conflits.RAISON_CLIENT]))

    def test_a_passage_gone_to_the_client_makes_a_real_decision(self):
        plan = conflits.releve(self.studio)
        conflits.juger(plan, [dict(JUGEMENTS[1], passages=['E2.1', 'E2.2'])])
        self.assertEqual(plan['decisions'][0]['raisons'], [conflits.RAISON_CLIENT])

    def test_a_whole_chain_shares_the_real_level(self):
        plan = {'sujets': [], 'jugements': {}}
        d = lambda sid, dep, niveau: {'sujet': sid, 'depend_de': dep, 'niveau': niveau, 'raisons': []}
        a, b, c = d('S1', 'S2', 'arbitrage'), d('S2', 'S3', 'evident'), d('S3', None, 'evident')
        with unittest.mock.patch.object(conflits, 'nouvelle_decision', side_effect=[a, b, c]):
            plan = {'sujets': [{'id': x} for x in ('S1', 'S2', 'S3')], 'studio': str(self.studio),
                    'jugements': {x: {'classe': 'PM'} for x in ('S1', 'S2', 'S3')}}
            conflits.construire(plan)
        self.assertEqual([x['niveau'] for x in plan['decisions']], ['arbitrage'] * 3)

    def test_a_dependent_decision_shares_the_real_level(self):
        js = [dict(JUGEMENTS[1]), dict(JUGEMENTS[2], depend_de='S2')]
        plan = conflits.releve(self.studio)
        conflits.juger(plan, js)
        self.assertEqual({d['niveau'] for d in plan['decisions']}, {'arbitrage'})

    def test_register_carries_the_queue_fields_without_code(self):
        self.plan_ecrit()
        texte = self.lire_registre()
        self.assertIn('- **Niveau** : évident', texte)
        self.assertIn('- **Niveau** : arbitrage', texte)
        self.assertIn('- **Recommandé** : remplacer', texte)
        self.assertIn('- **Raisons** : savoir propre au PM', texte)
        self.assertIn('- **Ajouté par** : rattrapage', texte)
        for ligne in texte.splitlines():
            if ligne.startswith(('- **Pourquoi**', '- **Contexte**')):
                self.assertEqual(registre.codes_pour_le_pm(ligne.split(' : ', 1)[1]), [], ligne)
        r = registre.lire(texte)
        self.assertEqual(r['illisibles'], [])
        self.assertEqual({c['file']['niveau'] for c in r['cas']}, {'evident', 'arbitrage'})

    def lire_registre(self):
        return (self.studio / 'projet' / 'conflits.md').read_text(encoding='utf-8')

    def test_recap_of_the_grouped_go(self):
        code, out = self.run_cli('releve', self.studio, '--sortie', self.plan_chemin)
        plan = conflits.charger_plan(self.plan_chemin)
        conflits.juger(plan, JUGEMENTS)
        conflits.sauver_plan(self.plan_chemin, plan)
        code, out = self.run_cli('ecrire', self.plan_chemin, '--pm', 'Camille')
        self.assertEqual(code, 0)
        self.assertIn('Récapitulatif :', out)
        self.assertIn('Comité de pilotage le jeudi', out)
        self.assertIn("1 cas évidents à valider d'un coup, puis 1 vraies décisions une par une. On enchaîne", out)
        self.assertIn('sans attendre que le PM le demande', out)            # not an end (PM, 2026-11-18)
        self.assertEqual(registre.codes_pour_le_pm(out.split('Récapitulatif :')[1].split('Suite, tout')[0]), [])

    def test_the_decisions_follow_at_once_even_after_decisions_only(self):
        self.run_cli('releve', self.studio, '--sortie', self.plan_chemin)
        plan = conflits.charger_plan(self.plan_chemin)
        conflits.juger(plan, JUGEMENTS)
        conflits.sauver_plan(self.plan_chemin, plan)
        code, out = self.run_cli('ecrire', self.plan_chemin, '--pm', 'Camille', '--decisions-seules')
        self.assertEqual(code, 0)
        self.assertIn('Suite, tout de suite, sans attendre que le PM le demande', out.splitlines()[-1])
        skill = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Enchaîne tout de suite sur les décisions (usage 3)**, dans le même tour, sans attendre que le PM le demande', skill)
        self.assertIn('Pareil après `--decisions-seules`', skill)

    def test_the_conflicts_session_puts_itself_at_the_first_level(self):
        skill = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')
        ou = skill.split('## Où ça tourne', 1)[1]
        self.assertTrue(ou.lstrip().startswith('0. **Avant tout autre geste, au premier niveau.**'))
        for mot in ('`get_session` sur elle-même', '`parentSessionId` sans être `detached`', '`detach_session` sur elle-même',
                    "Si l'outil manque ou refuse, dis-le en une ligne et continue"):
            self.assertIn(mot, ou)
        self.assertIn('puis `detach_session` pour la mettre au premier niveau', ou)     # the launcher's step 2 stays


class Evidents(Base):
    def test_list_and_one_form_without_code(self):
        self.plan_ecrit()
        code, out = self.run_cli('evidents', self.plan_chemin)
        r = json.loads(out)
        self.assertEqual([x['titre'] for x in r['liste']], ['Plafond de remise relevé'])
        self.assertIn('« Plafond de remise relevé » : remplacer', r['texte'])
        f = r['formulaire']
        self.assertEqual(f['options'][0]['label'], conflits.LIBELLE_VALIDER + conflits.RECOMMANDE)
        self.assertEqual(f['options'][-1]['label'], conflits.LIBELLE_DISCUTER)
        self.assertEqual(registre.codes_pour_le_pm(r['texte'] + f['question']), [])

    def test_real_decisions_only_in_the_forms(self):
        self.plan_ecrit()
        code, out = self.run_cli('formulaires', self.plan_chemin)
        r = json.loads(out)
        self.assertEqual([f['question'].splitlines()[0] for f in r['formulaires']], ['Format d’export des commandes'])
        self.assertEqual(r['evidents_en_attente'], 1)

    def test_validate_writes_all_in_one_go(self):
        self.plan_ecrit()
        code, out = self.run_cli('valider', self.plan_chemin, '--pm', 'Camille')
        self.assertEqual(code, 0)
        self.assertIn('1 faites', out)
        etats = {c['sujet']: c['tranche'] for c in registre.lire(self.lire())['cas']}
        self.assertEqual(etats['Plafond de remise relevé']['choix'], 'remplacer')
        self.assertIsNone(etats['Format d’export des commandes'])

    def lire(self):
        return (self.studio / 'projet' / 'conflits.md').read_text(encoding='utf-8')

    def test_taken_out_joins_the_real_questions(self):
        self.plan_ecrit()
        code, out = self.run_cli('valider', self.plan_chemin, '--pm', 'Camille', '--sortir', '["plafond de remise"]')
        self.assertEqual(code, 0)
        self.assertIn('Sortis de la liste, posés à part : « Plafond de remise relevé »', out)
        self.assertTrue(all(c['etat'] == 'ouvert' for c in registre.lire(self.lire())['cas']))
        code, out = self.run_cli('formulaires', self.plan_chemin)
        titres = [f['question'].splitlines()[0] for f in json.loads(out)['formulaires']]
        self.assertEqual(sorted(titres), sorted(['Plafond de remise relevé', 'Format d’export des commandes']))
        self.assertEqual(json.loads(self.run_cli('evidents', self.plan_chemin)[1])['liste'], [])

    def test_changed_answer_and_unknown_words_write_nothing(self):
        self.plan_ecrit()
        avant = self.lire()
        code, out = self.run_cli('valider', self.plan_chemin, '--pm', 'Camille', '--sortir', '["livraison"]')
        self.assertEqual(code, 2)
        self.assertIn('aucun cas évident ne répond à « livraison »', out)
        self.assertEqual(self.lire(), avant)
        code, out = self.run_cli('valider', self.plan_chemin, '--pm', 'Camille',
                                 '--changer', '[{"quoi": "remise", "choix": "Garder tel quel"}]')
        self.assertEqual(code, 0)
        c = {c['sujet']: c for c in registre.lire(self.lire())['cas']}
        self.assertEqual(c['Plafond de remise relevé']['tranche']['choix'], 'simple discussion')

    def test_taken_out_stays_out_on_another_plan(self):
        self.plan_ecrit()
        self.run_cli('valider', self.plan_chemin, '--pm', 'Camille', '--sortir', '["plafond de remise"]')
        autre = conflits.plan_vide(self.studio)      # the session reads the register alone next time
        self.assertEqual(conflits.evidents(autre)['liste'], [])
        self.assertIn('Plafond de remise relevé', [f['question'].splitlines()[0] for f in conflits.formulaires(autre)])

    def test_one_by_one_takes_them_all_out(self):
        self.plan_ecrit()
        code, out = self.run_cli('valider', self.plan_chemin, '--pm', 'Camille', '--tous-sortir')
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(self.run_cli('formulaires', self.plan_chemin)[1])['formulaires']), 2)


class FileDAttente(Base):
    def test_optional_fields_roundtrip_and_defaults(self):
        file = {'niveau': 'evident', 'recommande': 'remplacer', 'pourquoi': 'écrit et récent', 'contexte': 'Le mail du 3.',
                'raisons': [], 'ajoute_par': 'ingestion auto'}
        lignes = registre.bloc_du_cas('C1', 'Remise', {'texte': 'a', 'source': 'x.md', 'date': '01/10/2026'},
                                      {'texte': 'b', 'source': 'y.md', 'date': '02/10/2026'}, False, '2026-11-10', file=file)
        self.assertEqual(lignes[-1], '- **État** : ouvert')
        self.assertLess(lignes.index('- **Options** : ' + registre.OPTIONS), lignes.index('- **Niveau** : évident'))
        c = registre.lire('\n'.join(lignes))['cas'][0]
        self.assertEqual(c['file'], file)
        sans = registre.lire(registre_texte(dict(n=1, sujet='A', detecte='10/11/2026', extra='', etat='ouvert')))['cas'][0]
        self.assertEqual((sans['file']['niveau'], sans['file']['recommande']), ('arbitrage', None))
        raison = registre.lire(registre_texte(dict(n=1, sujet='A', detecte='10/11/2026', etat='ouvert',
                                                   extra='- **Niveau** : évident\n- **Raisons** : argent ou contrat\n')))
        self.assertEqual(raison['cas'][0]['file']['niveau'], 'arbitrage')

    def test_a_case_of_the_ingestion_keeps_its_recommendation(self):
        (self.studio / 'projet' / 'conflits.md').write_text(registre_texte(
            dict(n=1, sujet='Remise relevée', detecte='10/11/2026', etat='ouvert',
                 extra='- **Niveau** : évident\n- **Recommandé** : simple discussion\n- **Pourquoi** : rien ne change\n'),
            dict(n=2, sujet='Jour du comité', detecte='10/11/2026', etat='ouvert',
                 extra='- **Niveau** : évident\n')), encoding='utf-8')
        plan = conflits.plan_vide(self.studio)
        r = conflits.evidents(plan)
        self.assertEqual(r['liste'], [{'titre': 'Remise relevée', 'reponse': conflits.LIBELLE_GARDER}])
        self.assertEqual([f['question'].splitlines()[0] for f in conflits.formulaires(plan)], ['Jour du comité'])

    def test_unknown_date_of_the_file_is_the_same_case(self):
        chemin = self.studio / 'projet' / 'conflits.md'
        a = {'texte': 'x (date inconnue, celle du fichier)', 'source': 'projet/a.md', 'date': '01/11/2026'}
        n = {'texte': 'y', 'source': 'sources/b.md', 'date': '02/11/2026'}
        c1 = registre.ajouter(chemin, 'S', a, n, False, par_sources=True)
        c2 = registre.ajouter(chemin, 'S', dict(a, date='05/11/2026'), n, False, par_sources=True)
        self.assertEqual(c1, c2)
        c3 = registre.ajouter(chemin, 'S', dict(a, texte='x', date='05/11/2026'), n, False, par_sources=True)
        self.assertNotEqual(c1, c3)

    def test_a_title_that_carries_a_code_brings_none_back(self):
        self.assertEqual(registre.sans_codes('décision prise (PRJ-74)', {'PRJ-74': 'Remplacer le logiciel (PRJ-75)'}),
                         'décision prise (Remplacer le logiciel)')

    def test_two_undated_conflicts_between_the_same_files_are_two_cases(self):
        chemin = self.studio / 'projet' / 'conflits.md'
        a = {'texte': 'x (date inconnue, celle du fichier)', 'source': 'projet/a.md', 'date': '01/11/2026'}
        n = {'texte': 'y (date inconnue, celle du fichier)', 'source': 'projet/b.md', 'date': '02/11/2026'}
        c1 = registre.ajouter(chemin, 'Remise', a, n, False, par_sources=True)
        c2 = registre.ajouter(chemin, 'Hébergement', dict(a, texte='z (date inconnue, celle du fichier)'), n, False,
                              par_sources=True)
        self.assertNotEqual(c1, c2)

    def test_the_pm_as_a_person_is_not_a_code(self):
        self.assertEqual(registre.codes_pour_le_pm('Le 4 novembre, le PM a tranché ; Eric en informe du PM au PM.'), [])
        self.assertEqual(registre.codes_pour_le_pm('Au PM de voir. Du PM vient la réponse.'), [])
        self.assertEqual(registre.codes_pour_le_pm('classe PM'), ['PM'])


class Passe(Base):
    def test_nothing_new_nothing_to_judge(self):
        self.plan_ecrit()
        code, out = self.run_cli('passe', self.studio)
        self.assertEqual(code, 0)
        self.assertIn('Rien de nouveau', out)

    def test_pass_registers_and_keeps_markings_for_the_go(self):
        avant = F.snapshot(self.studio)
        code, out = self.run_cli('passe', self.studio, '--estimer')
        self.assertIn('Passe du lundi, dans le point du matin', out)
        self.assertNotIn('Haiku', out)
        self.assertEqual(F.snapshot(self.studio), avant)
        code, out = self.run_cli('passe', self.studio)
        self.assertEqual(code, 2)                  # never a whole-Studio read every week
        self.assertIn('Pas encore de passage complet', out)
        self.assertFalse((self.studio / 'projet' / '.conflits').exists())
        registre.poser_dernier_passage(self.studio / 'projet' / 'conflits.md', '2026-01-01')
        chemin = self.studio / 'projet' / '.conflits' / 'passe-2026-11-10.json'
        chemin.parent.mkdir(parents=True)
        ancien = chemin.with_name('passe-2026-11-10.jugements-1.json')
        ancien.write_text('[]', encoding='utf-8')
        code, out = self.run_cli('passe', self.studio)
        self.assertFalse(ancien.exists())          # an earlier run's judgments are set aside, not reused
        self.assertTrue(pathlib.Path(str(ancien) + '.ancien').exists())
        self.assertTrue(chemin.exists(), out)
        (chemin.with_name('passe-2026-11-10.jugements-1.json')).write_text(json.dumps(JUGEMENTS), encoding='utf-8')
        roadmap = (self.studio / '2-cadrage' / 'roadmap.md').read_text(encoding='utf-8')
        code, out = self.run_cli('cloturer', chemin)
        self.assertEqual(code, 0, out)
        self.assertIn('2 décisions au registre (1 évidentes, 1 à trancher une par une)', out)
        self.assertEqual((self.studio / '2-cadrage' / 'roadmap.md').read_text(encoding='utf-8'), roadmap)
        texte = (self.studio / 'projet' / 'conflits.md').read_text(encoding='utf-8')
        self.assertIn('Dernier passage : 10/11/2026', texte)   # every subject judged
        self.assertIn('- **Ajouté par** : passe hebdomadaire', texte)
        code, out = self.run_cli('attente', self.studio)
        self.assertIn('marquages sûrs', out)
        self.assertIn("Cas évidents à valider d'un coup : 1. Vraies décisions, une par une : 1.", out)
        code, out = self.run_cli('ecrire', chemin, '--pm', 'Camille')
        self.assertIn('marquages posés', out)
        self.assertNotIn('attendent ton go', self.run_cli('attente', self.studio)[1])
        self.assertNotEqual((self.studio / '2-cadrage' / 'roadmap.md').read_text(encoding='utf-8'), roadmap)

    def test_last_pass_never_goes_back(self):
        chemin = self.studio / 'projet' / 'conflits.md'
        registre.poser_dernier_passage(chemin, '2026-11-20')
        plan = conflits.releve(self.studio)
        conflits.juger(plan, JUGEMENTS)
        conflits.ecrire(plan, 'Camille')
        self.assertEqual(registre.lire_fichier(chemin)['dernier_passage'], '20/11/2026')


class Relance(Base):
    def test_thresholds_and_days_without_treatment(self):
        t = registre_texte(dict(n=1, sujet='A', detecte='01/11/2026', extra='', etat='tranché le 03/11/2026 par Camille : remplacer'),
                           dict(n=2, sujet='B', detecte='05/11/2026', extra='', etat='ouvert'))
        x = registre.etat_du_registre(t, 0, None, dt.date(2026, 11, 18))
        self.assertEqual((x['ouverts'], x['jours'], x['relance']), (1, 13, False))
        x = registre.etat_du_registre(t, 0, None, dt.date(2026, 11, 19))
        self.assertEqual((x['jours'], x['relance'], x['raison']), (14, True, 'rien de traité depuis 14 jours'))
        x = registre.etat_du_registre(t, 0, {'relance_cas': 1}, dt.date(2026, 11, 6))
        self.assertEqual(x['raison'], '1 conflit à traiter')
        # Everything answered on the 20th, a new case on the 25th: the days count from the 25th.
        t2 = registre_texte(dict(n=1, sujet='A', detecte='01/11/2026', extra='', etat='tranché le 20/11/2026 par Camille : remplacer'),
                            dict(n=2, sujet='B', detecte='25/11/2026', extra='', etat='ouvert'))
        self.assertEqual(registre.etat_du_registre(t2, 0, None, dt.date(2026, 11, 27))['jours'], 2)
        self.assertFalse(registre.etat_du_registre('', 0, None)['relance'])

    def test_nothing_written_outside_a_studio(self):
        with tempfile.TemporaryDirectory() as ailleurs:
            for cmd in (('ouverts', ailleurs), ('attente', ailleurs), ('regler', ailleurs, '--cas', '5')):
                self.assertEqual(self.run_cli(*cmd)[0], 2)
            self.assertEqual(os.listdir(ailleurs), [])

    def test_regler_and_seen(self):
        code, out = self.run_cli('regler', self.studio, '--cas', '5', '--jours', '7')
        self.assertIn('à partir de 5 conflits non traités ou de 7 jours', out)
        self.assertEqual(registre.lire_reglages(self.studio), {'relance_cas': 5, 'relance_jours': 7})
        self.assertEqual(self.run_cli('regler', self.studio, '--cas', '0')[0], 2)
        self.plan_ecrit()
        self.assertEqual(registre.lire_vu(self.studio), 0)
        self.run_cli('ouverts', self.studio)
        self.assertEqual(registre.lire_vu(self.studio), 2)

    def test_mon_studio_dot_reminder_and_global(self):
        # Detected two days ago, so the 14-day reminder never fires by the calendar alone.
        recent = (dt.date.today() - dt.timedelta(days=2)).strftime('%d/%m/%Y')
        (self.studio / 'projet' / 'conflits.md').write_text(registre_texte(
            *[dict(n=k, sujet=f'Cas {k}', detecte=recent, extra='', etat='ouvert') for k in range(1, 4)]), encoding='utf-8')
        d = str(self.studio)
        c = projets.conflits_du_projet(d, [], instantane={})
        self.assertEqual((c['nouveaux'], c['relance']), (3, False))
        conflits.regler(self.studio, cas=3)
        conflits.noter_vu(self.studio)
        c = projets.conflits_du_projet(d, [], instantane={})
        self.assertEqual((c['nouveaux'], c['relance'], c['raison']), (0, True, '3 conflits à traiter'))
        metas = [{'id': 'local_c1', 'cwd': d, 'titre': 'Projet Alpha · Conflits Studio', 'activite': 5}]
        l = projets.ligne_relance_conflits(d, metas, 1_800_000_000, instantane={})
        self.assertEqual((l['type'], l['session'], l['repli']), ('conflits', 'local_c1', False))
        self.assertEqual(l['titre'], 'Conflits du Studio : 3 conflits à traiter')
        self.assertEqual(registre.codes_pour_le_pm(l['titre'] + l['detail']), [])
        g = projets.conflits_global([{'nom': 'Projet Alpha', 'dossier': d, 'role': 'pm'},
                                     {'nom': 'Autre', 'dossier': d, 'role': 'membre'}], metas, instantane={})
        self.assertEqual([(x['nom'], x['ouverts'], x['relance']) for x in g], [('Projet Alpha', 3, True)])


class Rattacher(unittest.TestCase):
    def test_question_goes_to_the_conflicts_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp) / 'a' / 'b'
            base.mkdir(parents=True)
            studio = str(pathlib.Path(tmp) / 'Studio - Projet Alpha')
            for sid, titre, archive in (('local_x1', 'Projet Alpha · Conflits Studio (rattrapage)', False),
                                        ('local_x2', 'Projet Alpha · Compte rendu', False),
                                        ('local_x3', 'Projet Alpha · Conflits Studio', True)):
                (base / f'{sid}.json').write_text(json.dumps({'sessionId': sid, 'title': titre, 'cwd': studio,
                                                              'isArchived': archive}), encoding='utf-8')
            with unittest.mock.patch.object(question, 'APP_SESSIONS', pathlib.Path(tmp)):
                self.assertEqual(question.conflicts_session(studio),
                                 {'id': 'local_x1', 'title': 'Projet Alpha · Conflits Studio (rattrapage)'})
                self.assertIsNone(question.conflicts_session(str(pathlib.Path(tmp) / 'Studio - Projet Beta')))

    def test_option_is_parsed(self):
        src = (ROOT / 'skills' / 'mon-studio' / 'scripts' / 'question.py').read_text(encoding='utf-8')
        self.assertIn("'--rattacher', choices=('conflits', 'aucune')", src)


class Page(unittest.TestCase):
    def test_global_tab_dot_and_reminder_type(self):
        html = PAGE.read_text(encoding='utf-8')
        self.assertIn('id="onglet-conflits" data-onglet="conflits"', html)
        self.assertIn('function rendreConflitsGlobal', html)
        self.assertIn('conflits: "conflits à trancher"', html)
        self.assertIn('l.type !== "conflits"', html)   # no « Fait » on the reminder: it closes by itself
        for interdit in ('slack', 'mailto:'):
            self.assertNotIn(interdit, html[html.index('function rendreConflitsGlobal'):html.index('function choisirOnglet')].lower())


if __name__ == '__main__':
    unittest.main()
