"""Order of the board (PM, Q37 of 2026-11-06): python3 -m unittest discover -s tests

Within a Studio: a close deadline first (soonest first), then the most recent. « Une session attend » stays written on
the line but puts it in front only for 24 h after it appeared. The grouping by Studio stays. The project view reads the
same order (vue_projet keeps the board's). Mirrors and cards here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc_q37', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN = 'local_foreman'
NOW = 1_760_400_000.0


def iso(t):
    return dt.datetime.fromtimestamp(t).astimezone().isoformat(timespec='seconds')


class Order(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name)

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def board(self, waits):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': iso(NOW), 'attentes': waits}))
        cards = [{'id': FOREMAN, 'archivee': False, 'cwd': '/studios/Studio-Essai', 'titre': 'Contremaître', 'parent': None}]
        return parc.tableau([], cards, [], 7, NOW, {})

    def titles(self, waits):
        return [l['suite'].split(' · ')[1] for l in self.board(waits)]

    def test_old_blocked_line_takes_its_place_by_age(self):
        waits = [{'type': 'decision', 'titre': 'Q1 · Ancienne bloquante', 'bloque': True, 'depuis': iso(NOW - 3 * 86400)},
                 {'type': 'decision', 'titre': 'Q2 · Toute fraîche', 'depuis': iso(NOW - 240)},
                 {'type': 'decision', 'titre': 'Q3 · Bloquante récente', 'bloque': True, 'depuis': iso(NOW - 7200)},
                 {'type': 'decision', 'titre': 'Q4 · Échéance demain', 'depuis': iso(NOW - 2 * 86400),
                  'echeance': (dt.date.fromtimestamp(NOW) + dt.timedelta(days=1)).isoformat()}]
        self.assertEqual(self.titles(waits), ['Échéance demain', 'Bloquante récente', 'Toute fraîche', 'Ancienne bloquante'])
        lines = {l['suite'].split(' · ')[1]: l for l in self.board(waits)}
        self.assertTrue(lines['Ancienne bloquante']['bloque'])   # still written on the line

    def test_close_deadlines_soonest_first_far_ones_by_age(self):
        jour = dt.date.fromtimestamp(NOW)
        waits = [{'type': 'task', 'titre': 'Q1 · Dans trois jours', 'depuis': iso(NOW - 600), 'echeance': (jour + dt.timedelta(days=3)).isoformat()},
                 {'type': 'task', 'titre': 'Q2 · Demain', 'depuis': iso(NOW - 86400), 'echeance': (jour + dt.timedelta(days=1)).isoformat()},
                 {'type': 'task', 'titre': 'Q3 · Dans un mois', 'depuis': iso(NOW - 2 * 86400), 'echeance': (jour + dt.timedelta(days=30)).isoformat()},
                 {'type': 'task', 'titre': 'Q4 · Récente', 'depuis': iso(NOW - 60)}]
        self.assertEqual(self.titles(waits), ['Demain', 'Dans trois jours', 'Récente', 'Dans un mois'])

    def test_rank(self):
        self.assertEqual(parc.rang_urgence({'bloque': True, 'depuis': NOW - 3600}, NOW), (parc.RANG_ATTEND,))
        self.assertEqual(parc.rang_urgence({'bloque': True, 'depuis': NOW - 25 * 3600}, NOW), (parc.RANG_OUVERTE,))
        self.assertEqual(parc.rang_urgence({'proche': True, 'bloque': True, 'depuis': NOW}, NOW), (parc.RANG_PROCHE,))
        self.assertEqual(parc.rang_urgence({'reglee': True, 'proche': True}, NOW), (parc.RANG_A_CONFIRMER,))


if __name__ == '__main__':
    unittest.main()
