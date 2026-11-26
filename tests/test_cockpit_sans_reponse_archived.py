"""Tests: « Sans réponse » of Today (PM, 2026-11-20): a wait whose source session is archived does not show.
Sessions and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import time
import unittest

from test_cockpit_board_lighter import charger

parc = charger('parc_sans_reponse', 'parc.py')
JOUR = 86400


class ArchivedSource(unittest.TestCase):
    def test_a_wait_of_an_archived_session_is_dropped(self):
        maintenant = time.time()
        quand = lambda j: time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(maintenant - j * JOUR))
        journal = [
            {'type': 'blocked', 'sessionId': 'a', 'session': 'Reprise', 'text': 'Cockpit pas publié : reprendre les points', 'at': quand(13)},
            {'type': 'blocked', 'sessionId': 'b', 'session': 'Suivi', 'text': 'Ana : exemplaire signé du contrat', 'at': quand(13)},
        ]
        metas = [{'id': 'a', 'archivee': True, 'cwd': ''}, {'id': 'b', 'archivee': False, 'cwd': ''}]
        ancien = (parc.chantiers_actifs, parc.dossiers_du_miroir, parc.journal_du_miroir, parc.tiers_recus)
        parc.chantiers_actifs = lambda m: [{'chantier': 'Essai', 'sessionId': 'b'}]
        parc.dossiers_du_miroir = lambda c, cwd: ['/x/Essai']
        parc.journal_du_miroir = lambda c: journal
        parc.tiers_recus = lambda: {}
        try:
            r = parc.sans_reponse({'genere': maintenant, '_metas': metas, 'tableau': []}, maintenant)
        finally:
            parc.chantiers_actifs, parc.dossiers_du_miroir, parc.journal_du_miroir, parc.tiers_recus = ancien
        self.assertEqual([x['session'] for x in r], ['b'])


if __name__ == '__main__':
    unittest.main()
