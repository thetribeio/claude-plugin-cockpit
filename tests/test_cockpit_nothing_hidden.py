"""Tests of « no waiting demand leaves Mon Studio without proof »: python3 -m unittest discover -s tests

Q130 (PM, 2026-10-20): a question of a foreman's board answered in its own session leaves Mon Studio only on strong
proof: the PM's message cites its number, or he answered the menu that carried it (the session that settles it with
question.py removes it from the mirror). Otherwise the line stays, « réglée dans la session, à confirmer », the words
of the foreman's board. The board still gets every settled number (field « reglees ») for its « À confirmer » group.
Q131 (PM, 2026-10-20): a demand of a read session whose last message is more than seven days old no longer drops out
of the screen: it goes to « Anciennes : à traiter ou à archiver », under the fresh ones, with its own count.
Two cases of the line check (2026-10-20): a sentence that recalls numbered questions outside « Encore ouvert » gives
one line per question, as a recall; a sentence that says it is not for the PM (« jamais à toi ») gives none.
Transcripts, mirrors and session cards here are synthetic; the real sentences are kept word for word."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parc', ROOT / 'skills' / 'mon-studio' / 'scripts' / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN, KIT, OLD, ALONE = 'local_foreman', 'local_kit', 'local_old', 'local_alone'
STUDIO_CWD, OTHER_CWD = '/studios/Studio-Essai', '/studios/Studio-Autre'
NOW = time.time()


def at(minutes_ago):
    return dt.datetime.fromtimestamp(NOW - minutes_ago * 60, dt.timezone.utc).isoformat()


def final(minutes_ago, text):
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'm{minutes_ago}', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(minutes_ago, text):
    return {'type': 'user', 'timestamp': at(minutes_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


def tool(minutes_ago):
    return [{'type': 'assistant', 'timestamp': at(minutes_ago),
             'message': {'id': f't{minutes_ago}', 'stop_reason': 'tool_use',
                         'content': [{'type': 'tool_use', 'id': f'b{minutes_ago}', 'name': 'Bash', 'input': {}}]}},
            {'type': 'user', 'timestamp': at(minutes_ago),
             'message': {'content': [{'type': 'tool_result', 'tool_use_id': f'b{minutes_ago}', 'content': 'ok'}]}}]


def menu(minutes_ago, question):
    entry = {'questions': [{'question': question, 'options': [{'label': 'Oui (Recommandé)'}, {'label': 'Non'}]}]}
    return {'type': 'assistant', 'timestamp': at(minutes_ago),
            'message': {'id': f'q{minutes_ago}', 'stop_reason': 'tool_use',
                        'content': [{'type': 'tool_use', 'id': f'u{minutes_ago}', 'name': 'AskUserQuestion', 'input': entry}]}}


def menu_answer(menu_minutes_ago, minutes_ago):
    return {'type': 'user', 'timestamp': at(minutes_ago),
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': f'u{menu_minutes_ago}',
                                     'content': 'User has answered your questions: Oui'}]}}


def card(sid, title, cwd=STUDIO_CWD):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None, 'tache': None}


CARDS = [card(FOREMAN, 'Contremaître'), card(KIT, 'Kit A'), card(OLD, 'Vieille session', OTHER_CWD),
         card(ALONE, 'Seule', OTHER_CWD)]
ASK = "Le script est prêt.\n\n## À trancher\n- **Q112 · Recoller le script v9** dans les autres Sheets ? Je recommande oui."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _studio = unittest.mock.patch.object(parc, 'est_un_studio', lambda d: True)   # synthetic folders: no manifest on disk
        _studio.start()
        self.addCleanup(_studio.stop)
        self.saved = parc.CHANTIERS
        parc.CHANTIERS = pathlib.Path(self.tmp.name) / 'chantiers'
        parc.CHANTIERS.mkdir()

    def tearDown(self):
        parc.CHANTIERS = self.saved
        self.tmp.cleanup()

    def session(self, sid, entries, cwd=STUDIO_CWD, unread=False, title=None):
        """A session as construire() builds it, its transcript written on disk."""
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(card(sid, title or 'Session ' + sid, cwd), chemin=str(path), derniere=r['depuis'], non_lue=unread, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def foreman(self, waits):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(300), 'attentes': list(waits)}))

    def screen(self, sessions):
        e = {'genere': NOW, 'pastilles_lues': True, 'fils_rouges': [], 'sans_action': []}
        e['tableau'], e['anciennes'] = parc.lignes_et_anciennes(sessions, CARDS, [], 7, NOW, {})
        return e


class StrongProof(Base):
    """Q130: the line leaves only on strong proof; otherwise it stays, « à confirmer »."""
    Q112 = {'type': 'task', 'titre': 'Q112 · Recoller le script v9 dans les autres Sheets', 'source': KIT,
            'depuis': at(60), 'ou': 'Kit suivi temps passé'}

    def run_case(self, entries, waits=None):
        self.foreman(waits or [self.Q112])
        e = self.screen([self.session(KIT, entries)])
        rows = [l for l in e['tableau'] if l.get('question') == 'Q112']
        return rows, parc.reglees([self.session(KIT, entries)], parc.chantiers_actifs(CARDS), {})

    def test_hidden_when_the_pm_cites_its_number(self):
        for words in ('Q112 : oui, vas-y', 'q 112 ok', 'pour la 112, oui'):
            with self.subTest(words=words):
                rows, settled = self.run_case([final(60, ASK), pm(50, words), *tool(49)])
                self.assertEqual(rows, [])
                self.assertEqual(settled, {FOREMAN: {112: parc.FORTE}})

    def test_hidden_when_the_pm_answers_the_menu_that_carried_it(self):
        entries = [menu(60, 'Q112 · Je recolle le script v9 dans les autres Sheets ?'), menu_answer(60, 50), *tool(49)]
        rows, settled = self.run_case(entries)
        self.assertEqual((rows, settled), ([], {FOREMAN: {112: parc.FORTE}}))
        # A menu without its number, dated with the question on the board, carried it too.
        rows, settled = self.run_case([menu(60, 'Je recolle le script v9 ?'), menu_answer(60, 50), *tool(49)])
        self.assertEqual((rows, settled), ([], {FOREMAN: {112: parc.FORTE}}))

    def test_settled_by_its_session_is_gone_from_the_mirror(self):
        # question.py settle removes the question from the mirror: nothing left to show, nothing to confirm.
        rows, settled = self.run_case([final(60, ASK), pm(50, 'Q112 : fait'), *tool(49)],
                                      waits=[dict(self.Q112, titre='Q113 · Autre chose')])
        self.assertEqual((rows, settled), ([], {}))

    def test_weak_presumption_stays_a_plain_open_line(self):
        # The real case of Q112 (20/10): the PM wrote to the session on another subject, and it went to work. The line
        # stays, as a plain open line, with no « à confirmer » (PM, 2026-10-20: « ça fait tellement pas pro »).
        rows, settled = self.run_case([final(60, ASK), pm(50, 'Au fait, tu peux regarder le Sheet de Studio G ?'), *tool(49)])
        l, = rows
        self.assertFalse(l['reglee'])
        self.assertEqual(settled, {FOREMAN: {112: parc.A_CONFIRMER}})
        # The board still gets it, for its « À confirmer » group.
        self.foreman([self.Q112])
        self.assertEqual(parc.reglees([self.session(KIT, [final(60, ASK), pm(50, 'Autre sujet'), *tool(49)])],
                                      parc.chantiers_actifs(CARDS), {}), {FOREMAN: {112: parc.A_CONFIRMER}})

    def test_not_settled_stays_a_plain_line(self):
        rows, settled = self.run_case([final(60, ASK)])
        l, = rows
        self.assertFalse(l['reglee'])
        self.assertEqual(settled, {})

    def test_to_confirm_goes_under_the_open_lines_of_its_studio(self):
        open_go = {'type': 'go', 'titre': 'Q120 · Go pour publier', 'depuis': at(10)}
        self.foreman([self.Q112, open_go])
        e = self.screen([self.session(KIT, [final(60, ASK), pm(50, 'Autre sujet'), *tool(49)])])
        self.assertEqual([l['question'] for l in e['tableau']], ['Q120', 'Q112'])

    def test_screens_show_no_to_confirm_mention(self):
        self.foreman([self.Q112])
        e = self.screen([self.session(KIT, [final(60, ASK), pm(50, 'Autre sujet'), *tool(49)])])
        page = parc.pour_la_page(e)['lignes']
        l, = [x for x in page if x['question'] == 'Q112']
        self.assertFalse(l['reglee'])
        self.assertNotIn('à confirmer', parc.rendre_md(e))

class CitedNumbers(unittest.TestCase):
    def test_what_cites_a_question(self):
        cases = {'Q112 : oui': [112], 'q 112 ok': [112], 'pour la 112, oui': [112], 'Pour la deux, je prends 1': [2],
                 'sur la dix-sept : non': [17], 'la question 45 est réglée': [45], 'Q130 et Q131 : ok': [130, 131],
                 'Q130 et 131 : ok': [130], 'Drive et Slack': [], '1': [], 'Il reste 3,5 JH': [],
                 'pour la 2e fois': [], 'Q3,5': []}
        for text, nums in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parc.numeros_cites(text), nums)

    def test_cited_then_asked_again_then_answered_without_it(self):
        # The PM cited Q61 to ask back; the session asked it again; his next answer has no number: to confirm.
        ask = "## À trancher\n- **Q61 · Photos :** Drive seul, ou Drive et Slack ?"
        sv = parc.suivi_session([final(60, ask), pm(55, "Q61 : c'était quoi le dossier ?"),
                                 final(54, "Le dossier de l'équipe.\n\nEncore ouvert : Q61"), pm(50, 'Drive'), *tool(49)])
        self.assertEqual(parc.reglee_dans_session({'titre': 'Q61 · Photos', 'depuis': at(60)}, [], sv), parc.A_CONFIRMER)


class OldDemands(Base):
    """Q131: a demand older than seven days goes to « Anciennes », never out of the screen."""
    def old(self, unread=False):
        entries = [final(10 * 24 * 60, "Tu veux que je lance cette migration maintenant, ou tu préfères d'abord vérifier ?")]
        return self.session(OLD, entries, cwd=OTHER_CWD, unread=unread, title='Prestataires stocks et coûts')

    def fresh(self):
        return self.session(ALONE, [final(30, 'Je publie la page ?')], cwd='/studios/Studio-Neuf', title='Seule')

    def test_old_demand_in_its_own_group_not_in_the_fresh_ones(self):
        e = self.screen([self.old(), self.fresh()])
        self.assertEqual([l['cle'] for l in e['tableau']], [ALONE])
        l, = e['anciennes']
        # Not numbered, no « Rien à faire » (2026-10-26, Q37): kept, with the neutral verb, never a guessed « Go ».
        self.assertEqual((l['studio'], l['session'], l['ouvrir'], l['verbe']),
                         ('Autre', 'Prestataires stocks et coûts', OLD, 'Vérifier'))
        self.assertIn('lance cette migration', l['complet'])
        page = parc.pour_la_page(e)
        self.assertEqual(([x['cle'] for x in page['lignes']], [x['cle'] for x in page['anciennes']]), ([ALONE], [OLD]))

    def test_unread_old_session_stays_fresh(self):
        e = self.screen([self.old(unread=True)])
        self.assertEqual(([l['cle'] for l in e['tableau']], e['anciennes']), ([OLD], []))

    def test_only_old_demands(self):
        e = self.screen([self.old()])
        md = parc.rendre_md(e)
        self.assertIn('0 en attente', md)
        self.assertIn('**Anciennes : à traiter ou à archiver** · 1', md)

    def test_markdown(self):
        md = parc.rendre_md(self.screen([self.old(), self.fresh()]))
        self.assertIn('1 en attente dans 1 Studio(s)', md)
        fresh, old = md.split('**Anciennes : à traiter ou à archiver** · 1')
        self.assertIn(f'| Neuf | [Seule](#{ALONE}) |', fresh)
        self.assertIn(f'| Autre | [Prestataires stocks et coûts](#{OLD}) | Tu veux que je lance cette migration', old)
        self.assertIn('| 10 j |', old)

    def test_pinned_page_has_the_group(self):
        page = (ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html').read_text(encoding='utf-8')
        # Collapsed by default (PM, Q24 of 2026-11-04): its heading is the button that unfolds it.
        self.assertIn('aria-expanded="false" aria-controls="anciennes"><span class="fleche">▸</span>Anciennes : à traiter ou à archiver '
                      '<span class="muted" id="anciennes-n"></span></button></h2>', page)
        self.assertIn('d.anciennes', page)


# The real sentence of 20/10, 11 h 27, session « Installation kit recette » (a client Studio, no foreman).
WAITING = ("J'attends tes réponses, déjà posées plus haut : Q8 pour la publication du kit, Q10 pour le commentaire et "
           "l'assignation de PRJ-1234, Q11 pour les écarts restants et Q12 pour le passage quotidien.")
ASKED = ("Voici où on en est.\n\n## À trancher\n- **Q8 · Publication de la correction du kit** : je recommande que tu "
         "lances la commande.\n- **Q10 · PRJ-1234, commentaire et assignation** : je recommande Alex.\n"
         "- **Q11 · Les écarts restants** : un brouillon à la fois ?\n- **Q12 · Passage quotidien** : chaque matin ?")
# The real sentence of 20/10, 11 h 44, session « ᐅ Foreman PM · contremaître plus léger ».
NOT_YOU = "Un écart sans décision tracée se demande au fil rouge du sujet, jamais à toi."


class RecalledInASentence(Base):
    def lines(self, entries, sid=ALONE, cwd=OTHER_CWD):
        e = self.screen([self.session(sid, entries, cwd=cwd)])
        return [(l['affiche_titre'], l['lecture']) for l in e['tableau']], e['tableau']

    def test_each_recalled_question_gets_its_line_and_the_sentence_none(self):
        got, rows = self.lines([final(120, ASKED), pm(100, 'Je regarde'), final(60, 'Le ticket est à jour.\n\n' + WAITING)])
        self.assertEqual(got, [('Q8 · Publication de la correction du kit', 'rappel'),
                               ('Q10 · PRJ-1234, commentaire et assignation', 'rappel'),
                               ('Q11 · Les écarts restants', 'rappel'), ('Q12 · Passage quotidien', 'rappel')])
        self.assertIn('je recommande Alex', rows[1]['detail'])

    def test_found_nowhere_titled_by_what_the_sentence_says(self):
        got, rows = self.lines([final(60, WAITING)])
        self.assertEqual(got[0], ('Q8 · Pour la publication du kit', 'introuvable'))
        self.assertEqual(rows[0]['detail'], f"Question introuvable dans la session ; son dernier message disait : « {WAITING} »")
        self.assertEqual(len(got), 4)

    def test_a_list_announced_for_the_pm_keeps_its_other_demand(self):
        text = ("J'ai posté la version courte.\n\nIl reste à toi :\n- **Slack** : veux-tu un brouillon pour Sam ?\n"
                "- **Q8, publication du kit** : la commande à lancer toi-même est plus haut.\n"
                "- **Q11 (écarts restants) et Q12 (passage quotidien)** : toujours en attente.")
        got, _ = self.lines([final(120, ASKED), final(60, text)])
        self.assertEqual(sorted(t for t, _ in got), ['', 'Q11 · Les écarts restants', 'Q12 · Passage quotidien',
                                                     'Q8 · Publication de la correction du kit'])

    def test_a_mention_or_an_answer_given_is_not_a_recall(self):
        for text in ("Ce n'est pas encore fait. Une fois fait, dis-le au contremaître pour qu'il ferme Q44.",
                     "C'est fait.\n\nUne différence avec ta réponse à Q1 : la section n'est pas celle du 14/10. Dis-moi si ça te va.",
                     "Il t'a répondu par une marche à suivre, qu'il suit sous le numéro Q44, encore ouverte. Colle ce lien pour que je continue."):
            with self.subTest(text=text[:40]):
                got, _ = self.lines([final(60, text)])
                self.assertNotIn('rappel', [lecture for _, lecture in got])

    def test_in_a_chantier_a_recalled_question_on_the_board_gives_way(self):
        self.foreman([{'type': 'decision', 'titre': 'Q12 · Passage quotidien', 'source': KIT, 'depuis': at(200)}])
        _, rows = self.lines([final(60, 'Toujours en attente de toi : Q12.')], sid=KIT, cwd=STUDIO_CWD)
        self.assertEqual([l['lecture'] for l in rows], ['inscrite'])  # the board's line only


class NotForThePm(Base):
    def test_the_real_demand_next_to_it_stays(self):
        for text in ("Pas à toi de trancher : dis-moi juste si le texte te va.",
                     "Le contremaître répond, pas toi. Dis-moi si ça te va."):
            with self.subTest(text=text):
                self.assertEqual(parc.trier(text)[3], 1)
        self.assertEqual(parc.trier("C'est à toi.")[3], 1)


if __name__ == '__main__':
    unittest.main()
