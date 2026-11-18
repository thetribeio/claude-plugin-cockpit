"""Tests of the Monday pass of the conflicts, inside the morning point (PM, Q18, 2026-11-15):
python3 -m unittest discover -s tests

No scheduled task per Studio. The first morning point of the week opens the pass of every Studio the person leads,
checked once (« Dernier passage ») and without an active automatic ingestion; `matin.py preparer` hands the subjects and
the judging instructions to the task, which gives its judgments to the connector's tool `conflits_juger`: the decisions
go to the register, nothing is marked in the documents. The prepared preview became a gesture from the board
(« Préparer l'aperçu », `/cockpit:conflits préparer`). Synthetic data, temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
ASSETS = ROOT / 'skills' / 'mon-studio' / 'assets'
SKILL_CONFLITS = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')
LUNDI = dt.datetime(2026, 11, 16, 7, 31).timestamp()
JUGEMENTS = [
    {'sujet': 'S1', 'classe': 'M', 'titre': 'Comité de pilotage le jeudi', 'passages': ['E1.1', 'E1.2']},
    {'sujet': 'S2', 'classe': 'PM', 'titre': 'Plafond de remise relevé', 'passages': ['E2.2'],
     'contexte': "Les règles de septembre limitaient la remise à 10 % ; au point du 3 novembre, l'équipe l'a portée à 15 %.",
     'recommande': 'remplacer', 'pourquoi': 'La nouvelle règle est écrite et plus récente.'},
]


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
        env = mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-16', 'MON_STUDIO': str(self.mon_studio)})
        env.start()
        self.addCleanup(env.stop)
        self.conflits = charger('conflits_lundi', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
        self.registre = self.conflits.registre
        self.m = charger('matin_lundi', SCRIPTS / 'matin.py')
        self.m.parc.SORTIE, self.m.parc.INTERNE = self.mon_studio, self.mon_studio / '.parc'
        self.studios = [{'nom': 'Projet Alpha', 'dossier': str(self.studio), 'role': 'pm'}]
        (self.mon_studio / 'projets.json').write_text(json.dumps({'studios': self.studios}), encoding='utf-8')

    def verifie_une_fois(self):
        self.registre.poser_dernier_passage(self.studio / 'projet' / 'conflits.md', '2026-01-01')


class Semaine(Base):
    def test_a_checked_studio_gets_its_pass_once_a_week(self):
        self.verifie_une_fois()
        avant = F.snapshot(self.studio)
        passes = self.m.passes_de_la_semaine(self.studios, LUNDI)
        self.assertEqual(len(passes), 1)
        x = passes[0]
        self.assertEqual(x['studio'], 'Projet Alpha')
        self.assertTrue(x['plan'].endswith('projet/.conflits/passe-2026-11-16.json'))
        self.assertIn('Lot 1', x['texte'])
        self.assertGreater(x['sujets'], 0)
        # Nothing written in the documents: only the plan next to the register.
        apres = F.snapshot(self.studio)
        self.assertEqual({k: v for k, v in apres.items() if '.conflits' not in k}, avant)
        # Tuesday, the same week: nothing again.
        self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI + 86400), [])
        # Next Monday: again.
        self.assertEqual(len(self.m.passes_de_la_semaine(self.studios, LUNDI + 7 * 86400)), 1)

    def test_never_checked_member_or_ingested_studios_are_left_out(self):
        self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI), [])   # no « Dernier passage »
        self.verifie_une_fois()
        membre = [dict(self.studios[0], role='membre')]
        self.assertEqual(self.m.passes_de_la_semaine(membre, LUNDI + 7 * 86400), [])
        etat = {'nouvelles': [{'ts': dt.datetime.fromtimestamp(LUNDI + 13 * 86400).isoformat(), 'texte': ''}]}
        (self.studio / 'projet' / '.ingestion-auto-state.json').write_text(json.dumps(etat), encoding='utf-8')
        self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI + 14 * 86400), [])
        # An ingestion silent for more than 8 days no longer counts.
        self.assertEqual(len(self.m.passes_de_la_semaine(self.studios, LUNDI + 28 * 86400)), 1)

    def test_a_week_too_heavy_waits_for_the_next_monday(self):
        self.verifie_une_fois()
        c = self.m._charger_conflits()
        c.PASSE_MATIN_CARACTERES = 100
        with mock.patch.object(self.m, '_charger_conflits', return_value=c):
            self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI), [])
        self.assertFalse((self.studio / 'projet' / '.conflits').exists())   # no plan kept

    def test_preparer_hands_the_subjects_and_the_instructions(self):
        self.verifie_une_fois()
        r = self.m.preparer(LUNDI)
        self.assertEqual(len(r['conflits']), 1)
        self.assertIn('`M` (marquage sûr)', r['conflits_consigne'])
        self.assertEqual(self.m.preparer(LUNDI + 86400).get('conflits'), None)   # once a week
        self.assertNotIn('conflits_consigne', self.m.preparer(LUNDI + 86400))

    def test_a_failure_never_stops_the_morning_point(self):
        self.verifie_une_fois()
        with mock.patch.object(self.m, '_charger_conflits', side_effect=FileNotFoundError('conflits.py')):
            r = self.m.preparer(LUNDI)
        self.assertNotIn('conflits', r)
        self.assertIn('studios', r)


class Connecteur(Base):
    def setUp(self):
        super().setUp()
        self.mcp = charger('mcp_lundi', SCRIPTS / 'mcp_mon_studio.py')
        self.verifie_une_fois()
        self.plan = self.m.passes_de_la_semaine(self.studios, LUNDI)[0]['plan']

    def test_the_judgments_go_to_the_register_and_nothing_is_marked(self):
        roadmap = (self.studio / '2-cadrage' / 'roadmap.md').read_text(encoding='utf-8')
        r = self.mcp.conflits_juger({'plan': self.plan, 'jugements': JUGEMENTS})
        self.assertTrue(r['inscrit'])
        self.assertIn('décisions au registre', r['compte_rendu'])
        self.assertEqual((self.studio / '2-cadrage' / 'roadmap.md').read_text(encoding='utf-8'), roadmap)
        texte = (self.studio / 'projet' / 'conflits.md').read_text(encoding='utf-8')
        self.assertIn('- **Ajouté par** : passe hebdomadaire', texte)
        self.assertTrue(pathlib.Path(self.plan).with_name('passe-2026-11-16.jugements-matin.json').exists())
        with self.assertRaisesRegex(ValueError, 'déjà jugée'):
            self.mcp.conflits_juger({'plan': self.plan, 'jugements': JUGEMENTS})
        out = self.conflits.attente(str(self.studio))
        self.assertTrue(out['marquages_en_attente'])               # the safe markings wait for the PM's go

    def test_only_a_pass_plan_of_a_known_studio(self):
        autre = pathlib.Path(self.plan).with_name('apercu-2026-11-16.json')
        autre.write_text(pathlib.Path(self.plan).read_text(encoding='utf-8'), encoding='utf-8')
        for chemin in (str(autre), str(self.studio / 'projet' / 'conflits.md'), '/etc/passwd'):
            with self.assertRaisesRegex(ValueError, 'Refusé'):
                self.mcp.conflits_juger({'plan': chemin, 'jugements': []})
        (self.mon_studio / 'projets.json').write_text(json.dumps({'studios': []}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Refusé'):
            self.mcp.conflits_juger({'plan': self.plan, 'jugements': JUGEMENTS})
        with self.assertRaises(ValueError):
            self.mcp.conflits_juger({'plan': self.plan})

    def test_the_tool_is_declared_and_allowed_like_matin_ecrire(self):
        noms = [o['name'] for o in self.mcp.OUTILS]
        self.assertIn('conflits_juger', noms)
        install = charger('install_lundi', SCRIPTS / 'install.py')
        self.assertIn('mcp__mon-studio__conflits_juger', install.SCRIPT_RULES)
        consigne = (ASSETS / 'consigne-point-du-matin.md').read_text(encoding='utf-8')
        self.assertIn("`conflits_juger` du connecteur mon-studio", consigne)
        self.assertIn("suis `conflits_consigne`", consigne)
        self.assertIn("`conflits_juger` du connecteur mon-studio", self.m.CONSIGNE_CONFLITS)


class SansTache(unittest.TestCase):
    def test_the_skill_creates_no_scheduled_task(self):
        self.assertNotIn('create_scheduled_task', SKILL_CONFLITS)
        self.assertNotIn('Conflits, passe hebdo', SKILL_CONFLITS)
        self.assertNotIn("Conflits, aperçu préparé", SKILL_CONFLITS)
        self.assertIn('Aucune tâche planifiée par Studio', SKILL_CONFLITS)
        self.assertIn('/cockpit:conflits préparer', SKILL_CONFLITS)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertNotIn('jamais planifiée', readme)
        self.assertIn('aucune tâche planifiée par Studio', readme)

    def test_the_judging_instructions_follow_the_skill_brief(self):
        c = charger('conflits_brief', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
        brief = SKILL_CONFLITS[SKILL_CONFLITS.index('## Brief d\'un sous-agent'):SKILL_CONFLITS.index('## Règle de lecture commune')]
        for ligne in brief.splitlines():
            ligne = ligne.lstrip('> ').strip()
            if ligne.startswith(('- `M`', '- `PM`', '- `absence`', '- `rien`', '« Rien » est strict', 'Genres particuliers',
                                 'Une décision tirée')):
                self.assertIn(ligne, c.CONSIGNE_JUGEMENT)
        for regle in ('La dernière source datée fait foi', 'Donnée figée', 'Action déjà faite'):
            self.assertIn(regle, c.CONSIGNE_JUGEMENT)

    def test_the_prepare_gesture_from_the_board(self):
        page = (ASSETS / 'page-servie.html').read_text(encoding='utf-8')
        self.assertIn('data-copier="/cockpit:conflits préparer"', page)
        self.assertIn("Préparer l\\'aperçu ↗", page)
        mcp = charger('mcp_lundi_motif', SCRIPTS / 'mcp_mon_studio.py')
        self.assertTrue(re.fullmatch(mcp.COPIE_MOTIF, '/cockpit:conflits préparer'))
        self.assertFalse(re.fullmatch(mcp.COPIE_MOTIF, '/cockpit:conflits préparer; rm -rf'))


class AnciennesTaches(unittest.TestCase):
    def test_former_conflicts_tasks_are_found_and_named_by_disable(self):
        with tempfile.TemporaryDirectory() as d:
            home = pathlib.Path(d)
            with mock.patch.dict(os.environ, {'HOME': str(home)}):
                os.environ.pop('MON_STUDIO', None)
                i = charger('install_anciennes', SCRIPTS / 'install.py')
            for nom, texte in (('alpha-conflits-passe-hebdo', 'Passe hebdomadaire des conflits du Studio « Alpha ».'),
                               ('alpha-apercu', "Préparation de l'aperçu des conflits du Studio « Alpha »."),
                               ('autre', 'Autre chose.')):
                p = home / '.claude' / 'scheduled-tasks' / nom / 'SKILL.md'
                p.parent.mkdir(parents=True)
                p.write_text(f'---\nname: {nom}\ndescription: x\n---\n\n{texte}\n', encoding='utf-8')
            self.assertEqual(i.former_conflicts_tasks(), ['alpha-apercu', 'alpha-conflits-passe-hebdo'])


if __name__ == '__main__':
    unittest.main()
