"""/cockpit:conflits, recall and cost of the sub-agents (2026-11-10, after a real run: 44 % recall, batches of 170 KB):
documents under a banner left out, html pages read as text and their twins as one subject, closed questions as
archives, fewer extracts per subject, batches by size, the project's state (counts, phase), the stricter brief."""
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
SKILL = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')

ETAPE = """# Revue du cadrage

> ⚠️ **Document d'étape du 02/10/2026**, périmé sur : le comité de pilotage du premier mardi. Voir `2-cadrage/roadmap.md`.

Le comité de pilotage se tient le premier mardi du mois.
"""

ETAPE_HTML = """<!doctype html><html><head><title>Revue</title>
<style>
.comite { color: red; }
</style></head><body>
<h1>Revue du cadrage</h1>
<p class="comite">Le comité de pilotage se tient le <strong>premier mardi</strong> du mois.</p>
<script>var comite = "premier mardi du mois";</script>
</body></html>
"""

PAGE_HTML = """<html><body>
<h1>Gouvernance</h1>
<p>Le comit&eacute; de pilotage se tient le <b>premier mardi</b> du mois, en visio.</p>
</body></html>
"""

QUESTIONS = """# Questions ouvertes

## ~~PRJ-70~~ — Comité de pilotage : quel jour retenir ? — 🟢 Résolue (2026-10-20)

- **Contexte** : le comité de pilotage du premier mardi du mois gêne la comptabilité.

## PRJ-71 — Accès hors ligne : solution technique non tranchée

- **Contexte** : à voir avec l'équipe technique.

## PRJ-72 — Format des exports ?

- **Contexte** : tableur ou texte.
"""

STATUS = """# Statut

| Rubrique | État | Détail |
|---|---|---|
| Questions ouvertes | 🟡 | 3 questions : 3 ouvertes, 0 closes |
| Décisions | 🟢 | 2 décisions ; 5 remplacées |
| Story map | 🟢 | 2 thèmes, 9 fonctionnalités dans la story map |
| Fiche projet | 🟢 | **Phase** : Phase 2, Cadrage |

## Historique

- 2026-10-01 : 4 questions ouvertes, 1 close ; 3 décisions remplacées.
- 2026-11-09 : passage en Phase 3, développement.
"""

CARTE = json.dumps({'themes': [{'id': 't1'}, {'id': 't2'}], 'epics': [{'id': 'e1'}],
                    'fonctionnalites': [{'id': f'f{k}'} for k in range(8)]})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = F.make(pathlib.Path(self.tmp.name) / 'Studio - Projet Alpha')
        env = unittest.mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-10'})
        env.start()
        self.addCleanup(env.stop)

    def poser(self, fichiers):
        for rel, texte in fichiers.items():
            p = self.studio / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(texte, encoding='utf-8')

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = conflits.main([str(a) for a in args])
        return code, out.getvalue()

    def fichiers_des_extraits(self, plan):
        return {x['fichier'] for s in plan['sujets'] for x in s['extraits']}


