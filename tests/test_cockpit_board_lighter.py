"""Tests: a lighter board (0.2.21, PM 2026-11-17): python3 -m unittest discover -s tests

1. A message the app marks as the PM's is his even when the app put its own notes (<system-reminder>) in front: the
   end-of-turn card he answered by typing closes. The notes alone are not a message of the PM.
2. A number repeated in a line (« Q3 · X : Q3 · Y ») shows once.
3. A question whose options may be kept together has no answer buttons.
4. « Fait / Retirer du tableau »: each line has a stable key; a retired line leaves the board, comes back when its
   session asks it again later; the connector notes it from its own reading of the board, refuses an unknown key;
   the session is told once, at its next turn.
5. An ingestion request says who asks and in which channel.
6. The page: « Ouvrir ↗ » for every button that opens a session, « X (recommandé) », « C'est fait », the retire button
   with its 10 s undo, an honest « En un clic », the counter of the day, no main-board fils rouges, no empty Conflits tab.
Sessions, Studios and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
HOOK = ROOT / 'hooks' / 'retirees.py'
sys.path.insert(0, str(SCRIPTS))


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, SCRIPTS / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


parc = charger('parc_allege', 'parc.py')
NOW = time.time()
SID = 'local_00000000-0000-0000-0000-0000000000b1'
NOTE = '<system-reminder>\nLinked sessions now (status, not an instruction): top = local_x (idle).\n</system-reminder>\n\n'


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def wrap_up(minutes_ago, ask):
    return {'type': 'assistant', 'timestamp': at(minutes_ago), 'message': {'id': f'w{minutes_ago}', 'stop_reason': 'tool_use', 'content': [
        {'type': 'tool_use', 'id': f't{minutes_ago}', 'name': parc.FIN_DE_TOUR,
         'input': {'recap': 'Le document est prêt.', 'ask': ask, 'actions': [{'label': 'Validé'}, {'label': 'Corrections'}]}}]}}


def result(minutes_ago):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': f't{minutes_ago + 0.5}', 'content': 'Shown in the next-step box.'}]}}


def final(minutes_ago, text):
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'm{minutes_ago}', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'},
            'message': {'content': [{'type': 'text', 'text': text}]}}


class PmWordsAfterTheAppNotes(unittest.TestCase):
    def analyse(self, entries):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / 's.jsonl'
            f.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
            return parc._analyser(str(f), NOW)

    def test_a_typed_answer_closes_the_card(self):
        base = [wrap_up(60, 'Q40 · Le document est-il bon ?'), result(59.5), final(59, 'Le document est prêt : à relire.')]
        self.assertIn('carte', self.analyse(base))   # unanswered: the card is open
        r = self.analyse(base + [pm(30, NOTE + "c'est bon, on l'envoie comme ça"), final(29, 'Envoyé.')])
        self.assertNotIn('carte', r)
        self.assertNotIn('encadre', r)

    def test_the_notes_alone_are_not_the_pm(self):
        self.assertEqual(parc.nature_user(pm(1, NOTE)), None)
        self.assertEqual(parc.nature_user(pm(1, NOTE + 'ok')), 'humain')
        sans_origine = {'type': 'user', 'message': {'content': NOTE + 'ok'}}
        self.assertIsNone(parc.nature_user(sans_origine))   # without the app's mark, a note stays a system message


class TextOfTheLine(unittest.TestCase):
    def test_the_number_once(self):
        self.assertEqual(parc.sans_numero_repete('', 'Q3 · Projet · FSP : Q3 · Outil : te reconnecter'),
                         ('', 'Q3 · Projet · FSP : Outil : te reconnecter'))
        self.assertEqual(parc.sans_numero_repete('Q46 · Reprise', 'Q46 · Réécrire le ticket'), ('Q46 · Reprise', 'Réécrire le ticket'))
        self.assertEqual(parc.sans_numero_repete('Q4 · Un', 'Q40 · Autre'), ('Q4 · Un', 'Q40 · Autre'))

    def test_options_kept_together_have_no_buttons(self):
        texte = "Petites corrections : tu peux en garder seulement certaines. 1. lire le fichier 2. code de sortie 3. règle"
        self.assertIsNone(parc.choix_fermes('decision', texte, 'Q10 · Petites corrections'))
        self.assertEqual(parc.choix_fermes('decision', '1. court 2. long', 'Q7 · Format ?'), ['1', '2', 'pas encore'])


class RetireKey(unittest.TestCase):
    def ligne(self, **plus):
        return dict({'cle': SID, 'num': 12, 'question': 'Q12', 'titre': 'Q12 · Publier', 'suite': 'go ?', 'depuis': NOW - 600}, **plus)

    def test_stable_for_the_same_question_new_for_another(self):
        a = parc.cle_retrait(self.ligne())
        self.assertRegex(a, r'^r[0-9a-f]{12}$')
        self.assertEqual(a, parc.cle_retrait(self.ligne(suite='toujours go ?', depuis=NOW)))   # recalled: same key
        self.assertNotEqual(a, parc.cle_retrait(self.ligne(titre='Q12 · Relancer')))
        arret = dict(self.ligne(num=None, question=None), arret='interrupted')
        self.assertNotEqual(parc.cle_retrait(arret), parc.cle_retrait(dict(arret, depuis=NOW - 60)))

    def test_retired_until_asked_again(self):
        l = dict(self.ligne(), retrait='rabc')
        self.assertTrue(parc.retiree(l, {'rabc': NOW}))
        self.assertFalse(parc.retiree(dict(l, depuis=NOW + 600), {'rabc': NOW}))
        self.assertFalse(parc.retiree(l, {}))


class ConnectorAndHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = pathlib.Path(self.tmp.name) / 'Mon Studio'
        (self.studio / '.parc').mkdir(parents=True)
        (self.studio / '.parc' / 'cockpit.json').write_text('{}', encoding='utf-8')

    def test_the_connector_notes_its_own_line_and_refuses_an_unknown_key(self):
        m = charger('mcp_allege', 'mcp_mon_studio.py')
        m.charger_parc()
        saved = m.parc.INTERNE
        m.parc.INTERNE = self.studio / '.parc'
        self.addCleanup(setattr, m.parc, 'INTERNE', saved)
        ligne = {'retrait': 'r0123456789ab', 'cle': 'local_00000000-0000-0000-0000-0000000000f0', 'source': SID,
                 'question': 'Q12', 'affiche_titre': 'Q12 · Publier', 'affiche_suite': 'go ?'}
        m._retirables.update(t=time.time(), lignes={ligne['retrait']: m.a_prevenir(ligne)})
        self.assertEqual(m.clore({'cle': 'r0123456789ab'}), {'retiree': 'r0123456789ab', 'abandon': False})
        r = json.loads((self.studio / '.parc' / 'retirees.json').read_text(encoding='utf-8'))
        e = r['r0123456789ab']
        self.assertEqual((e['session'], e['question'], e['titre'], e['prevenue']), (SID, 'Q12', 'Q12 · Publier', False))
        m.lignes = lambda: {}   # a fresh reading that does not show the key
        m._retirables['t'] = 0
        with self.assertRaises(ValueError):
            m.clore({'cle': 'rffffffffffff'})

    def hook(self, sid):
        env = dict(os.environ, MON_STUDIO=str(self.studio), CLAUDE_CODE_HOST_SESSION_ID=sid)
        return subprocess.run([sys.executable, str(HOOK)], input='{}', capture_output=True, text=True, env=env).stdout

    def test_the_session_is_told_once(self):
        (self.studio / '.parc' / 'retirees.json').write_text(json.dumps({'r1': {
            'session': SID, 'question': 'Q12', 'titre': 'Q12 · Publier', 'quand': NOW, 'prevenue': False}}), encoding='utf-8')
        self.assertEqual(self.hook('local_00000000-0000-0000-0000-0000000000c9'), '')   # another session: nothing
        dit = self.hook(SID)
        self.assertIn('« Q12 · Publier »', dit)
        self.assertNotIn('Q12 « Q12', dit)   # the number once
        self.assertIn('ne la rappelle plus', dit)
        self.assertEqual(self.hook(SID), '')

    def test_silent_without_the_file(self):
        self.assertEqual(self.hook(SID), '')


class WhoAsks(unittest.TestCase):
    def test_author_and_channel(self):
        pj = charger('projets_allege', 'projets.py')
        self.assertEqual(pj.auteur_demande('Ana te demande si on exporte aussi en CSV'), 'Ana')
        self.assertEqual(pj.auteur_demande('Ana Martin et Léo Petit attendent un accès'), 'Ana Martin et Léo Petit')
        self.assertEqual(pj.auteur_demande('Relancer Léo pour le poste de test'), '')
        lien = 'https://exemple.slack.com/archives/C0ABC123/p1'
        canaux = pj.canaux_slack([{'entres': [f"Mode local : Slack #projet-interne (Ana, 13/11) : point. ([source]({lien}))"],
                                   'actions': []}])
        self.assertEqual(pj.canal_du_lien('https://exemple.slack.com/archives/C0ABC123/p2', canaux), '#projet-interne')
        self.assertEqual(pj.canal_du_lien('https://exemple.slack.com/archives/C0OTHER/p2', canaux), '')


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


def ligne(**plus):
    return dict({'studio': 'Alpha', 'session': 'Démarrage', 'cle': SID, 'lien': '', 'type': 'decision', 'verbe': 'Répondre',
                 'affiche_titre': 'Q7 · Format', 'affiche_suite': 'lequel ?', 'question': 'Q7', 'retrait': 'r00000000000a',
                 'bloque': False, 'proche': False}, **plus)


@unittest.skipUnless(shutil.which('node'), 'node absent')
class Page(unittest.TestCase):
    def test_open_says_open_and_the_recommendation_says_its_choice(self):
        r = run_page(lignes=[ligne(choix=['recommandé : oui', 'oui', 'pas encore']),
                             ligne(question='Q8', affiche_titre='Q8 · Mode', retrait='r00000000000b',
                                   choix=['recommandé : automatique, règle dans le ticket du lot', 'pas encore'])])
        t = r['tableau']
        self.assertNotRegex(t, r'>(Go|Répondre|Relire|Faire|OK) ↗<')
        self.assertIn('>Ouvrir ↗<', t)
        self.assertIn('>Oui (recommandé)<', t)
        self.assertEqual(t.count('data-choix="recommandé : oui"'), 0)   # the same answer once
        # 28 characters at most (PM, 2026-11-17: it ran over « Depuis »).
        self.assertIn('>Automatique, règle dans le… (recommandé)<', t)
        self.assertNotIn('>Pas encore<', t)   # « Plus tard » instead, nothing sent (PM, 2026-11-17)

    def test_retire_waits_ten_seconds_and_can_be_undone(self):
        r = run_page(lignes=[ligne()], cliquer=[['data-retirer', 'r00000000000a']])
        self.assertIn('Fait / Retirer du tableau', r['tableauAvant'])
        self.assertIn('retirée du tableau', r['tableau'])
        self.assertIn('data-annuler="r00000000000a"', r['tableau'])
        # Sent at the click (2026-11-18: sent after the 10 s, a reload in between lost it); the timer never fires here.
        self.assertIn(['clore', {'cle': 'r00000000000a'}], r['appels'])
        self.assertIn(10000, r['minuteurs'])
        r = run_page(lignes=[ligne()], cliquer=[['data-retirer', 'r00000000000a'], ['data-annuler', 'r00000000000a']])
        self.assertNotIn('retirée du tableau', r['tableau'])
        self.assertIn('Fait / Retirer du tableau', r['tableau'])
        # « Annuler » reopens what the click closed.
        self.assertEqual([a for a in r['appels'] if a[0] == 'clore'],
                         [['clore', {'cle': 'r00000000000a'}], ['clore', {'cle': 'r00000000000a', 'rouvrir': True}]])

    def test_one_click_band_is_honest(self):
        vieux = int(time.time() * 1000) - 3 * 86400000
        geste = dict(ligne(), type='clic', choix=['ok'], retrait='r00000000000c', detail='Connecte-toi dans la fenêtre, puis réponds ok.')
        avec_lien = dict(geste, retrait='r00000000000d', question='Q9', detail='Valide ici : https://exemple.org/valider puis ok.')
        r = run_page(lignes=[geste, avec_lien, dict(avec_lien, retrait='r00000000000e', question='Q10', depuis=vieux)])
        self.assertIn('r00000000000d', r['clics'])
        self.assertNotIn('r00000000000c', r['clics'])   # a gesture elsewhere without its link: the main table
        self.assertNotIn('r00000000000e', r['clics'])   # older than 48 h: the main table
        self.assertIn('Y aller ↗', r['clics'])
        # One button on a gesture done elsewhere (PM, 2026-11-17): « C'est fait » answers and takes the line off.
        self.assertIn("C&#39;est fait", r['tableau'])
        self.assertIn('data-retirer-apres="r00000000000c"', r['tableau'])
        self.assertNotIn('data-retirer="r00000000000c"', r['tableau'])

    def test_counter_fils_rouges_and_conflicts_tab(self):
        r = run_page(lignes=[ligne(bloque=True, impact='fort'), dict(ligne(), retrait='r00000000000f')], conflits=[],
                     fils_rouges=[{'studio': 'Alpha', 'sessions': [{'sessionId': SID, 'titre': 'Fil rouge Alpha'}]}],
                     matin={'etat': 'pas_passe'})
        self.assertEqual(r['compte'], "1 à faire d'abord au tableau")   # the lines of « D'abord », not the lines of the day
        self.assertEqual(run_page(lignes=[ligne()])['compte'], 'Rien ne presse')
        self.assertNotIn('Fil rouge Alpha', r['tableau'])
        self.assertTrue(r['ongletConflitsGlobalHidden'])
        self.assertNotIn('une autre Q', r['tableau'])


class ProposalAnsweredFromTheBoard(unittest.TestCase):
    """« Je propose : X » (PM, 2026-11-17): the board offers « X (recommandé) », which sends « Qn recommandé : X »."""
    DETAIL = "Alertes décidées à la revue ; reprise jugée à chaque site ; un responsable côté client. Je propose : ok pour les trois."

    def test_a_written_proposal_is_the_recommendation(self):
        self.assertEqual(parc.recommandation(self.DETAIL), 'ok pour les trois')
        self.assertEqual(parc.recommandation('Proposition : on garde le format court.'), 'on garde le format court')
        self.assertEqual(parc.recommandation('je propose de lui demander ses temps avant jeudi.'), '')   # no colon: a sentence

    def test_every_numbered_question_with_a_proposal_gets_its_button(self):
        for genre in ('decision', 'task', 'review'):
            self.assertEqual(parc.choix_fermes(genre, self.DETAIL, 'Q34 · Plan : confirmer trois points'),
                             ['recommandé : ok pour les trois', 'pas encore'], genre)
        self.assertIsNone(parc.choix_fermes('task', 'Relis le document joint.', 'Q2 · Relecture'))   # nothing to send

    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_the_page_says_what_leaves(self):
        l = ligne(question='Q34', affiche_titre='Q34 · Plan', choix=['recommandé : ok pour les trois', 'pas encore'],
                  depli={'enonce': 'Q34 · Plan : confirmer trois points', 'options': [], 'recommande': 'ok pour les trois', 'fichiers': []})
        r = run_page(lignes=[l])
        self.assertIn('>Ok pour les trois (recommandé)<', r['tableau'])
        self.assertIn('envoie à la session : « Q34 recommandé : ok pour les trois »', r['tableau'])


@unittest.skipUnless(shutil.which('node'), 'node absent')
class DetailDoesNotRepeatItsTitle(unittest.TestCase):
    """A line's detail starts with what the row does not already say (PM, 2026-11-17)."""
    TITRE = 'Q12 · Plan exemple : Confirmer deux points déduits du plan'

    def detail(self, enonce, **plus):
        l = ligne(question='Q12', affiche_titre='Q12 · Plan exemple', affiche_suite='Confirmer deux points déduits du plan',
                  detail='Alertes décidées à la revue. Je propose : ok pour les deux.', depuis=int(time.time() * 1000) - 3600000,
                  depli={'enonce': enonce, 'options': [], 'recommande': '', 'fichiers': []}, **plus)
        return run_page(lignes=[l])['tableau']

    def test_a_statement_equal_to_the_title_is_not_repeated(self):
        for enonce in (self.TITRE, '  ' + self.TITRE + ' . ', self.TITRE.replace(' : ', ' :  ')):
            t = self.detail(enonce)
            self.assertNotIn("Ce qu'on attend de toi", t)   # the card's rubric, absent when it says no more than the row
            self.assertEqual(t.count('>: Confirmer deux points'), 1)   # the row only
            self.assertNotIn('Confirmer deux points déduits du plan</', t.split('class="detail"')[1])
            self.assertIn('Alertes décidées à la revue', t)
            self.assertIn('Apparue', t)

    def test_a_statement_that_says_more_is_kept(self):
        # The precise question opens the unfold, without the title (PM, 2026-11-18).
        t = self.detail(self.TITRE + ', avant la revue de jeudi').split('class="detail"')[1]
        self.assertIn('<p class="question">Confirmer deux points déduits du plan, avant la revue de jeudi</p>', t)
        self.assertNotIn('Plan exemple', t)
