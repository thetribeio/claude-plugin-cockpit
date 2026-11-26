"""Mon Studio suggests a full conflicts pass every 30 days (2026-11-19): python3 -m unittest discover -s tests

Ingestion reports new conflicts to the register as it finds them, but not all of them. The tab and « Ce qui t'attend »
therefore suggest a full pass (`/cockpit:conflits rattrapage`) once the register's « Dernier passage » is 30 days old
(`repasse_jours` in projet/.conflits/reglages.json, 1..365). Synthetic data, temporary HOME."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import test_cockpit_projets as tp

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
CONFLITS = 'local_00000000-0000-0000-0000-00000000000d'
JOUR = 86400
PASSAGE = '01/10/2026'
DEPART = tp.local(2026, 10, 1, 12)


def apres(jours):
    return DEPART + jours * JOUR


class Base(tp.Base):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {'COCKPIT_IDENTITE': 'ana exemple'})
        env.start()
        self.addCleanup(env.stop)
        self.membre = self.studio('Studio - Beta', pm='Léo EXEMPLE')
        for d, pm in ((self.alpha, 'Ana EXEMPLE'),):
            (pathlib.Path(d) / 'projet' / 'fiche-projet.md').write_text(
                '# Fiche projet\n\n| Champ | Valeur |\n|---|---|\n| **PM** | ' + pm + ' |\n', encoding='utf-8')
        self.passage(self.alpha, PASSAGE)

    def passage(self, studio, jour):
        (pathlib.Path(studio) / 'projet' / 'conflits.md').write_text(
            '# Registre des conflits\n\nDernier passage : ' + jour + '\n', encoding='utf-8')

    def reglages(self, studio, contenu):
        p = pathlib.Path(studio) / 'projet' / '.conflits'
        p.mkdir(parents=True, exist_ok=True)
        (p / 'reglages.json').write_text(json.dumps(contenu), encoding='utf-8')

    def onglet(self, jours, studio=None):
        return self.p.conflits_du_projet(studio or self.alpha, self.metas, maintenant=apres(jours))

    def ligne(self, jours, etat=None):
        etat = {} if etat is None else etat
        c = self.onglet(jours)
        return self.p.ligne_repasse_conflits(self.alpha, c, etat, apres(jours), self.metas), etat


class Repasse(Base):
    def test_due_after_30_days_and_not_before(self):
        self.assertEqual(self.onglet(29)['repasse'], {'due': False, 'jours': 29, 'seuil': 30})
        self.assertEqual(self.onglet(30)['repasse'], {'due': True, 'jours': 30, 'seuil': 30})
        self.assertEqual(self.onglet(41)['repasse']['jours'], 41)

    def test_the_setting_is_honoured_and_invalid_values_are_ignored(self):
        self.reglages(self.alpha, {'repasse_jours': 7})
        self.assertEqual(self.onglet(7)['repasse'], {'due': True, 'jours': 7, 'seuil': 7})
        self.assertFalse(self.onglet(6)['repasse']['due'])
        for mauvais in (0, 366, -3, '10', 7.5, True, None, [7]):
            self.reglages(self.alpha, {'repasse_jours': mauvais})
            self.assertEqual(self.onglet(10)['repasse']['seuil'], 30, repr(mauvais))
        self.reglages(self.alpha, {'repasse_jours': 365})
        self.assertEqual(self.onglet(10)['repasse']['seuil'], 365)

    def test_never_checked_has_no_repasse(self):
        (pathlib.Path(self.alpha) / 'projet' / 'conflits.md').write_text('# Registre des conflits\n', encoding='utf-8')
        c = self.onglet(90)
        self.assertIsNone(c['repasse'])
        self.assertIsNone(self.p.ligne_repasse_conflits(self.alpha, c, {}, apres(90), self.metas))

    def test_the_line_says_what_it_is_and_where_it_runs(self):
        self.assertIsNone(self.ligne(29)[0])
        l, _ = self.ligne(41)
        self.assertEqual(l['type'], 'repasse')
        self.assertEqual(l['titre'], 'Refaire une passe complète des conflits')
        self.assertIn("Dernier passage complet il y a 41 jours. L'ingestion signale les conflits au fil de l'eau, "
                      'mais pas tous : une passe complète rattrape le reste.', l['detail'])
        self.assertEqual(l['copier'], '/cockpit:conflits rattrapage')
        self.assertIn('la session la plus récente du Studio', l['detail'])
        self.assertTrue(l['session'])

    def test_with_a_conflicts_session_the_button_opens_it_without_copying(self):
        self.metas.append(self.card(CONFLITS, self.alpha, 'Alpha · Conflits Studio', 300))
        l, _ = self.ligne(41)
        self.assertEqual((l['session'], l['copier']), (CONFLITS, ''))
        self.assertIn('Dans la session « Alpha · Conflits Studio »', l['detail'])

    def test_closed_it_stays_hidden_until_the_next_period_and_a_new_pass_resets_it(self):
        l, etat = self.ligne(31)
        etat[l['cle']].update(fermee=apres(31), par='main')
        self.assertIsNone(self.ligne(50, etat)[0])
        self.assertIsNone(self.ligne(59, etat)[0])
        suivante, _ = self.ligne(60, etat)
        self.assertIsNotNone(suivante)
        self.assertNotEqual(suivante['cle'], l['cle'])
        # a new full pass on 15/10: due again 30 days after it, under another key
        self.passage(self.alpha, '15/10/2026')
        self.assertIsNone(self.ligne(43, etat)[0])
        nouvelle, _ = self.ligne(44, etat)
        self.assertNotIn(nouvelle['cle'], (l['cle'], suivante['cle']))

    def test_for_a_pm_studio_only(self):
        self.passage(self.membre, PASSAGE)
        out = self.compute(apres(41))
        self.assertIn('repasse', self.types(out, 'Alpha'))
        self.assertNotIn('repasse', self.types(out, 'Beta'))
        # closed by the board's « clore », it does not come back at the next computation
        cle = next(l['cle'] for l in self.block(out)['lignes'] if l['type'] == 'repasse')
        self.p.fermer(cle, apres(41) + 5)
        self.assertNotIn('repasse', self.types(self.compute(apres(42))))
        self.assertNotIn('repasse', self.types(self.compute(apres(41 + 9))))   # past the purge delay too

    def test_a_failure_costs_only_the_line(self):
        with mock.patch.object(self.p, 'ligne_repasse_conflits', side_effect=ValueError('x')):
            out = self.compute(apres(41))
        self.assertNotIn('repasse', self.types(out))
        self.assertIn('Alpha', [b['nom'] for b in self.compute(apres(10))['projets']] + ['Alpha'])


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    A = '/studios/Projet Alpha'

    def run_page(self, repasse, session=None, session_studio=None):
        c = {'ouverts': [], 'illisibles': 0, 'session': session, 'titre_session': 'Projet Alpha · Conflits Studio',
             'commande': '/cockpit:conflits', 'lu': True, 'nouveaux': 0, 'relance': False, 'raison': '',
             'a_traiter': {'evident': 0, 'arbitrage': 0}, 'jours': 0, 'dernier_passage': '01/10/2026', 'journal': [],
             'tranches': 0, 'verification': 'verifie', 'en_cours': [], 'sessions_actives': [], 'backlog': None,
             'repasse': repasse, 'session_studio': session_studio}
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

    def test_due_the_header_says_it_and_the_button_follows(self):
        html = self.run_page({'due': True, 'jours': 41, 'seuil': 30}, session_studio='local_' + 'a' * 36)
        self.assertIn('<strong>Dernier passage complet le 01/10</strong> · Dernier passage complet il y a 41 jours : '
                      "une nouvelle passe rattrape ce que l'ingestion n'a pas vu", html)
        self.assertIn('Refaire une passe complète ↗', html)
        self.assertIn('data-copier="/cockpit:conflits rattrapage"', html)
        self.assertIn('data-sid="local_' + 'a' * 36 + '"', html)

    def test_with_the_conflicts_session_the_button_opens_it(self):
        html = self.run_page({'due': True, 'jours': 41, 'seuil': 30}, session={'sessionId': CONFLITS, 'titre': 'S'})
        self.assertIn('data-sid="' + CONFLITS + '"', html)
        self.assertIn('Refaire une passe complète ↗', html)

    def test_not_due_nothing_changes(self):
        for rp in ({'due': False, 'jours': 12, 'seuil': 30}, None):
            html = self.run_page(rp)
            self.assertNotIn('Refaire une passe complète', html)
            self.assertNotIn('il y a ', html)


if __name__ == '__main__':
    unittest.main()
