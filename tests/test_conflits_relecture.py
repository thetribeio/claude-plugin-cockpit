"""Tests of what the « Conflits » tab says of the re-read (2026-11-17): python3 -m unittest discover -s tests

« Dernier passage » is the date of the last complete pass, not of the last look. The Monday pass of the morning point
notes what it did of each checked Studio (re-read, nothing new, skipped for an active ingestion, too large, failed) next
to the week's marker; the tab says it with its reason and its date, and writes « Studio à jour » only when a re-read
found nothing or was judged whole. Synthetic data, temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import _studio_conflits as F

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
LUNDI = dt.datetime(2026, 11, 16, 7, 31).timestamp()


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
        self.m = charger('matin_relecture', SCRIPTS / 'matin.py')
        self.p = charger('projets_relecture', SCRIPTS / 'projets.py')
        for module in (self.m, self.p):
            module.parc.SORTIE, module.parc.INTERNE = self.mon_studio, self.mon_studio / '.parc'
        self.conflits = self.m._charger_conflits()
        self.d = str(self.studio)
        self.studios = [{'nom': 'Projet Alpha', 'dossier': self.d, 'role': 'pm'}]

    def verifie(self, jour='2026-11-10'):
        self.conflits.registre.poser_dernier_passage(self.studio / 'projet' / 'conflits.md', jour)

    def ingestion(self, quand):
        etat = {'nouvelles': [{'ts': dt.datetime.fromtimestamp(quand).isoformat(), 'texte': ''}]}
        (self.studio / 'projet' / '.ingestion-auto-state.json').write_text(json.dumps(etat), encoding='utf-8')

    def note(self):
        return json.loads((self.mon_studio / '.parc' / 'conflits-semaine.json').read_text(encoding='utf-8'))

    def relecture(self, maintenant=LUNDI + 86400):
        c = self.p.conflits_du_projet(self.d, [])
        r = self.p.relecture_du_studio(self.d, c['dernier_passage'], None, maintenant)
        self.assertEqual(c['relecture']['etat'], r['etat'])      # the tab carries it
        return r


class CeQueLeLundiNote(Base):
    def test_a_never_checked_studio_is_not_noted(self):
        self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI), [])
        self.assertEqual(self.note()['studios'], {})
        self.assertIsNone(self.p.conflits_du_projet(self.d, [])['relecture'])

    def test_a_pass_handed_to_the_morning_task(self):
        self.verifie('2026-01-01')
        passes = self.m.passes_de_la_semaine(self.studios, LUNDI)
        self.assertEqual(self.note()['studios'], {self.d: {'etat': 'ouverte', 'sujets': passes[0]['sujets']}})
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour'], r['le']), ('remise', False, '16/11'))
        self.assertIn('Relecture du 16/11 pas finie', r['texte'])
        self.assertIn('Dernier passage complet : le 01/01.', r['texte'])
        # Judged whole: « Dernier passage » moves to that Monday, and only then the Studio is up to date.
        self.verifie('2026-11-16')
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour']), ('faite', True))
        self.assertEqual(r['texte'], 'Relu le 16/11 : les nouveautés sont jugées.')

    def test_nothing_new(self):
        self.verifie('2026-01-01')
        with mock.patch.object(self.conflits, 'passe_du_matin', return_value=None), \
                mock.patch.object(self.m, '_charger_conflits', return_value=self.conflits):
            self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI), [])
        self.assertEqual(self.note()['studios'], {self.d: {'etat': 'rien'}})
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour']), ('rien', True))
        self.assertEqual(r['texte'], 'Relu le 16/11 : rien de nouveau depuis le passage complet du 01/01.')

    def test_skipped_for_an_active_ingestion(self):
        self.verifie()
        self.ingestion(LUNDI - 86400)
        self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI), [])
        self.assertEqual(self.note()['studios'], {self.d: {'etat': 'ingestion'}})
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour'], r['le']), ('ingestion', False, '16/11'))
        self.assertIn("Relecture du 16/11 sautée : l'ingestion automatique passe sur ce Studio", r['texte'])
        self.assertIn('Dernier passage complet : le 10/11.', r['texte'])

    def test_too_large(self):
        self.verifie('2026-01-01')
        self.conflits.PASSE_MATIN_CARACTERES = 100
        with mock.patch.object(self.m, '_charger_conflits', return_value=self.conflits):
            self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI), [])
        x = self.note()['studios'][self.d]
        self.assertEqual(x['etat'], 'trop')
        self.assertGreater(x['sujets'], 0)
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour'], r['sujets']), ('trop', False, x['sujets']))
        self.assertIn('Relecture du 16/11 pas faite', r['texte'])
        self.assertIn("plus que ce qu'un point du matin relit", r['texte'])

    def test_a_failure_is_noted_and_never_stops_the_morning_point(self):
        self.verifie('2026-01-01')
        with mock.patch.object(self.conflits, 'passe_du_matin', side_effect=RuntimeError('lecture')), \
                mock.patch.object(self.m, '_charger_conflits', return_value=self.conflits):
            self.assertEqual(self.m.passes_de_la_semaine(self.studios, LUNDI), [])
        self.assertEqual(self.note()['studios'], {self.d: {'etat': 'erreur'}})
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour']), ('erreur', False))
        self.assertIn('Relecture du 16/11 en échec', r['texte'])


class SansNoteDuLundi(Base):
    def test_no_re_read_yet(self):
        self.verifie()
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour'], r['le']), ('aucune', False, ''))
        self.assertEqual(r['texte'], "Pas relu depuis le passage complet du 10/11 : la relecture du lundi n'a pas encore "
                                     "tourné sur ce Studio.")

    def test_a_marker_of_an_earlier_version_gives_the_ingestion_as_the_reason(self):
        self.verifie()
        self.ingestion(LUNDI)
        (self.mon_studio / '.parc' / 'conflits-semaine.json').write_text(
            json.dumps({'semaine': '2026-S47', 'le': '2026-11-16T07:35:29'}), encoding='utf-8')
        r = self.relecture()
        self.assertEqual((r['etat'], r['a_jour']), ('aucune', False))
        self.assertIn('Pas relu depuis le passage complet du 10/11', r['texte'])
        self.assertIn("l'ingestion automatique passe sur ce Studio", r['texte'])
        # Silent for more than 8 days, the ingestion is no longer the reason.
        r = self.relecture(LUNDI + 9 * 86400)
        self.assertIn("n'a pas encore tourné", r['texte'])

    def test_the_ingestion_read_from_the_snapshot_when_the_drive_refuses(self):
        self.verifie()
        self.ingestion(LUNDI)
        garde = {self.d: self.p.lire_sources(self.d, LUNDI)}
        self.assertEqual(garde[self.d]['ingestion_derniere'], LUNDI)
        with mock.patch.object(pathlib.Path, 'read_text', side_effect=PermissionError('Drive')):
            self.assertTrue(self.p.ingestion_recente(self.d, garde, LUNDI + 86400))
            self.assertFalse(self.p.ingestion_recente(self.d, garde, LUNDI + 9 * 86400))
            self.assertIsNone(self.p.ingestion_recente(self.d, {}, LUNDI + 86400))
            # Not known: no reason given, rather than a wrong one.
            self.assertEqual(self.p.relecture_du_studio(self.d, '10/11/2026', {}, LUNDI + 86400)['texte'],
                             'Pas relu depuis le passage complet du 10/11.')

    def test_a_complete_pass_after_the_monday_replaces_its_note(self):
        self.verifie('2026-11-18')
        (self.mon_studio / '.parc' / 'conflits-semaine.json').write_text(json.dumps(
            {'semaine': '2026-S47', 'le': '2026-11-16T07:35:29', 'studios': {self.d: {'etat': 'trop', 'sujets': 40}}}),
            encoding='utf-8')
        r = self.relecture(LUNDI + 3 * 86400)
        self.assertEqual(r['etat'], 'aucune')
        self.assertIn('Pas relu depuis le passage complet du 18/11', r['texte'])

    def test_the_eight_days_are_the_pass_s_own(self):
        self.assertEqual(self.p.INGESTION_ACTIVE_S, self.conflits.INGESTION_ACTIVE_S)


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    A = '/studios/Projet Alpha'

    def run_page(self, **k):
        c = {'ouverts': [], 'illisibles': 0, 'session': None, 'titre_session': 'Projet Alpha · Conflits Studio',
             'commande': '/cockpit:conflits', 'lu': True, 'nouveaux': 0, 'relance': False, 'raison': '',
             'a_traiter': {'evident': 0, 'arbitrage': 0}, 'jours': 0, 'dernier_passage': '10/11/2026', 'journal': [],
             'tranches': 0, 'verification': 'verifie'}
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
        return json.loads(r.stdout)['projetConflits']

    def test_skipped_is_said_with_its_reason_and_never_up_to_date(self):
        texte = "Relecture du 16/11 sautée : l'ingestion automatique passe sur ce Studio. Dernier passage complet : le 10/11."
        html = self.run_page(relecture={'etat': 'ingestion', 'a_jour': False, 'le': '16/11', 'sujets': 0, 'texte': texte})
        self.assertIn('<strong>Dernier passage complet le 10/11</strong>', html)
        self.assertIn('Relecture du 16/11 sautée', html)
        self.assertNotIn('à jour', html)

    def test_up_to_date_only_after_a_re_read(self):
        html = self.run_page(relecture={'etat': 'rien', 'a_jour': True, 'le': '16/11', 'sujets': 0,
                                        'texte': 'Relu le 16/11 : rien de nouveau depuis le passage complet du 10/11.'})
        self.assertIn('<strong>Studio à jour</strong> · Relu le 16/11 : rien de nouveau', html)

    def test_without_the_field_the_date_alone(self):
        html = self.run_page()
        self.assertIn('<strong>Dernier passage complet le 10/11</strong>', html)
        self.assertNotIn('à jour', html)


if __name__ == '__main__':
    unittest.main()