class Bandeau(Base):
    def test_a_document_under_its_own_banner_is_left_out(self):
        self.poser({'2-cadrage/revue-cadrage-2026-09-25.md': ETAPE})
        plan = conflits.releve(self.studio)
        self.assertIn('2-cadrage/revue-cadrage-2026-09-25.md', plan['sous_bandeau'])
        self.assertNotIn('2-cadrage/revue-cadrage-2026-09-25.md', self.fichiers_des_extraits(plan))
        # The living documents with the same old value are still found.
        self.assertIn('2-cadrage/roadmap.md', self.fichiers_des_extraits(plan))

    def test_a_catch_up_marking_at_the_top_is_not_a_banner(self):
        texte = ('# Roadmap\n\n⚠️ Remplacé le 2026-11-09 par la décision du jeudi, source `projet/decisions-log.md`. '
                 'Rattrapage du 2026-11-10.\n\nLe comité de pilotage du premier mardi du mois valide chaque lot.\n')
        self.assertIsNone(conflits.bandeau(texte))
        self.assertIsNotNone(conflits.bandeau(ETAPE))

    def test_a_hand_marking_under_a_table_marks_the_rows_it_speaks_of(self):
        lignes = ['| Date | Jalon | Source |', '|---|---|---|',
                  '| 26 février | MEP lot 1 | Date butoir contractuelle (Annexe 5) ; roadmap présentée en macro |',
                  '| Été | Pilote ventilation | Atelier de septembre |', '',
                  "⚠️ Remplacé le 2026-11-09 par la décision des jalons (dates butoirs de l'Annexe 5 présentées), "
                  'source `projet/decisions-log.md`. Rattrapage du 2026-11-10.']
        self.assertTrue(conflits.deja_marque(lignes, 2))
        self.assertFalse(conflits.deja_marque(lignes, 3))

    def test_its_html_twin_without_banner_is_one_subject(self):
        self.poser({'2-cadrage/revue-cadrage-2026-09-25.md': ETAPE, '2-cadrage/revue-cadrage-2026-09-25.html': ETAPE_HTML})
        plan = conflits.releve(self.studio)
        jumeaux = [s for s in plan['sujets'] if s['genre'] == 'jumeau']
        self.assertEqual(len(jumeaux), 1)
        s = jumeaux[0]
        self.assertEqual(s['nouveau']['source'], '2-cadrage/revue-cadrage-2026-09-25.md')
        self.assertIn("Document d'étape", s['nouveau']['texte'])
        self.assertEqual([x['fichier'] for x in s['extraits']], ['2-cadrage/revue-cadrage-2026-09-25.html'])
        # The twin is not searched value by value: no other subject quotes it.
        autres = {x['fichier'] for t in plan['sujets'] if t is not s for x in t['extraits']}
        self.assertNotIn('2-cadrage/revue-cadrage-2026-09-25.html', autres)
        # Never a safe marking: an html page is never written.
        j = conflits.valider_jugement(plan, {'sujet': s['id'], 'classe': 'M', 'titre': 'Page de revue sans bandeau',
                                             'passages': [s['extraits'][0]['id']]})
        self.assertEqual(j['classe'], 'PM')


class Html(Base):
    def test_a_page_is_read_as_text_without_tags_scripts_or_styles(self):
        lignes = conflits.texte_html(ETAPE_HTML.splitlines())
        self.assertEqual(len(lignes), len(ETAPE_HTML.splitlines()))
        texte = '\n'.join(lignes)
        self.assertNotIn('<', texte)
        self.assertNotIn('color', texte)
        self.assertNotIn('var comite', texte)
        self.assertIn('Le comité de pilotage se tient le premier mardi du mois.', texte)

    def test_html_extracts_are_text_short_and_few(self):
        self.poser({f'2-cadrage/page-{k}.html': PAGE_HTML for k in range(4)})
        plan = conflits.releve(self.studio)
        for s in plan['sujets']:
            html = [x for x in s['extraits'] if x['fichier'].endswith('.html')]
            self.assertLessEqual(len(html), conflits.EXTRAITS_HTML)
            for x in html:
                self.assertNotIn('<', x['contexte'])
                self.assertLessEqual(len(x['contexte']), conflits.CONTEXTE_HTML)
        self.assertTrue(any('comité de pilotage' in x['contexte'] for s in plan['sujets'] for x in s['extraits']
                            if x['fichier'].endswith('.html')))


class Questions(Base):
    def test_a_closed_question_is_an_archive_and_non_tranchee_stays_open(self):
        self.poser({'projet/questions-ouvertes.md': QUESTIONS})
        es = conflits.entrees(QUESTIONS, 'projet/questions-ouvertes.md')
        self.assertEqual([e['etat'] for e in es], ['clos', 'actif', 'actif'])
        plan = conflits.releve(self.studio)
        lignes = {(x['fichier'], x['ligne']) for s in plan['sujets'] for x in s['extraits']}
        self.assertNotIn(('projet/questions-ouvertes.md', 5), lignes)


class Plafonds(Base):
    def test_extracts_per_subject_and_per_file_are_capped(self):
        copies = {f'2-cadrage/copie-{k}.md': '# Copie\n\n' + '\n\n'.join(
            f'Point {n} : le comité de pilotage se tient le premier mardi du mois.' for n in range(5)) + '\n'
            for k in range(6)}
        self.poser(copies)
        plan = conflits.releve(self.studio)
        for s in plan['sujets']:
            self.assertLessEqual(len(s['extraits']), conflits.EXTRAITS_SUJET)
            par_fichier = {}
            for x in s['extraits']:
                par_fichier[x['fichier']] = par_fichier.get(x['fichier'], 0) + 1
            self.assertLessEqual(max(par_fichier.values()), conflits.EXTRAITS_PAR_FICHIER)
            for x in s['extraits']:
                self.assertLessEqual(len(x['contexte']), conflits.CONTEXTE_CARACTERES)


