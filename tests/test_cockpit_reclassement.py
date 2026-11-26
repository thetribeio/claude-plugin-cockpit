"""Tests: the PM corrects the board's order (PM, 2026-11-17, for him alone at first): python3 -m unittest discover -s tests

1. Switch « reclassement » off (the default): nothing is read, the board and the page are those of 0.2.23, and the
   connector refuses a reclassement.
2. Switch on: his order holds over the computed one while the line is there, for a line of a session (key « r… ») as
   for a request of the ingestion (its own key); the line says « classé par toi »; what he put first never folds into
   « Anciennes ».
3. The connector looks the line up in its own reading, keeps his order in reclassees.json, undoes it on « annuler »,
   and notes each click in reclassements.jsonl: date, key, origin, text, the computed order (impact, raison, effort,
   label or rule) and his.
4. reclassements.py sums the journal up: clicks, direction, by computed reason, rule and origin, the ten latest.
5. The page: one button per line of the main board, « Pas si urgent » in « D'abord », « À faire d'abord » elsewhere;
   the line moves at once and one more click undoes it; none in « Anciennes » nor « En un clic »; none switch off.
Sessions, Studios, people and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

import test_cockpit_exits_and_sort as board_tests
from test_cockpit_projets import Base, FRIDAY, MONDAY

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
SID = 'local_00000000-0000-0000-0000-0000000000d1'


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, SCRIPTS / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def allumer(interne, on=True):
    interne.mkdir(parents=True, exist_ok=True)
    (interne / 'cockpit.json').write_text(json.dumps({'reclassement_tableau': on}), encoding='utf-8')


def classer(interne, **ordre):
    interne.mkdir(parents=True, exist_ok=True)
    (interne / 'reclassees.json').write_text(json.dumps({k: {'vers': v, 'quand': time.time()} for k, v in ordre.items()}),
                                             encoding='utf-8')


class Rules(unittest.TestCase):
    parc = board_tests.parc

    def test_where_the_computed_order_came_from(self):
        r = self.parc.regle_du_calcul
        self.assertEqual(r({'impact': 'fort', 'raison': 'client attend'}, {'impact': 'fort', 'raison': 'client attend'}), 'étiquette')
        self.assertEqual(r({}, {'impact': 'fort', 'raison': 'en retard'}), 'règle : en retard')
        self.assertEqual(r({}, {'impact': 'fort', 'raison': ''}, bloque=True), 'règle : session qui attend')
        self.assertEqual(r({}, {'impact': 'faible', 'raison': 'rangement'}), 'règle : rangement')
        self.assertEqual(r({}, {'impact': 'normal', 'raison': ''}), 'aucune règle')

    def test_his_order_over_the_computed_one(self):
        l = self.parc.appliquer_classement({'impact': 'normal', 'raison': '', 'effort': 'court', 'ancienne': True}, 'dabord')
        self.assertEqual((l['impact'], l['raison'], l['effort'], l['reclassee'], l['ancienne']),
                         ('fort', 'classé par toi', 'court', 'dabord', False))
        l = self.parc.appliquer_classement({'impact': 'fort', 'raison': 'bloqué', 'effort': ''}, 'ensuite')
        self.assertEqual((l['impact'], l['raison']), ('normal', 'classé par toi'))


class BoardLines(unittest.TestCase):
    """The lines of sessions, through the harness of the sort tests."""
    def setUp(self):
        self.b = board_tests.Board('board')
        self.b.setUp()
        self.addCleanup(self.b.doCleanups)
        self.addCleanup(self.b.tearDown)
        self.interne = board_tests.parc.INTERNE

    def lines(self):
        line, KIT = board_tests.line, board_tests.KIT
        fresh = self.b.board([line(1, KIT, 30, title='Production bloquée : que faire ?'), line(2, KIT, 20)])[2]
        return {l['question']: l for l in fresh if l.get('chantier')}

    def test_off_nothing_is_read(self):
        keys = {q: l['retrait'] for q, l in self.lines().items()}
        classer(self.interne, **{keys['Q1']: 'ensuite', keys['Q2']: 'dabord'})
        for on in (None, False):
            if on is not None:
                allumer(self.interne, on)
            lines = self.lines()
            self.assertEqual((lines['Q1']['impact'], lines['Q2']['impact']), ('fort', 'normal'))
            self.assertNotIn('reclassee', lines['Q1'])
            self.assertNotIn('reclassee', board_tests.parc.rang_page(lines['Q1']))
            self.assertNotIn('calcul', board_tests.parc.rang_page(lines['Q1']))

    def test_on_his_order_holds_and_says_so(self):
        keys = {q: l['retrait'] for q, l in self.lines().items()}
        allumer(self.interne)
        classer(self.interne, **{keys['Q1']: 'ensuite', keys['Q2']: 'dabord'})
        lines = self.lines()
        q1, q2 = lines['Q1'], lines['Q2']
        self.assertEqual((q1['impact'], q1['raison'], q1['reclassee']), ('normal', 'classé par toi', 'ensuite'))
        self.assertEqual((q2['impact'], q2['raison'], q2['reclassee']), ('fort', 'classé par toi', 'dabord'))
        self.assertEqual(q1['calcul'], {'impact': 'fort', 'raison': 'bloqué', 'effort': '', 'regle': 'règle : bloqué'})
        page = board_tests.parc.rang_page(q1)
        self.assertEqual((page['reclassee'], page['calcul']), ('ensuite', {'impact': 'fort', 'raison': 'bloqué', 'effort': ''}))

    def test_an_old_order_is_forgotten(self):
        keys = {q: l['retrait'] for q, l in self.lines().items()}
        allumer(self.interne)
        (self.interne / 'reclassees.json').write_text(json.dumps({keys['Q2']: {'vers': 'dabord', 'quand': time.time() - 61 * 86400}}))
        self.assertEqual(self.lines()['Q2']['impact'], 'normal')


def report(*requests):
    return '📬 Alpha · nouveautés\nÀ toi de jouer :\n' + ''.join(f'- {r}\n' for r in requests)


class Requests(Base):
    def lines(self, when=MONDAY):
        return {l['titre']: l for l in self.block(self.compute(when))['lignes']}

    def test_off_the_request_is_as_before(self):
        self.runs(self.alpha, (FRIDAY, report('Caler le point', 'Ana te demande un accès')))
        lines = self.lines()
        classer(self.p.parc.INTERNE, **{lines['Caler le point']['cle']: 'dabord'})
        lines = self.lines()
        self.assertEqual(lines['Caler le point']['impact'], 'normal')
        self.assertNotIn('calcul', lines['Caler le point'])
        self.assertNotIn('reclassee', lines['Caler le point'])

    def test_on_his_order_holds(self):
        self.runs(self.alpha, (FRIDAY, report('Caler le point', 'Ana te demande un accès')))
        lines = self.lines()
        allumer(self.p.parc.INTERNE)
        classer(self.p.parc.INTERNE, **{lines['Caler le point']['cle']: 'dabord', lines['Ana te demande un accès']['cle']: 'ensuite'})
        lines = self.lines()
        c, a = lines['Caler le point'], lines['Ana te demande un accès']
        self.assertEqual((c['impact'], c['raison'], c['reclassee']), ('fort', 'classé par toi', 'dabord'))
        self.assertEqual(c['calcul']['regle'], 'aucune règle')
        self.assertEqual((a['impact'], a['reclassee'], a['calcul']['raison'], a['calcul']['regle']),
                         ('normal', 'ensuite', 'Ana attend', 'règle : Ana attend'))

    def test_what_he_put_first_never_folds_into_anciennes(self):
        self.runs(self.alpha, (FRIDAY, report('Caler le point')))
        cle = self.lines()['Caler le point']['cle']
        later = MONDAY + 10 * 86400
        self.assertTrue(self.lines(later)['Caler le point']['ancienne'])
        allumer(self.p.parc.INTERNE)
        classer(self.p.parc.INTERNE, **{cle: 'dabord'})
        self.assertFalse(self.lines(later)['Caler le point']['ancienne'])


class Connector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.interne = pathlib.Path(self.tmp.name) / 'Mon Studio' / '.parc'
        self.m = charger('mcp_reclassement', 'mcp_mon_studio.py')
        self.m.charger_parc()
        saved = self.m.parc.INTERNE
        self.m.parc.INTERNE = self.interne
        self.addCleanup(setattr, self.m.parc, 'INTERNE', saved)
        self.m.lignes = lambda: {}   # a fresh reading that shows nothing more
        e = {'tableau': [{'retrait': 'r0123456789ab', 'studio': 'Alpha', 'complet': 'Q3 · Production bloquée : que faire ?',
                          'calcul': {'impact': 'fort', 'raison': 'bloqué', 'effort': '', 'regle': 'règle : bloqué'}}]}
        projets = {'projets': [{'nom': 'Alpha', 'lignes': [
            {'cle': 'abcdef012345', 'type': 'a_toi', 'texte': 'Caler le point',
             'calcul': {'impact': 'normal', 'raison': '', 'effort': '', 'regle': 'aucune règle'}},
            {'cle': 'fedcba543210', 'type': 'entree', 'titre': 'Une entrée'}]}]}
        self.lus = self.m.a_reclasser(e, projets)
        self.m._reclassables.update(t=time.time(), lignes=self.lus)

    def journal(self):
        return [json.loads(l) for l in (self.interne / 'reclassements.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_the_lines_it_may_move(self):
        self.assertEqual(sorted(self.lus), ['abcdef012345', 'r0123456789ab'])   # never an entry, only requests
        self.assertEqual(self.lus['abcdef012345']['origine'], 'ingestion')
        self.assertEqual(self.lus['r0123456789ab']['origine'], 'session')

    def test_off_it_refuses(self):
        allumer(self.interne, False)
        with self.assertRaises(ValueError):
            self.m.clore({'cle': 'r0123456789ab', 'reclasser': 'ensuite'})
        self.assertFalse((self.interne / 'reclassees.json').exists())
        self.assertFalse((self.interne / 'reclassements.jsonl').exists())

    def test_kept_noted_and_undone(self):
        allumer(self.interne)
        self.assertEqual(self.m.clore({'cle': 'r0123456789ab', 'reclasser': 'ensuite'}), {'cle': 'r0123456789ab', 'reclassee': 'ensuite'})
        self.m._reclassables.update(t=time.time(), lignes=self.lus)
        self.m.clore({'cle': 'abcdef012345', 'reclasser': 'dabord'})
        r = json.loads((self.interne / 'reclassees.json').read_text(encoding='utf-8'))
        self.assertEqual({k: v['vers'] for k, v in r.items()}, {'r0123456789ab': 'ensuite', 'abcdef012345': 'dabord'})
        self.m._reclassables.update(t=time.time(), lignes=self.lus)
        self.assertEqual(self.m.clore({'cle': 'r0123456789ab', 'reclasser': 'annuler'})['reclassee'], '')
        r = json.loads((self.interne / 'reclassees.json').read_text(encoding='utf-8'))
        self.assertEqual(list(r), ['abcdef012345'])
        j = self.journal()
        self.assertEqual([(x['cle'], x['origine'], x['pm'], x['avant']) for x in j],
                         [('r0123456789ab', 'session', 'ensuite', ''), ('abcdef012345', 'ingestion', 'dabord', ''),
                          ('r0123456789ab', 'session', 'annuler', 'ensuite')])
        self.assertEqual(j[0]['texte'], 'Q3 · Production bloquée : que faire ?')
        self.assertEqual(j[0]['calcul'], {'impact': 'fort', 'raison': 'bloqué', 'effort': '', 'regle': 'règle : bloqué'})
        self.assertRegex(j[0]['date'], r'^\d{4}-\d\d-\d\dT')

    def test_unknown_line_or_word(self):
        allumer(self.interne)
        for args in ({'cle': 'rffffffffffff', 'reclasser': 'dabord'}, {'cle': 'r0123456789ab', 'reclasser': 'tout'},
                     {'cle': 'fedcba543210', 'reclasser': 'dabord'}, {'cle': '../x', 'reclasser': 'dabord'}):
            self.m._reclassables.update(t=time.time(), lignes=self.lus)
            with self.assertRaises(ValueError, msg=args):
                self.m.clore(args)

    def test_the_page_learns_the_switch_only_when_on(self):
        schema = next(o for o in self.m.OUTILS if o['name'] == 'clore')['inputSchema']['properties']
        self.assertEqual(schema['reclasser']['enum'], ['dabord', 'ensuite', 'annuler'])


class Summary(unittest.TestCase):
    def setUp(self):
        self.r = charger('reclassements_resume', 'reclassements.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.f = pathlib.Path(self.tmp.name) / 'reclassements.jsonl'

    def write(self, *entrees):
        self.f.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entrees) + 'pas du json\n', encoding='utf-8')

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.r.main(['--fichier', str(self.f), *argv])
        return code, out.getvalue()

    def entree(self, n, cle, origine, pm, impact, raison='', regle='aucune règle'):
        return {'date': f'2026-11-{n:02d}T10:00:00+01:00', 'cle': cle, 'origine': origine, 'studio': 'Alpha',
                'texte': f'Ligne {cle}', 'calcul': {'impact': impact, 'raison': raison, 'effort': '', 'regle': regle}, 'pm': pm}

    def test_empty(self):
        self.assertIn('Aucune correction', self.run_main()[1])

    def test_figures(self):
        self.write(self.entree(1, 'r1', 'session', 'ensuite', 'fort', 'bloqué', 'règle : bloqué'),
                   self.entree(2, 'r2', 'session', 'ensuite', 'fort', 'bloqué', 'règle : bloqué'),
                   self.entree(3, 'a1', 'ingestion', 'dabord', 'normal'),
                   self.entree(4, 'r2', 'session', 'annuler', 'fort', 'bloqué', 'règle : bloqué'))
        code, out = self.run_main('--json')
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual((r['clics'], r['sens'], r['corrections_gardees']), (4, {'ensuite': 2, 'dabord': 1, 'annuler': 1}, 2))
        self.assertEqual(r['par_regle'], [["hors de « D'abord » · règle : bloqué", 1], ["vers « D'abord » · aucune règle", 1]])
        self.assertEqual(r['par_origine'], [["session · hors de « D'abord »", 1], ["ingestion · vers « D'abord »", 1]])
        self.assertEqual([x['texte'] for x in r['dernieres']], ['Ligne r2', 'Ligne a1', 'Ligne r2', 'Ligne r1'])
        texte = self.run_main()[1]
        self.assertIn("4 clics : 1 vers « D'abord », 2 hors de « D'abord », 1 annulées. 2 lignes gardent ton classement.", texte)
        self.assertIn('calculé fort · bloqué', texte)
        self.assertIn('Les dix plus récentes', texte)

    def test_ten_latest_only(self):
        self.write(*[self.entree(i, f'r{i}', 'session', 'dabord', 'normal') for i in range(1, 15)])
        r = json.loads(self.run_main('--json')[1])
        self.assertEqual([x['texte'] for x in r['dernieres']][:2], ['Ligne r14', 'Ligne r13'])
        self.assertEqual(len(r['dernieres']), 10)


def run_page(**entree):
    entree.setdefault('outils', ['lignes', 'projet', 'ouvrir', 'clore', 'lire', 'repondre', 'attentes'])
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(entree, f)
    try:
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def ligne(titre, retrait, **plus):
    return dict({'studio': 'Alpha', 'session': 'Démarrage', 'cle': SID, 'lien': '', 'type': 'decision', 'verbe': 'Répondre',
                 'affiche_titre': titre, 'affiche_suite': '', 'bloque': False, 'proche': False, 'impact': 'normal',
                 'raison': '', 'effort': '', 'hors_studio': False, 'retrait': retrait}, **plus)


def demande(titre, cle, **plus):
    return dict({'cle': cle, 'type': 'a_toi', 'titre': titre, 'texte': titre, 'depuis': int((time.time() - 3600) * 1000),
                 'session': '', 'repli': False, 'echeance': None, 'lien': '', 'dossier': '/x/alpha', 'ancienne': False,
                 'auteur': '', 'canal': '', 'impact': 'normal', 'raison': '', 'effort': ''}, **plus)


LIGNES = [ligne('Production arrêtée', 'r00000000000a', impact='fort', raison='bloqué'), ligne('Question ordinaire', 'r00000000000b'),
          ligne('Archiver cette session', 'r00000000000c', impact='faible', raison='rangement')]
PROJETS = {'projets': [{'nom': 'Alpha', 'dossier': '/x/alpha', 'lignes': [demande('Caler le point', 'b' * 12)]}], 'studios': ['Alpha']}


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def order(self, html, *titres):
        places = [html.find(t) for t in titres]
        self.assertNotIn(-1, places, (titres, places))
        self.assertEqual(places, sorted(places), titres)

    def test_off_no_button(self):
        r = run_page(lignes=LIGNES, liste_projets=PROJETS)
        self.assertNotIn('data-reclasser', r['tableau'] + r['attendre'])
        self.assertNotIn('Pas si urgent', r['tableau'])

    def test_one_button_per_line_that_says_what_it_does(self):
        r = run_page(lignes=LIGNES, liste_projets=PROJETS, reclassement=True)
        t = r['tableau']
        self.assertEqual(t.count('data-reclasser='), 3)
        self.assertIn('data-reclasser="ensuite|r00000000000a"', t)
        self.assertIn('data-reclasser="dabord|r00000000000b"', t)
        self.assertIn('data-reclasser="dabord|' + 'b' * 12 + '"', t)   # a request of the ingestion too
        # An icon each (PM, 2026-11-26: one line for the gestures), its name for screen readers and on hover.
        self.assertEqual(t.count('aria-label="Pas si urgent"'), 1)
        self.assertEqual(t.count('aria-label="À faire d&#39;abord"') + t.count('aria-label="À faire d\'abord"'), 2)
        self.assertIn('data-reclasser="dabord|r00000000000c"', r['attendre'])   # « Peut attendre » is the main board too

    def test_none_in_one_click_nor_anciennes(self):
        clic = ligne('Valide le lien', 'r00000000000d', type='clic', choix=['ok'], question='Q9',
                     detail='Valide ici : https://exemple.org/valider puis ok.')
        r = run_page(lignes=[clic], anciennes=[ligne('Vieille question', 'r00000000000e')], reclassement=True)
        self.assertIn('r00000000000d', r['clics'])
        self.assertNotIn('data-reclasser', r['clics'] + r['anciennes'])

    def test_the_line_moves_at_once_and_one_more_click_undoes_it(self):
        r = run_page(lignes=LIGNES, liste_projets=PROJETS, reclassement=True, cliquer=[['data-reclasser', 'dabord|r00000000000b']])
        self.assertIn(['clore', {'cle': 'r00000000000b', 'reclasser': 'dabord'}], r['appels'])
        t = r['tableau']
        self.order(t, "D'abord <span", 'Question ordinaire', 'Ensuite <span', 'Caler le point')
        self.assertIn('<span class="raison">classé par toi</span>', t)
        self.assertIn('data-reclasser="annuler|r00000000000b"', t)
        self.assertEqual(r['compte'], "2 à faire d'abord au tableau")
        # Out of « D'abord », the line says who put it there.
        r = run_page(lignes=LIGNES, liste_projets=PROJETS, reclassement=True, cliquer=[['data-reclasser', 'ensuite|r00000000000a']])
        self.assertNotIn("D'abord <span", r['tableau'])   # nothing first any more: one list, as in 0.2.23
        self.assertIn('<span class="raison court">classé par toi</span>', r['tableau'])
        self.assertEqual(r['compte'], 'Rien ne presse')

    def test_what_he_put_first_stays_first_however_old(self):
        vieux = int(time.time() * 1000) - 30 * 86400000   # past the 21 days that send a line to « Peut attendre »
        kept = ligne('Vieille question', 'r00000000000f', impact='fort', raison='classé par toi', reclassee='dabord',
                     calcul={'impact': 'normal', 'raison': '', 'effort': ''}, depuis=vieux)
        r = run_page(lignes=[kept, dict(kept, retrait='r000000000010', affiche_titre='Autre vieille', reclassee=None, impact='normal')],
                     reclassement=True)
        self.assertIn('Vieille question', r['tableau'])
        self.assertIn('Autre vieille', r['attendre'])

    def test_undo_a_kept_order(self):
        kept = ligne('Question ordinaire', 'r00000000000b', impact='fort', raison='classé par toi', reclassee='dabord',
                     calcul={'impact': 'normal', 'raison': '', 'effort': ''})
        r = run_page(lignes=[LIGNES[0], kept], reclassement=True)
        self.assertIn('data-reclasser="annuler|r00000000000b"', r['tableau'])
        r = run_page(lignes=[LIGNES[0], kept], reclassement=True, cliquer=[['data-reclasser', 'annuler|r00000000000b']])
        self.assertIn(['clore', {'cle': 'r00000000000b', 'reclasser': 'annuler'}], r['appels'])
        self.order(r['tableau'], "D'abord <span", 'Production arrêtée', 'Ensuite <span', 'Question ordinaire')
        self.assertNotIn('classé par toi', r['tableau'])


if __name__ == '__main__':
    unittest.main()
