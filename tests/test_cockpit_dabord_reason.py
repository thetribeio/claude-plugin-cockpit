"""Tests: every line of « D'abord » says why it is there (PM, 2026-11-19).

The rule that puts a line in « D'abord » (parc.priorite, impact « fort ») left the reason empty for a close due date, a
session that waits and a session that stopped (« the line already says it »), so those lines showed no chip while
others showed « sécurité » or « Ana attend ». The same reason that decided now rides on the line, one chip, whatever
the rule, and the page falls back to what the line carries when a reason is missing. People and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import pathlib
import re
import shutil
import time
import unittest

from test_cockpit_impact_effort import demande, ligne, run_page

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc_raison', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
NOW = time.time()
DAY = 86400


class Reason(unittest.TestCase):
    def p(self, texte, **plus):
        return parc.priorite(texte, NOW, **plus)

    def test_every_strong_line_has_a_reason(self):
        cas = [self.p('Envoyer le devis', echeance=NOW - 3 * DAY),
               self.p('Envoyer le devis', echeance=NOW + DAY, proche=True),
               self.p('Q2 · Format', bloque=True),
               self.p('Session arrêtée', arret='interrupted'),
               self.p('Session arrêtée', arret='authorization', bloque=True),
               self.p('Session arrêtée', arret='error'),
               self.p('Des identifiants sont en clair'), self.p('À faire sans délai'), self.p('Production bloquée'),
               self.p('Ana te demande un accès', demande=True),
               self.p('Q1 · Budget', dit={'impact': 'fort', 'raison': 'client attend'})]
        for c in cas:
            self.assertEqual(c['impact'], 'fort', c)
            self.assertTrue(c['raison'], c)

    def test_the_wording(self):
        jour = dt.date.fromtimestamp(NOW + DAY).strftime('%d/%m')
        self.assertEqual(self.p('Envoyer', echeance=NOW + DAY, proche=True)['raison'], f'échéance {jour}')
        self.assertEqual(self.p('Envoyer', echeance=NOW - 3 * DAY)['raison'], 'en retard')
        self.assertEqual(self.p('Q2 · Format', bloque=True)['raison'], 'une session attend')
        self.assertEqual(self.p('Arrêtée', arret='interrupted')['raison'], 'arrêtée en plein travail')
        self.assertEqual(self.p('Arrêtée', arret='authorization', bloque=True)['raison'], 'attend une autorisation')
        self.assertEqual(self.p('Arrêtée', arret='error')['raison'], 'arrêtée sur une erreur')
        self.assertEqual(self.p('Arrêtée', arret='refused')['raison'], 'arrêtée sur une autorisation')

    def test_the_reason_that_decided_wins_over_the_words(self):
        # A stopped session whose text also says « en clair » is in « D'abord » because it stopped.
        self.assertEqual(self.p('Arrêtée, un mot de passe en clair', arret='interrupted')['raison'], 'arrêtée en plein travail')

    def test_a_scheduled_pass_stopped_on_a_refused_authorization_says_so(self):
        # The line's text says « arrêtée sur une autorisation »: its chip says the same, not « en plein travail ».
        a = {'id': 'tache-x', 'nom': 'Passage', 'ts': NOW - 600, 'cwd': '/studios/Alpha', 'lien': 'local_task', 'detail': '',
             'arret': {'quoi': 'refused', 'outil': 'Bash', 'depuis': NOW - 600}}
        l, = [x for x in parc.lignes_et_anciennes([], [], [a], 7, NOW, {})[0] if x.get('tache')]
        self.assertEqual((l['impact'], l['raison']), ('fort', 'arrêtée sur une autorisation'))
        self.assertEqual(l['arret'], 'interrupted')

    def test_a_normal_line_has_none(self):
        self.assertEqual(self.p('Question ordinaire')['raison'], '')


def chips(html):
    """The reason chips of each row of the table, in order."""
    out = []
    for row in re.split(r'(?=<tr class="(?:nouveau-studio)?[^"]*"[^>]*data-deplier|<tr class="nouveau-studio|<tr>)', html):
        m = re.search(r'<td class="action">(.*?)</td>', row, re.S)
        if m:
            out.append(re.findall(r'<span class="raison">(.*?)</span>', m.group(1)))
    return out


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class OnThePage(unittest.TestCase):
    def dabord(self, **entree):
        out = run_page(**entree)
        t = out['tableau']
        return t[t.index("D'abord"):t.index('Ensuite') if 'Ensuite' in t else len(t)]

    def test_a_chip_on_every_line_of_dabord_even_without_the_reason_in_the_data(self):
        # Lines as an older connector served them: strong impact, empty reason.
        lignes = [ligne('Session sans raison', impact='fort', arret='interrupted', cle='local_00000000-0000-0000-0000-0000000000c1'),
                  ligne('Autorisation sans raison', impact='fort', arret='authorization', bloque=True, cle='local_00000000-0000-0000-0000-0000000000c2'),
                  ligne('Session qui attend', impact='fort', bloque=True, cle='local_00000000-0000-0000-0000-0000000000c3'),
                  ligne('Avec raison', impact='fort', raison='sécurité', cle='local_00000000-0000-0000-0000-0000000000c4')]
        h = self.dabord(lignes=lignes)
        c = chips(h)
        self.assertEqual(len(c), 4)
        self.assertTrue(all(len(x) == 1 and x[0] for x in c), c)
        self.assertEqual(sorted(x[0] for x in c), sorted(['arrêtée en plein travail', 'attend une autorisation', 'une session attend', 'sécurité']))

    def test_a_request_with_a_close_due_date_shows_it_as_its_reason(self):
        jour = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        d = demande('Répondre à Ana avant jeudi', impact='fort', raison='', ech_iso=jour,
                    echeance=jour)
        out = run_page(lignes=[], liste_projets={'genere': 0, 'page': None, 'studios': [], 'projets': [
            {'nom': 'Alpha', 'dossier': '/x/alpha', 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': [d]}]})
        c = chips(out['tableau'])
        self.assertEqual(len(c), 1)
        # The ingestion does not say where this due date comes from (no `echeance_mode`): the chip says so (PM, Q6, 2026-11-25).
        self.assertRegex(c[0][0], r'^échéance \d\d/\d\d · origine inconnue$')
        d['echeance_mode'] = 'lue'
        out = run_page(lignes=[], liste_projets={'genere': 0, 'page': None, 'studios': [], 'projets': [
            {'nom': 'Alpha', 'dossier': '/x/alpha', 'role': 'pm', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': [d]}]})
        self.assertRegex(chips(out['tableau'])[0][0], r'^échéance \d\d/\d\d$')

    def test_the_session_attend_tail_is_not_said_twice(self):
        out = run_page(lignes=[ligne('Session qui attend', impact='fort', raison='une session attend', bloque=True)])
        self.assertEqual(out['tableau'].count('une session attend'), 1)


if __name__ == '__main__':
    unittest.main()