class Lots(Base):
    def test_batches_stop_by_size_and_hold_every_subject_once(self):
        plan = conflits.releve(self.studio)
        long = 'x' * 9000
        plan['sujets'] = [dict(plan['sujets'][0], id=f'S{k}', extraits=[dict(plan['sujets'][0]['extraits'][0],
                                                                            contexte=long, id=f'E{k}.1')])
                          for k in range(1, 23)]
        plan['lots'] = conflits.repartir(plan)
        self.assertEqual([i for lot in plan['lots'] for i in lot], [s['id'] for s in plan['sujets']])
        for k, lot in enumerate(plan['lots'], 1):
            self.assertLessEqual(len(lot), conflits.LOT)
            self.assertLessEqual(len(conflits.texte_lot(plan, k)), conflits.LOT_CARACTERES + 200)
        self.assertGreater(len(plan['lots']), 3)
        self.assertEqual(conflits.estimer_cout(plan)['lots'], len(plan['lots']))

    def test_a_plan_made_before_batches_by_size_is_cut_by_ten(self):
        plan = conflits.releve(self.studio)
        plan['sujets'] = [dict(plan['sujets'][0], id=f'S{k}') for k in range(1, 13)]
        del plan['lots']
        self.assertEqual([len(l) for l in conflits.lots_du_plan(plan)], [10, 2])
        self.assertIn('S12 ·', conflits.texte_lot(plan, 2))

    def test_lot_writes_its_text_to_a_file_read_once(self):
        chemin = pathlib.Path(self.tmp.name) / 'plan.json'
        self.run_cli('releve', self.studio, '--sortie', chemin)
        sortie = pathlib.Path(self.tmp.name) / 'lot-1.txt'
        code, out = self.run_cli('lot', chemin, 1, '--sortie', sortie)
        self.assertEqual(code, 0)
        self.assertIn('S1 ·', sortie.read_text(encoding='utf-8'))
        self.assertNotIn('S1 ·', out)
        self.assertIn('lis-le en une fois', out)
        self.assertIn('plan.jugements-1.json', out)


class Etat(Base):
    def setUp(self):
        super().setUp()
        self.poser({'projet/status.md': STATUS, 'projet/questions-ouvertes.md': QUESTIONS,
                    '2-cadrage/story-mapping.json': CARTE})
        self.plan = conflits.releve(self.studio)
        self.par_titre = {s['titre']: s for s in self.plan['sujets'] if s['genre'] in ('compteur', 'etat')}

    def lignes(self, titre):
        return [(x['fichier'], x['ligne']) for x in self.par_titre[titre]['extraits']]

    def test_counts_of_questions_and_replaced_decisions(self):
        q = self.par_titre['Nombre de questions ouvertes et closes']
        self.assertIn('2 questions ouvertes et 1 closes', q['nouveau']['texte'])
        self.assertEqual(self.lignes('Nombre de questions ouvertes et closes'), [('projet/status.md', 5)])
        d = self.par_titre['Nombre de décisions remplacées']
        self.assertIn('1 décisions remplacées', d['nouveau']['texte'])
        self.assertEqual(self.lignes('Nombre de décisions remplacées'), [('projet/status.md', 6)])

    def test_a_dated_history_line_is_never_a_stale_count(self):
        for s in self.par_titre.values():
            self.assertNotIn(('projet/status.md', 12), [(x['fichier'], x['ligne']) for x in s['extraits']])

    def test_story_map_size_from_its_json(self):
        s = self.par_titre['Taille de la story map']
        self.assertIn('8 fonctionnalités', s['nouveau']['texte'])
        self.assertEqual(s['nouveau']['source'], '2-cadrage/story-mapping.json')
        self.assertEqual(self.lignes('Taille de la story map'), [('projet/status.md', 7)])
        # Counted in the JSON: a safe marking may stand; a count of the stores is never one alone.
        x = s['extraits'][0]['id']
        self.assertEqual(conflits.valider_jugement(self.plan, {'sujet': s['id'], 'classe': 'M', 'titre': 'Taille de la story map',
                                                               'passages': [x]})['classe'], 'M')
        q = self.par_titre['Nombre de questions ouvertes et closes']
        self.assertEqual(conflits.valider_jugement(self.plan, {'sujet': q['id'], 'classe': 'M', 'titre': 'Nombre de questions',
                                                               'passages': [q['extraits'][0]['id']]})['classe'], 'PM')

    def test_the_phase_said_is_behind_the_latest_passage(self):
        s = self.par_titre['Phase du projet']
        self.assertTrue(s['nouveau']['texte'].startswith('Phase 3 depuis le 09/11/2026'))
        self.assertEqual(self.lignes('Phase du projet'), [('projet/status.md', 8)])

    def test_a_planned_phase_is_not_the_current_one(self):
        self.poser({'README.md': '# Projet\n\n- passage en Phase 4 prévu le 2027-01-15.\n'})
        plan = conflits.releve(self.studio)
        phase = [s for s in plan['sujets'] if s['genre'] == 'etat']
        self.assertEqual(len(phase), 1)
        self.assertIn('Phase 3', phase[0]['nouveau']['texte'])


