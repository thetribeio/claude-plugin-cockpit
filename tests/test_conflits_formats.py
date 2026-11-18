"""The relevé on the formats of real Studios (tests/_studio_conflits.py, invented content):
python3 -m unittest discover -s tests

Entries under `##` with an em dash, a status in back ticks, a replacement or an update written in a bullet (also on an
entry still active), one-line rule bullets in a sub-folder store, a struck or ticked question, a value still waiting
for a decision, a read-only story map JSON; and what a catch-up already marked, by hand or by this script, is never
proposed again."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import tempfile
import unittest

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('conflits_formats', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)


class Entrees(unittest.TestCase):
    def test_level_two_em_dash_back_ticks_and_bullets(self):
        es = {e['code']: e for e in conflits.entrees(F.DECISIONS_REELLES, 'projet/decisions-log.md')}
        self.assertEqual(sorted(es), ['PRJ-1', 'PRJ-2', 'PRJ-7', 'PRJ-9'])
        self.assertEqual(es['PRJ-1']['libelle'], 'Hébergement chez le client')
        self.assertEqual(es['PRJ-1']['etat'], 'remplace')
        self.assertEqual(es['PRJ-2']['etat'], 'actif')
        self.assertEqual(es['PRJ-2']['majs'][0]['date'], '2026-11-04')
        self.assertIn('PRJ-8', es['PRJ-2']['majs'][0]['codes'])
        self.assertEqual(es['PRJ-1']['texte'], 'la plateforme est hébergée sur un serveur autonome chez le client.')

    def test_one_line_rules_and_their_superseded_mark(self):
        es = {e['code']: e for e in conflits.entrees(F.REGLES_PUCES, 'projet/produit-b/regles-metier.md')}
        self.assertEqual(es['PRJ-40']['etat'], 'remplace')
        self.assertEqual(es['PRJ-41']['etat'], 'actif')

    def test_struck_and_ticked_questions_are_closed(self):
        es = {e['code']: e for e in conflits.entrees(F.QUESTIONS_REELLES, 'projet/questions-ouvertes.md')}
        self.assertEqual(es['PRJ-60']['etat'], 'clos')
        self.assertEqual(es['PRJ-60']['libelle'], 'Quel hébergeur retenir ? — Résolue (2026-11-04)')
        self.assertEqual(es['PRJ-61']['etat'], 'actif')

    def test_stores_in_sub_folders(self):
        with tempfile.TemporaryDirectory() as d:
            s = F.make_reel(pathlib.Path(d) / 'Studio')
            m = conflits.magasins_du_studio(s)
            self.assertIn('projet/produit-b/regles-metier.md', m['regles'])
            self.assertEqual(m['decisions'], ['projet/decisions-log.md'])


class Releve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = F.make_reel(pathlib.Path(self.tmp.name) / 'Studio - Projet B')
        self.plan = conflits.releve(self.studio)
        self.vus = {(x['fichier'], x['passage']) for s in self.plan['sujets'] for x in s['extraits']}

    def passages(self, rel):
        return {p for f, p in self.vus if f == rel}

    def test_replaced_entry_found_by_its_code_and_its_old_words(self):
        self.assertIn('- Hébergement : serveur autonome chez le client (PRJ-1).', self.passages('projet/technique/stack.md'))

    def test_an_update_on_an_active_entry_is_a_candidate(self):
        self.assertIn('- Applications : Android et iOS natives pour les opérateurs.', self.passages('projet/technique/stack.md'))

    def test_a_value_still_waiting_is_paired_with_the_decision_that_settled_it(self):
        self.assertIn("- Postes : jusqu'à Windows XP. Version minimale à fixer par l'équipe technique.",
                      self.passages('projet/technique/stack.md'))
        s = next(s for s in self.plan['sujets'] if s['genre'] == 'attente')
        self.assertEqual(s['nouveau']['code'], 'PRJ-9')

    def test_a_one_line_rule_replaced_in_a_sub_folder_store(self):
        self.assertTrue(any('PRJ-40' in p for p in self.passages('2-cadrage/produit-b/story-mapping.md')))

    def test_a_json_story_map_is_read_only(self):
        x = next(x for s in self.plan['sujets'] for x in s['extraits'] if x['fichier'] == '2-cadrage/story-mapping.json')
        self.assertTrue(x['lecture_seule'])

    def test_work_folders_and_marked_passages_are_not_proposed(self):
        fichiers = {f for f, _ in self.vus}
        self.assertNotIn('projet/pilotage/journal-kit.md', fichiers)
        self.assertNotIn('projet/rattrapage-2026-11-10/apercu.md', fichiers)
        self.assertFalse(any('Rattrapage du' in p for p in self.passages('projet/technique/stack.md')))

    def test_hand_markings_are_recognised(self):
        for ligne in ('| Hébergeur | Serveur ⚠️ Remplacé le 2026-11-04 par PRJ-7, source `x.md`. Rattrapage du 2026-11-10. |',
                      '- Valeur ancienne *Remplacé le 2026-10-30 par « Coinz » — rattrapage du 2026-11-09*',
                      'Texte. ⚠️ Non retenu le 2026-11-09 par l\'équipe, source PRJ-60. Rattrapage du 2026-11-10.'):
            self.assertTrue(conflits.deja_marque([ligne], 0), ligne)
        self.assertTrue(conflits.deja_marque(['- Ancien texte', '  ⚠️ Remplacé le 20/10/2026 par X, source y — rattrapage du 10/11/2026'], 0))
        self.assertFalse(conflits.deja_marque(['- Ancien texte', '- Autre texte'], 0))

    def test_no_bare_code_in_the_batches(self):
        for k in range(1, self.plan['cout']['lots'] + 1):
            self.assertEqual(conflits.codes_nus(conflits.texte_lot(self.plan, k).replace('PRJ-8', 'PRJ-8 · x')), [])

    def test_one_folder_at_a_time_never_a_source_folder(self):
        self.assertEqual(conflits.documents_vivants(self.studio, 'sources'), [])
        self.assertNotIn('sources', conflits.dossiers_de_premier_niveau(self.studio))


if __name__ == '__main__':
    unittest.main()
