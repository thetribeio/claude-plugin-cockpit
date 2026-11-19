"""Tests: a Mail line says when the mail was received and where its due date comes from (PM, 2026-11-19).

The ingestion kit may write ` (reçu le AAAA-MM-JJ)` and ` (échéance AAAA-MM-JJ, lue dans le mail)` or
` (échéance AAAA-MM-JJ, calculée : <règle>)` at the end of a bullet. projets.py carries them on the line; the page shows
« reçu le 18/11 » beside the due date and, in the unfold, the date and its origin. What no bullet says is never invented:
« noté le » (the pass day, said as such) and « origine de l'échéance inconnue ». python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from test_cockpit_projets import Base, MONDAY, RUNNER, PAGE
from test_cockpit_board_actionable import a_toi, liste, rangee

MAILLIEN = '([source](https://mail.google.com/mail/u/0/#inbox/abc))'


def run_with(*bullets):
    return '📬 Alpha · nouveautés\nÀ toi de jouer :\n' + ''.join(f'- {b}\n' for b in bullets)


class Carried(Base):
    def line(self, bullet):
        self.runs(self.alpha, (MONDAY - 3600, run_with(bullet)))
        return self.block(self.compute())['lignes'][0]

    def test_the_suffixes_are_read(self):
        self.assertEqual(self.p.decouper_puce_meta(f'Valider le devis (reçu le 2026-11-18) (échéance 2026-11-23, lue dans le mail) {MAILLIEN}'),
                         ('Valider le devis', '2026-11-23', 'https://mail.google.com/mail/u/0/#inbox/abc',
                          {'recu': '2026-11-18', 'echeance_mode': 'lue'}))
        self.assertEqual(self.p.decouper_puce_meta('Valider (échéance 2026-11-23, calculée : 5 jours ouvrés après réception)')[3],
                         {'echeance_mode': 'calculee', 'echeance_regle': '5 jours ouvrés après réception'})
        self.assertEqual(self.p.decouper_puce_meta('Valider (échéance 2026-11-23)')[3], {})
        self.assertEqual(self.p.decouper_puce_meta('Valider (échéance 2026-11-23, au hasard)')[1:3], ('2026-11-23', ''))
        self.assertEqual(self.p.decouper_puce_meta('Valider (échéance 2026-11-23, au hasard)')[3], {})
        self.assertEqual(self.p.decouper_puce_meta('Valider (reçu le 2026-02-30)')[3], {})

    def test_the_old_signature_is_unchanged(self):
        self.assertEqual(self.p.decouper_puce('Valider (reçu le 2026-11-18) (échéance 2026-11-23, lue)'), ('Valider', '2026-11-23', ''))

    def test_the_line_carries_what_the_bullet_says_and_flags_a_mail(self):
        l = self.line(f'Valider le devis (reçu le 2026-11-18) (échéance 2026-11-23, calculée : 5 jours ouvrés) {MAILLIEN}')
        self.assertEqual((l['mail'], l['recu'], l['echeance'], l['echeance_mode'], l['echeance_regle']),
                         (True, '2026-11-18', '2026-11-23', 'calculee', '5 jours ouvrés'))

    def test_a_bullet_that_says_nothing_leaves_unknowns_never_guesses(self):
        l = self.line(f'Valider le devis (échéance 2026-11-23) {MAILLIEN}')
        self.assertEqual((l['mail'], l['recu'], l['echeance_mode'], l['echeance_regle']), (True, None, '', ''))

    def test_a_slack_line_is_not_a_mail(self):
        self.assertFalse(self.line('Ana te demande le planning ([source](https://x.slack.com/archives/C1/p1))')['mail'])

    def test_a_moved_date_drops_the_old_origin(self):
        self.runs(self.alpha, (MONDAY - 7200, run_with(f'Valider le devis (échéance 2026-11-23, lue dans le mail) {MAILLIEN}')))
        self.compute()
        self.runs(self.alpha, (MONDAY - 3600, run_with(f'Valider le devis (échéance 2026-11-25) {MAILLIEN}')))
        l = self.block(self.compute())['lignes'][0]
        self.assertEqual((l['echeance'], l['echeance_mode']), ('2026-11-25', ''))


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class OnThePage(unittest.TestCase):
    def row(self, **more):
        entree = {'lignes': [], 'outils': ['lignes', 'ouvrir', 'clore'],
                  'liste_projets': liste(a_toi('aaaaaaaaaaa1', 'Valider le devis du client', 'Valider le devis du client avant la fin du mois.',
                                               lien='https://mail.google.com/mail/u/0/#inbox/abc', echeance='2026-11-23', **dict({'mail': True}, **more)))}
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(entree, f)
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return rangee(json.loads(r.stdout)['tableau'], 'Valider le devis du client')

    def test_received_date_on_the_line_and_a_read_due_date_in_the_unfold(self):
        r = self.row(recu='2026-11-18', echeance_mode='lue')
        self.assertIn('avant le 23/11', r)
        self.assertIn('reçu le 18/11', r)
        self.assertIn('<dt>Reçu</dt><dd>reçu le 18/11</dd>', r)
        self.assertIn('<dt>Échéance</dt><dd>23/11 · lue dans le mail</dd>', r)

    def test_a_computed_due_date_gives_its_rule(self):
        r = self.row(recu='2026-11-18', echeance_mode='calculee', echeance_regle='5 jours ouvrés après réception')
        self.assertIn('23/11 · calculée : 5 jours ouvrés après réception', r)

    def test_unknowns_are_said_not_invented(self):
        r = self.row()
        self.assertNotIn('reçu le', r.split('<tr class="detail"')[0])
        self.assertIn('noté le ', r)
        self.assertIn('date de réception inconnue', r)
        self.assertIn("origine de l&#39;échéance inconnue", r.replace("'", '&#39;'))

    def test_the_mail_kind_is_also_read_from_the_link(self):
        r = self.row(recu='2026-11-18', mail=False)
        self.assertIn('reçu le 18/11', r)


if __name__ == '__main__':
    unittest.main()