class Relecture(Base):
    """What the independent review of 0.2.7 found."""

    def test_a_script_marking_of_one_row_does_not_hide_its_neighbour(self):
        lignes = ['| Date | Jalon |', '|---|---|', '| 12 mars | Livraison recette lot paiement |',
                  '| 30 mars | Livraison production lot paiement |', '',
                  '⚠️ Rangée « 12 mars » : Remplacé le 01/03/2026 par la livraison paiement, source `projet/x.md` '
                  '— rattrapage du 10/11/2026']
        self.assertFalse(conflits.deja_marque(lignes, 3))

    def test_a_banner_speaks_of_the_document_itself(self):
        self.assertIsNone(conflits.bandeau('# Doc\n\n> Voir aussi la page archivée de cadrage.\n\nTexte.\n'))
        self.assertIsNone(conflits.bandeau('# Journal\n\n> ⚠️ Les décisions remplacées restent ici, en archive.\n'))
        self.assertIsNotNone(conflits.bandeau('# Revue\n\n> ⚠️ Ce document est archivé depuis le 02/10.\n'))

    def test_a_question_code_is_not_a_count(self):
        self.poser({'projet/questions-ouvertes.md': QUESTIONS,
                    '2-cadrage/suivi.md': '# Suivi\n\nLa question Q-12 ouverte le 3 mars attend le client.\n'})
        plan = conflits.releve(self.studio)
        self.assertFalse([s for s in plan['sujets'] if s['genre'] == 'compteur'])

    def test_a_tag_or_comment_over_several_lines_leaves_no_markup(self):
        lignes = ['<div', '  class="carte" style="color: red">Le comité du jeudi</div>', '<!-- ancien :',
                  'Le comité du premier mardi', '-->', '<p>Fin</p>']
        sortie = conflits.texte_html(lignes)
        self.assertEqual(len(sortie), len(lignes))
        self.assertNotIn('class', ' '.join(sortie))
        self.assertNotIn('premier mardi', ' '.join(sortie))
        self.assertIn('Le comité du jeudi', sortie[1])

    def test_a_phase_line_is_never_a_safe_marking_alone(self):
        self.poser({'projet/status.md': STATUS})
        plan = conflits.releve(self.studio)
        s = next(s for s in plan['sujets'] if s['genre'] == 'etat')
        j = conflits.valider_jugement(plan, {'sujet': s['id'], 'classe': 'M', 'titre': 'Phase du projet',
                                             'passages': [s['extraits'][0]['id']]})
        self.assertEqual(j['classe'], 'PM')

    def test_a_broken_story_map_link_does_not_stop_the_releve(self):
        lien = self.studio / '2-cadrage' / 'story-mapping-vieux.json'
        os.symlink(self.studio / 'absent.json', lien)
        self.assertEqual(conflits.carte_du_studio(self.studio), (None, {}))
        conflits.releve(self.studio)


class Brief(unittest.TestCase):
    def test_the_brief_is_strict_on_nothing_and_cheap_to_run(self):
        self.assertIn('« Rien » est strict', SKILL)
        self.assertIn("n'est jamais « rien »", SKILL)
        self.assertIn('--sortie', SKILL)
        self.assertIn('en une seule lecture', SKILL)
        self.assertIn('sans script ni relecture', SKILL)
        self.assertIn('{"sujet": "S12", "classe": "rien"}', SKILL)
        self.assertNotIn('lis-le par morceaux', SKILL)


if __name__ == '__main__':
    unittest.main()
