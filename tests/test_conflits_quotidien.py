"""Tests of the daily conflicts pass (PM, Q16, 2026-11-23): python3 -m unittest discover -s tests

The re-read reads only the lines the last complete pass did not read (`projet/.conflits/lignes-lues.json`), never a
file's modification date, which the Drive rewrites for whole folders. Without that file, the dates written in the
Studio decide. The morning point opens the pass every day, on every Studio the person leads, automatic ingestion or
not; a pass with nothing new is complete and moves « Dernier passage ». The cases the PM set aside stay in the register
and leave the tab's journal. Synthetic data, temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
LUNDI = dt.datetime(2026, 11, 16, 7, 31).timestamp()
CAS_TRANCHES = """# Registre des conflits

Dernier passage : 10/11/2026

### C1 · Doublon marqué dans les parties prenantes
- **Détecté le** : 10/11/2026
- **Ancienne valeur** : Une personne présente deux fois (source : projet/stakeholders.md, 10/11/2026)
- **Nouvelle valeur** : Seconde ligne marquée doublon (source : projet/stakeholders.md, 10/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **Ajouté par** : reprise
- **État** : tranché le 10/11/2026 par Alex : remplacer

### C2 · Comité de pilotage le jeudi
- **Détecté le** : 10/11/2026
- **Ancienne valeur** : Le premier mardi du mois (source : 0-commerce/cahier-des-charges.md, 02/09/2026)
- **Nouvelle valeur** : Le jeudi (source : projet/decisions-log.md, 20/10/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **Ajouté par** : reprise
- **État** : tranché le 11/11/2026 par Alex : remplacer
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
        self.env = mock.patch.dict(os.environ, {'CONFLITS_AUJOURDHUI': '2026-11-16', 'MON_STUDIO': str(self.mon_studio)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.c = charger('conflits_quotidien', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
        self.registre = self.c.registre
        self.reg = self.studio / 'projet' / 'conflits.md'

    def toucher_tout(self):
        """What the Drive does: every file « modified » now."""
        t = time.time() + 3600
        for racine, _, fichiers in os.walk(self.studio):
            for f in fichiers:
                os.utime(os.path.join(racine, f), (t, t))

    def passe_complete(self):
        """A complete pass: what it read kept with « Dernier passage »."""
        plan = self.c.releve(str(self.studio))
        self.registre.poser_dernier_passage(self.reg, '2026-11-10')
        self.assertTrue(self.c.ecrire_lignes_lues(plan))

    def ajouter(self, rel, ligne):
        p = self.studio / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(ligne + '\n')


class Incremental(Base):
    def test_modification_dates_do_not_make_old_lines_new(self):
        self.passe_complete()
        self.toucher_tout()
        plan = self.c.releve(str(self.studio), None, True)
        self.assertEqual(plan['depuis'], '10/11/2026')
        self.assertEqual(plan['sujets'], [])

    def test_without_the_read_lines_the_written_dates_decide(self):
        # Checked on 10/11 before lignes-lues.json existed; every entry is dated before, every file touched since.
        self.registre.poser_dernier_passage(self.reg, '2026-11-10')
        self.toucher_tout()
        plan = self.c.releve(str(self.studio), None, True)
        self.assertEqual(plan['sujets'], [])
        self.assertFalse(self.c.chemin_lignes_lues(self.studio).exists())   # releve writes nothing

    def test_a_new_line_with_the_old_value_is_a_subject(self):
        self.passe_complete()
        self.ajouter('2-cadrage/roadmap.md', 'Le comité de pilotage se réunit le premier mardi du mois, en présentiel.')
        plan = self.c.releve(str(self.studio), None, True)
        lignes = [x['ligne_texte'] if 'ligne_texte' in x else x.get('contexte', '') for s in plan['sujets']
                  for x in s['extraits']]
        self.assertTrue(plan['sujets'])
        self.assertTrue(any('en présentiel' in l for l in lignes), lignes)
        self.assertTrue(all(any('en présentiel' in x.get('contexte', '') for x in s['extraits'])
                            for s in plan['sujets'] if s['genre'] != 'revirement'))

    def test_a_new_meeting_is_read_once(self):
        self.passe_complete()
        self.ajouter('sources/2026-11-20-cr-atelier.md',
                     "Le client revient en arrière : la remise portée à 15 % des commandes de plus de 50 pièces est annulée.")
        plan = self.c.releve(str(self.studio), None, True)
        self.assertEqual([s['genre'] for s in plan['sujets']].count('revirement'), 1)
        self.c.ecrire_lignes_lues(plan)
        self.toucher_tout()
        self.assertEqual(self.c.releve(str(self.studio), None, True)['sujets'], [])

    def test_a_meeting_dated_since_the_last_pass_counts_without_the_read_lines(self):
        self.registre.poser_dernier_passage(self.reg, '2026-11-10')
        self.ajouter('sources/2026-11-20-cr-atelier.md',
                     "Le client revient en arrière : la remise portée à 15 % des commandes de plus de 50 pièces est annulée.")
        self.ajouter('sources/2026-11-05-cr-ancien.md',
                     "Rappel : la remise des commandes de plus de 50 pièces reste discutée.")
        plan = self.c.releve(str(self.studio), None, True)
        sources = {x['fichier'] for s in plan['sujets'] if s['genre'] == 'revirement' for x in s['extraits']}
        self.assertEqual(sources, {'sources/2026-11-20-cr-atelier.md'})

    def test_the_read_lines_live_next_to_the_plan_not_inside(self):
        self.registre.poser_dernier_passage(self.reg, '2026-11-10')
        self.ajouter('sources/2026-11-20-cr-atelier.md',
                     "Le client revient en arrière : la remise portée à 15 % des commandes de plus de 50 pièces est annulée.")
        r = self.c.ouvrir_passe(str(self.studio))
        brut = json.loads(pathlib.Path(r['chemin']).read_text())
        self.assertNotIn('lu', brut)
        self.assertIn('lu', self.c.charger_plan(r['chemin']))
        self.assertEqual([os.path.realpath(x) for x in self.c.plans_du_studio(str(self.studio))], [os.path.realpath(r['chemin'])])

    def test_the_drive_refusing_the_read_lines_keeps_the_last_pass(self):
        self.passe_complete()
        os.environ['CONFLITS_AUJOURDHUI'] = '2026-11-23'
        with mock.patch.object(self.c, '_ecrire_lignes_lues', side_effect=PermissionError('Drive')):
            self.assertIsNone(self.c.passe_du_matin(str(self.studio), 90000))
        self.assertEqual(self.registre.lire_fichier(self.reg)['dernier_passage'], '10/11/2026')

    def test_a_pass_with_nothing_new_is_complete(self):
        self.passe_complete()
        os.environ['CONFLITS_AUJOURDHUI'] = '2026-11-23'
        self.assertIsNone(self.c.passe_du_matin(str(self.studio), 90000))
        self.assertEqual(self.registre.lire_fichier(self.reg)['dernier_passage'], '23/11/2026')
        self.assertEqual(json.loads(self.c.chemin_lignes_lues(self.studio).read_text())['le'], '2026-11-23')

    def test_a_complete_judged_pass_keeps_what_it_read(self):
        self.registre.poser_dernier_passage(self.reg, '2026-11-10')
        self.ajouter('sources/2026-11-20-cr-atelier.md',
                     "Le client revient en arrière : la remise portée à 15 % des commandes de plus de 50 pièces est annulée.")
        r = self.c.ouvrir_passe(str(self.studio))
        self.assertEqual(r['etat'], 'ouverte')
        jugements = [{'sujet': s['id'], 'classe': 'rien'} for s in r['plan']['sujets']]
        self.c.cloturer(r['chemin'], jugements)
        self.assertTrue(self.c.chemin_lignes_lues(self.studio).exists())
        self.assertEqual(self.c.releve(str(self.studio), None, True)['sujets'], [])


class ChaqueMatin(Base):
    def setUp(self):
        super().setUp()
        self.m = charger('matin_quotidien', SCRIPTS / 'matin.py')
        self.m.parc.SORTIE, self.m.parc.INTERNE = self.mon_studio, self.mon_studio / '.parc'
        self.studios = [{'nom': 'Projet Alpha', 'dossier': str(self.studio), 'role': 'pm'}]
        self.registre.poser_dernier_passage(self.reg, '2026-11-10')
        self.ajouter('sources/2026-11-14-cr-atelier.md',
                     "Le client revient en arrière : la remise portée à 15 % des commandes de plus de 50 pièces est annulée.")

    def note(self):
        return json.loads((self.mon_studio / '.parc' / 'conflits-semaine.json').read_text(encoding='utf-8'))

    def test_a_studio_under_automatic_ingestion_gets_its_pass(self):
        etat = {'nouvelles': [{'ts': dt.datetime.fromtimestamp(LUNDI - 3600).isoformat(), 'texte': ''}]}
        (self.studio / 'projet' / '.ingestion-auto-state.json').write_text(json.dumps(etat), encoding='utf-8')
        passes = self.m.passes_du_jour(self.studios, LUNDI)
        self.assertEqual(len(passes), 1)
        self.assertEqual(self.note()['studios'][str(self.studio)]['etat'], 'ouverte')

    def test_once_a_day_then_again_the_next_morning(self):
        self.assertEqual(len(self.m.passes_du_jour(self.studios, LUNDI)), 1)
        self.assertEqual(self.m.passes_du_jour(self.studios, LUNDI + 600), [])
        self.assertEqual(self.note()['jour'], '2026-11-16')
        self.assertEqual(len(self.m.passes_du_jour(self.studios, LUNDI + 86400)), 1)   # not judged yet: offered again
        self.assertEqual(self.note()['jour'], '2026-11-17')

    def test_never_for_a_studio_the_person_does_not_lead(self):
        membre = [dict(self.studios[0], role='membre')]
        self.assertEqual(self.m.passes_du_jour(membre, LUNDI), [])

    def test_the_instructions_speak_of_every_morning(self):
        consigne = (ROOT / 'skills' / 'mon-studio' / 'assets' / 'consigne-point-du-matin.md').read_text(encoding='utf-8')
        self.assertNotIn('le lundi les conflits', consigne)
        self.assertNotIn('# 6. Le lundi', consigne)
        skill = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('ne propose jamais de prompt à coller', skill)
        self.assertNotIn('Un Studio dont l\'ingestion automatique est active est sauté', skill)


class Revirement(Base):
    def test_header_lines_and_names_are_not_substance(self):
        c = self.c
        self.assertEqual(c.mots_de_fond('**Présents :** Alex Martin, Sam Durand. Absents : Lou Bernard.'), set())
        self.assertNotIn('martin', c.mots_de_fond('Le comité valide avec Alex Martin la remise des commandes.'))
        # A bold lead-in that is not a header keeps its substance.
        self.assertIn('delai', c.mots_de_fond('- **Décision** : on passe le délai de livraison à 12 jours.'))
        self.assertIn('tarif', c.mots_de_fond('- Tarif des grosses commandes relevé.'))
        self.assertIn('remise', c.mots_de_fond('Le comité valide avec Alex Martin la remise des commandes.'))


class HorsJournal(Base):
    def setUp(self):
        super().setUp()
        self.reg.write_text(CAS_TRANCHES, encoding='utf-8')
        self.p = charger('projets_quotidien', SCRIPTS / 'projets.py')
        self.p.parc.SORTIE, self.p.parc.INTERNE = self.mon_studio, self.mon_studio / '.parc'

    def test_a_case_set_aside_leaves_the_journal_and_stays_in_the_register(self):
        avant = self.reg.read_bytes()
        self.assertEqual(self.registre.mettre_hors_journal(str(self.studio), ['C1'], 'doublon marqué', 'Alex'), ['C1'])
        self.assertEqual(self.reg.read_bytes(), avant)
        t = self.p.conflits_du_registre(str(self.studio), [])
        self.assertEqual([x['sujet'] for x in t['journal']], ['Comité de pilotage le jeudi'])
        self.assertEqual((t['tranches'], t['hors_journal']), (1, 1))

    def test_the_snapshot_keeps_the_list_when_the_drive_refuses(self):
        self.registre.mettre_hors_journal(str(self.studio), ['C1'], 'doublon marqué', 'Alex')
        garde = {str(self.studio): {'conflits': CAS_TRANCHES,
                                    'conflits_hors_journal': {'cas': {'C1': 'doublon marqué'}}}}
        with mock.patch.object(pathlib.Path, 'read_text', side_effect=PermissionError('Drive')):
            self.assertEqual(self.registre.hors_journal(str(self.studio), garde[str(self.studio)]['conflits_hors_journal']),
                             {'C1': 'doublon marqué'})

    def test_an_unknown_case_is_refused(self):
        with self.assertRaises(ValueError):
            self.registre.mettre_hors_journal(str(self.studio), ['C9'], 'doublon', 'Alex')
        self.assertFalse(self.registre.chemin_hors_journal(self.studio).exists())

    def test_the_command(self):
        code = self.c.main(['cacher', str(self.studio), 'C1', '--raison', 'doublon marqué', '--pm', 'Alex'])
        self.assertEqual(code, 0)
        self.assertEqual(self.registre.hors_journal(str(self.studio)), {'C1': 'doublon marqué'})


if __name__ == '__main__':
    unittest.main()
