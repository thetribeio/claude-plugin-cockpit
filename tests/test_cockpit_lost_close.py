"""Tests: a « Fait » is never lost (2026-11-18): python3 -m unittest discover -s tests

Measured on the PM's board: « Fait / Retirer du tableau » closed an ingestion line at 23:11:22, a computation of the
board that had read projets-etat.json before the click wrote it back at 23:11:24, and the line came back. And the first
click never reached the connector: the page sent « clore » only after its 10 s « Annuler », a reload in between lost it.

1. Every read-modify-write of projets-etat.json holds a file lock; the computation re-reads the disk under the lock
   right before writing and keeps what a click or a Slack judgement wrote since its own read.
2. « clore » with « rouvrir » (the page's « Annuler », now sent after a « clore » made at the click) reopens only a
   closure of the page made less than a minute ago: an ingestion line, a line of a session, a third-party wait.

Studios, cards and states are synthetic (temporary HOME); the real app and ~/Mon Studio are never used."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import threading
import time
import unittest

import test_cockpit_projets as tp

SLACK = 'https://exemple.slack.com/archives/C0TEST/p1794000000000100'
REPONSE = 'https://exemple.slack.com/archives/C0TEST/p1794000900000100'


class Race(tp.Base):
    def etat(self):
        return json.loads((self.mon_studio / '.parc' / 'projets-etat.json').read_text(encoding='utf-8'))['lignes']

    def a_toi(self, out):
        return next(l['cle'] for l in self.block(out)['lignes'] if l['type'] == 'a_toi')

    def pendant_le_calcul(self, geste):
        """The next computation runs `geste` once, after it has read the state and before it writes it."""
        vrai = self.p.lignes_du_studio

        def lignes_du_studio(*a, **k):
            if not getattr(lignes_du_studio, 'fait', False):
                lignes_du_studio.fait = True
                geste()
            return vrai(*a, **k)
        self.p.lignes_du_studio = lignes_du_studio
        self.addCleanup(setattr, self.p, 'lignes_du_studio', vrai)

    def test_a_close_made_during_a_computation_is_kept(self):
        self.runs(self.alpha, (tp.FRIDAY, tp.REPORT))
        cle = self.a_toi(self.compute())
        self.pendant_le_calcul(lambda: self.p.fermer(cle, tp.MONDAY + 30))
        out = self.compute(tp.MONDAY + 31)
        self.assertEqual((self.etat()[cle]['fermee'], self.etat()[cle]['par']), (tp.MONDAY + 30, 'main'))
        self.assertNotIn(cle, [l['cle'] for l in self.block(out)['lignes']], 'the line closed meanwhile is not shown')
        self.assertNotIn('a_toi', self.types(self.compute(tp.MONDAY + 60)))

    def test_the_computation_keeps_its_own_changes_on_other_lines(self):
        self.runs(self.alpha, (tp.FRIDAY, tp.REPORT))
        cle = self.a_toi(self.compute())
        self.table = [self.question()]
        self.pendant_le_calcul(lambda: self.p.fermer(cle, tp.MONDAY + 30))
        self.compute(tp.MONDAY + 31)
        etat = self.etat()
        self.assertEqual(etat[cle]['par'], 'main')
        self.assertIn('question', [l['type'] for l in etat.values()], 'the question noted by this computation is written')

    def test_a_slack_judgement_made_during_a_computation_is_kept(self):
        self.runs(self.alpha, (tp.FRIDAY, tp.REPORT))
        cle = self.a_toi(self.compute())
        etat = self.etat()
        etat[cle]['lien'] = SLACK
        self.p.ecrire_etat(etat)
        self.pendant_le_calcul(lambda: self.p.slack_juger([{'cle': cle, 'verdict': 'reglee', 'resume': 'Devis validé par Ana',
                                                            'reponse': REPONSE, 'suite': 'Envoyer le devis à Léo'}],
                                                          tp.MONDAY + 30))
        self.compute(tp.MONDAY + 31)
        etat = self.etat()
        self.assertEqual((etat[cle]['par'], etat[cle]['preuve'], etat[cle]['resume']), ('slack', REPONSE, 'Devis validé par Ana'))
        self.assertTrue(any(l.get('suite_de') == cle and not l['fermee'] for l in etat.values()), 'the suite is kept')

    def test_merge_rules(self):
        lu = {'a' * 12: {'fermee': None, 'par': None, 'vue': 1}, 'b' * 12: {'fermee': None, 'par': None, 'vue': 1}}
        calcule = {'a' * 12: {'fermee': None, 'par': None, 'vue': 5}, 'b' * 12: {'fermee': 9, 'par': 'source', 'vue': 5}}
        disque = {'a' * 12: {'fermee': 3, 'par': 'main', 'vue': 1}, 'b' * 12: dict(lu['b' * 12]),
                  'c' * 12: {'fermee': None, 'par': None, 'vue': 4}}
        out = self.p.fusionner_etat(lu, calcule, disque)
        self.assertEqual(out['a' * 12], {'fermee': 3, 'par': 'main', 'vue': 5})       # the click, and the computation's own field
        self.assertEqual(out['b' * 12], calcule['b' * 12])                            # nobody else touched it
        self.assertEqual(out['c' * 12], disque['c' * 12])                             # added since

    def test_fermer_waits_for_the_lock(self):
        self.runs(self.alpha, (tp.FRIDAY, tp.REPORT))
        cle = self.a_toi(self.compute())
        fini = threading.Event()
        with self.p.verrou_etat():
            t = threading.Thread(target=lambda: (self.p.fermer(cle, tp.MONDAY + 30), fini.set()))
            t.start()
            self.assertFalse(fini.wait(0.3), 'fermer writes only once the lock is free')
        t.join(5)
        self.assertTrue(fini.is_set())
        self.assertEqual(self.etat()[cle]['par'], 'main')


class Reopen(tp.Base):
    connector = tp.Connector.connector
    call = tp.Connector.call

    def test_rouvrir_undoes_only_a_recent_close_by_hand(self):
        self.runs(self.alpha, (tp.FRIDAY, tp.REPORT))
        cle = next(l['cle'] for l in self.block(self.compute())['lignes'] if l['type'] == 'a_toi')
        with self.assertRaises(ValueError):
            self.p.rouvrir(cle, tp.MONDAY + 10)   # open: nothing to undo
        self.p.fermer(cle, tp.MONDAY + 10)
        with self.assertRaises(ValueError):
            self.p.rouvrir(cle, tp.MONDAY + 10 + 61)   # more than a minute
        self.assertEqual(self.p.rouvrir(cle, tp.MONDAY + 20), {'rouvert': cle})
        self.assertIn('a_toi', self.types(self.compute(tp.MONDAY + 30)))
        etat = self.p.lire_etat()
        etat[cle].update(fermee=tp.MONDAY + 40, par='source')
        self.p.ecrire_etat(etat)
        with self.assertRaises(ValueError):
            self.p.rouvrir(cle, tp.MONDAY + 45)   # closed by its source, not by the PM's click

    def test_connector_reopens_each_kind_of_line(self):
        m = self.connector()
        self.runs(self.alpha, (time.time() - 60, tp.REPORT))
        cle = next(l['cle'] for l in self.block(self.p.calculer(e={'tableau': []}, metas=self.metas))['lignes']
                   if l['type'] == 'a_toi')
        parc = self.mon_studio / '.parc'
        sid = 'local_00000000-0000-0000-0000-0000000000e1'
        maintenant = time.time()
        (parc / 'retirees.json').write_text(json.dumps({
            'r00000000000a': {'session': sid, 'question': 'Q3', 'titre': 'Q3 · Format', 'quand': maintenant - 5,
                              'prevenue': True, 'abandon': True},
            'r00000000000b': {'session': sid, 'question': 'Q4', 'titre': 'Q4 · Plan', 'quand': maintenant - 300,
                              'prevenue': False}}), encoding='utf-8')
        (parc / 'abandonnees.json').write_text(json.dumps({sid: {'titre': 'Cadrage Camille', 'quand': maintenant - 5}}), encoding='utf-8')
        (parc / 'tiers-recus.json').write_text(json.dumps({'t0123456789ab': maintenant - 5}), encoding='utf-8')
        ferme, ouvert, r_ok, r_vieux, t_ok, bad = self.call(
            m, ('clore', {'cle': cle}), ('clore', {'cle': cle, 'rouvrir': True}),
            ('clore', {'cle': 'r00000000000a', 'rouvrir': True}), ('clore', {'cle': 'r00000000000b', 'rouvrir': True}),
            ('clore', {'cle': 't0123456789ab', 'rouvrir': True}), ('clore', {'cle': '../x', 'rouvrir': True}))
        self.assertEqual(json.loads(ouvert['result']['content'][0]['text']), {'rouvert': cle})
        self.assertFalse(self.p.lire_etat()[cle]['fermee'])
        self.assertEqual(json.loads(r_ok['result']['content'][0]['text']), {'rouvert': 'r00000000000a'})
        self.assertTrue(r_vieux['result']['isError'], 'a removal older than a minute stays')
        self.assertEqual(json.loads(t_ok['result']['content'][0]['text']), {'rouvert': 't0123456789ab'})
        self.assertTrue(bad['result']['isError'])
        self.assertEqual(set(json.loads((parc / 'retirees.json').read_text(encoding='utf-8'))), {'r00000000000b'})
        self.assertEqual(json.loads((parc / 'abandonnees.json').read_text(encoding='utf-8')), {}, 'the abandon is undone too')
        self.assertEqual(json.loads((parc / 'tiers-recus.json').read_text(encoding='utf-8')), {})
        listed, = self.call(m, ('list', None))
        schema = next(t for t in listed['result']['tools'] if t['name'] == 'clore')['inputSchema']['properties']
        self.assertEqual(schema['rouvrir'], {'type': 'boolean'})


class Page(unittest.TestCase):
    def test_a_reload_after_the_click_loses_nothing_and_abandon_is_sent_at_once(self):
        from test_cockpit_board_lighter import ligne, run_page
        # The click sends « clore » before any timer fires: a reload in the 10 s finds the line closed on the Mac.
        r = run_page(lignes=[ligne()], cliquer=[['data-retirer', 'r00000000000a']])
        self.assertEqual([a for a in r['appels'] if a[0] == 'clore'], [['clore', {'cle': 'r00000000000a'}]])
        self.assertIn('data-annuler="r00000000000a"', r['tableau'])


if __name__ == '__main__':
    unittest.main()
