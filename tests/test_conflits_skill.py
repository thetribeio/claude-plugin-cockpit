"""Tests of the /cockpit:conflits skill text (skills/conflits/SKILL.md): python3 -m unittest discover -s tests

What the PM decided on 2026-11-10 must be in the instructions the session follows: typed by the PM only, one session
in the Studio titled « <Projet> · Conflits Studio », cost before each go, one form per decision with no tool call in
between, answers written every eight, the shared reading rule copied as it is, nothing removed nor sent."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')
spec = importlib.util.spec_from_file_location('conflits_cli', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)

# The shared reading rule, as the method writes it: copied word for word in every tool that reads a Studio.
REGLE = [
    "But : qu'aucun outil ne présente comme vraie une donnée qu'une source plus récente du Studio a changée.",
    "## Règle 1 · La dernière source datée fait foi",
    "Sur un sujet, la dernière source datée fait foi. Un document vivant qui la contredit est en retard, et non incomplet.",
    "Un document signé ne cède qu'à une source écrite qui pèse au moins autant : document signé, puis échange écrit, puis oral.",
    "Une décision tirée d'un résumé automatique seul reste « à confirmer ».",
    "## Règle 2 · Donnée figée",
    "Avant d'annoncer une donnée figée (agenda, fiche, règle, horaire d'un rituel), la rapprocher des échanges récents du Studio.",
    "S'ils divergent, le dire et donner les deux valeurs avec leurs dates. Ne jamais trancher seul.",
    "## Règle 3 · Action déjà faite",
    "Avant d'annoncer une action « à faire », chercher la preuve qu'elle est faite : compte rendu coché, ticket, commit ou branche.",
    "Si elle l'est, dire « déjà fait le {date} » au lieu de la reporter.",
]


class Skill(unittest.TestCase):
    def test_typed_by_the_pm_only(self):
        self.assertIn('\ndisable-model-invocation: true\n', SKILL.split('---')[1] + '\n')

    def test_the_shared_reading_rule_is_copied_as_it_is(self):
        texte = SKILL.split('## Règle de lecture commune', 1)[1]
        for ligne in REGLE:
            self.assertIn(ligne + '\n', texte)
        positions = [texte.index(l) for l in REGLE]
        self.assertEqual(positions, sorted(positions))

    def test_one_session_in_the_studio(self):
        self.assertIn('« <Projet> · Conflits Studio »', SKILL)
        self.assertIn('`start_session`', SKILL)
        self.assertIn('`detach_session`', SKILL)
        self.assertIn('sans groupe', SKILL)

    def test_cost_before_each_go_and_one_grouped_go(self):
        self.assertIn('conflits.py estimer', SKILL)
        self.assertIn('0,5 %', SKILL)
        self.assertIn('Un seul go groupé', SKILL)

    def test_forms_one_by_one_without_tool_calls(self):
        self.assertIn('Un encadré AskUserQuestion par décision, posé seul', SKILL)
        self.assertIn('aucune lecture, aucune écriture, aucun appel d\'outil', SKILL)
        self.assertIn(f'Toutes les huit réponses', SKILL)
        self.assertEqual(conflits.ORDRE_ECRITURE, 8)
        self.assertIn('« Discuter d\'abord »', SKILL)

    def test_sub_agents_on_extracts_only(self):
        self.assertIn('Sonnet, effort medium', SKILL)
        self.assertIn('jamais un fichier entier', SKILL)
        self.assertEqual(conflits.LOT, 10)

    def test_every_command_named_exists(self):
        commandes = set(re.findall(r'conflits\.py (\w+)', SKILL))
        src = (ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py').read_text(encoding='utf-8')
        sous = set(re.findall(r"add_parser\('([\w-]+)'\)", src)) | {'estimer', 'releve'}
        self.assertGreaterEqual(sous, {'lot', 'juger', 'ecrire', 'formulaires', 'repondre', 'evidents', 'valider',
                                       'passe', 'cloturer', 'attente', 'regler'})
        self.assertTrue(commandes)
        self.assertLessEqual(commandes, sous)

    def test_keep_label_lives_in_one_constant(self):
        self.assertNotIn(conflits.LIBELLE_GARDER, SKILL)
        self.assertEqual(conflits.LIBELLES['simple discussion'], conflits.LIBELLE_GARDER)

    def test_no_code_before_the_pm(self):
        section = SKILL.split('## Les mots devant le PM', 1)[1].split('\n## ', 1)[0]
        self.assertIn('Aucun code devant le PM', section)
        self.assertIn('que si le PM les demande', section)
        # « le PM » is the person this text is about, not a class letter.
        self.assertEqual(conflits.registre.codes_pour_le_pm(section.replace('le PM', 'la personne')), [])
        self.assertIn('"contexte"', SKILL)
        self.assertIn('aucun code dedans', SKILL)
        self.assertNotIn('« C3 remplacer »', SKILL)
        self.assertIn('« le comité de pilotage, remplacer »', SKILL)

if __name__ == '__main__':
    unittest.main()
