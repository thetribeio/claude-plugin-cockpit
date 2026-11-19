"""Tests of the text of a question line in Mon Studio: python3 -m unittest discover -s tests

A question that a session recalls (« Encore ouvert : Q4 ») takes, in the transcript, the last paragraph that starts
with its number, under « À trancher » or elsewhere: its title for the line, the whole paragraph (options and
recommendation included) for the detail. Otherwise the parenthesis of the « Encore ouvert » line gives the title,
otherwise « Une question t'attend dans cette session ». In a Studio that has a foreman, a session line shows no number
of its own (it would be mistaken for a board number); elsewhere, and in lignes-brutes.py, the number stays.
The replayed case comes from a real session, anonymised; the other transcripts are synthetic."""
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
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN, KIT, ALONE = 'local_foreman', 'local_kit', 'local_alone'
STUDIO_CWD, OTHER_CWD = '/studios/Studio-Essai', '/studios/Studio-Autre'
NOW = time.time()


def at(hours_ago):
    return dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).isoformat()


def final(hours_ago, text, mid):
    return {'type': 'assistant', 'timestamp': at(hours_ago),
            'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def pm(hours_ago, text):
    return {'type': 'user', 'timestamp': at(hours_ago), 'origin': {'kind': 'human'}, 'message': {'content': text}}


# The real case (a session of a Studio with a foreman, 14 and 15/10), anonymised. Q3's title is bold and alone on its
# line, its options follow; Q4's title is bold, its question follows on the same line. The bold line alone used to
# close « À trancher », so Q4 was never found and its line read « Q4 : posée plus haut dans la session ».
ASK_3_4 = """Oui pour l'option A. Une limite : l'outil ne sait pas installer une partie seulement d'un plugin (Q3).

## Ce que garantit « inerte »

- L'outil installe et met à jour un plugin d'un bloc.

## À savoir

Pour l'option A, il te restera un geste : demander à l'administrateur d'ajouter le dépôt au catalogue de l'organisation.

## À trancher

**Q3 · Skill lançable par Claude**
- a) **(Recommandé)** On accepte. La description se limite à « lancé par sa tâche programmée ».
- b) Le skill devient un plugin à part, dans le même catalogue. En contrepartie, la commande change de nom.

**Q4 · L'entrée du plugin dans le catalogue commun.** Avec l'option A, le plugin serait proposé par deux catalogues. Je recommande de fermer sans fusion la [PR catalogue#1](https://example.com/catalogue/pull/1), qui l'y ajoute.

Encore ouvert : Q2 (ton go pour écrire, qui attend aussi Q3)."""
RECALL_4 = ("La PR est ouverte. Rien n'est fusionné.\n\n"
            "Encore ouvert : Q4 (l'entrée du plugin dans le catalogue commun, que tu valides avec le référent technique).")
CITES_4 = ("**2. La synchronisation du catalogue.** Elle ne sert qu'aux versions suivantes. Pour la question au référent "
           "(Q4), il s'agit de savoir si on garde l'entrée dans le catalogue commun.\n\n" + RECALL_4.split('\n\n')[1])
REAL_CASE = [final(21, ASK_3_4, 'm1'), pm(20.9, 'Q3 : a. Q2 : go.'), final(20.5, RECALL_4, 'm2'),
             pm(5, 'Où en est la synchronisation ?'), final(4.9, CITES_4, 'm3')]
Q4_TITLE = "L'entrée du plugin dans le catalogue commun"
Q4_PARAGRAPH = ("Avec l'option A, le plugin serait proposé par deux catalogues. Je recommande de fermer sans fusion "
                "la PR catalogue#1, qui l'y ajoute.")


def card(sid, title, cwd=STUDIO_CWD):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None, 'tache': None}


class Transcripts(unittest.TestCase):
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

    def session(self, sid, entries, cwd=STUDIO_CWD):
        """A session as construire() builds it, from a transcript written on disk."""
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(card(sid, 'Session ' + sid, cwd), chemin=str(path), derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def foreman(self, waits=()):
        (parc.CHANTIERS / 'essai.json').write_text(json.dumps(
            {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(30), 'attentes': list(waits)}))

    def table(self, sessions):
        metas = [card(FOREMAN, 'Contremaître'), card(KIT, 'Kit A'), card(ALONE, 'Seule', OTHER_CWD)]
        metas += [card(s['id'], s['titre'], s['cwd']) for s in sessions if s['id'] not in (FOREMAN, KIT, ALONE)]
        lignes = parc.tableau(sessions, metas, [], 7, NOW, {})
        e = {'genere': NOW, 'pastilles_lues': True, 'tableau': lignes, 'fils_rouges': [], 'sans_action': []}
        return lignes, parc.pour_la_page(e)['lignes'], e


class RealCase(Transcripts):
    def test_the_bold_title_alone_keeps_the_section_open(self):
        items, ouverts = parc.a_trancher(ASK_3_4)
        self.assertEqual([i['num'] for i in items], [3, 4])
        self.assertEqual(ouverts, [2, 3])  # « Q2 (…, qui attend aussi Q3) »
        q3, q4 = items
        self.assertEqual(q3['titre'], 'Q3 · Skill lançable par Claude')
        self.assertIn('a) (Recommandé) On accepte.', q3['suite'])
        self.assertIn('b) Le skill devient un plugin à part', q3['suite'])
        self.assertEqual((q4['titre'], q4['suite']), ('Q4 · ' + Q4_TITLE, Q4_PARAGRAPH))

    def test_the_recalled_question_takes_its_paragraph(self):
        s = self.session(KIT, REAL_CASE, OTHER_CWD)
        d, = parc.demandes(s)
        self.assertEqual((d['num'], d['titre'], d['suite']), (4, 'Q4 · ' + Q4_TITLE, Q4_PARAGRAPH))
        self.assertEqual(d['depuis'], parc.ts_iso(at(21)))  # since it was first asked

    def test_in_the_foreman_studio_title_and_detail_without_its_number(self):
        self.foreman()
        _, page, _ = self.table([self.session(KIT, REAL_CASE)])
        l, = page
        self.assertEqual(l['affiche_titre'], Q4_TITLE)
        self.assertEqual(l['detail'], f"{Q4_TITLE} : {Q4_PARAGRAPH}")
        self.assertEqual(l['complet'], l['detail'])
        self.assertEqual(l['a_numeroter'], FOREMAN)

    def test_a_recalled_title_alone_brings_its_options_and_recommendation(self):
        entries = [final(3, ASK_3_4, 'm1'), pm(2.9, 'Q4 : je vois avec le référent.'),
                   final(2.8, 'Noté.\n\nEncore ouvert : Q3.', 'm2')]
        d, = parc.demandes(self.session(ALONE, entries, OTHER_CWD))
        self.assertEqual(d['titre'], 'Q3 · Skill lançable par Claude')
        self.assertTrue(d['suite'].startswith('a) (Recommandé) On accepte.'))
        self.assertIn('b) Le skill devient un plugin à part', d['suite'])


class Paragraphs(Transcripts):
    def recalled(self, *texts, recall='Encore ouvert : Q5.'):
        entries = [final(10 - i, t, f'm{i}') for i, t in enumerate(texts)] + [final(1, 'Fait.\n\n' + recall, 'last')]
        lines = parc.demandes(self.session(ALONE, entries, OTHER_CWD))
        for d in lines:
            self.assertNotIn('posée plus haut', d['titre'] + d['suite'])
        return lines

    def test_a_paragraph_outside_a_trancher(self):
        d, = self.recalled("Deux points d'abord.\n\n**Q5 · Format du CR.** Court ou long ? Je recommande court.\n\nLa suite demain.")
        self.assertEqual((d['titre'], d['suite']), ('Q5 · Format du CR', 'Court ou long ? Je recommande court.'))

    def test_plain_colon_form(self):
        d, = self.recalled('Q5 : faut-il prévenir le client avant vendredi ?')
        self.assertEqual(d['titre'], 'Q5 · faut-il prévenir le client avant vendredi ?')

    def test_a_title_alone_takes_the_options_after_a_blank_line_only(self):
        d, = self.recalled('**Q5 · Format du CR**\n\n- a) Court (recommandé)\n- b) Long\n\nJ\'ai aussi rangé le dossier.')
        self.assertEqual((d['titre'], d['suite']), ('Q5 · Format du CR', 'a) Court (recommandé) b) Long'))

    def test_the_paragraph_ends_at_the_next_heading_or_question(self):
        d, = self.recalled('Q5 · Format du CR : court ou long ?\n## À savoir\nRien de neuf.\nQ6 · Autre : oui ?')
        self.assertEqual(d['suite'], 'court ou long ?')

    def test_the_last_paragraph_wins_since_the_first(self):
        entries = [final(10, 'Q5 · Format : court ou long ?', 'a'), final(5, 'Q5 · Format du CR : court, long ou aucun ?', 'b'),
                   final(1, 'Encore ouvert : Q5.', 'c')]
        d, = parc.demandes(self.session(ALONE, entries, OTHER_CWD))
        self.assertEqual((d['titre'], d['suite']), ('Q5 · Format du CR', 'court, long ou aucun ?'))
        self.assertEqual(d['depuis'], parc.ts_iso(at(10)))

    def test_a_mere_mention_or_code_is_not_a_paragraph(self):
        lines = self.recalled('Pour la question au référent (Q5), rien de neuf. Q5 et Q6 attendent.',
                              '```\nQ5 · Faux titre : dans du code\n```')
        self.assertEqual(lines[0]['titre'], "Q5 · Une question t'attend dans cette session")


class Fallbacks(Transcripts):
    def test_the_parenthesis_of_encore_ouvert_gives_the_title(self):
        entries = [final(1, "C'est en ligne.\n\nEncore ouvert : Q7 (le nom du dossier partagé), Q8.", 'm')]
        q7, q8 = parc.demandes(self.session(ALONE, entries, OTHER_CWD))
        self.assertEqual((q7['titre'], q7['suite']), ('Q7 · Le nom du dossier partagé', ''))
        self.assertEqual((q8['titre'], q8['suite']), ("Q8 · Une question t'attend dans cette session", ''))

    def test_detail_never_says_asked_higher_up(self):
        self.foreman()
        entries = [final(1, "C'est en ligne.\n\nEncore ouvert : Q7 (le nom du dossier partagé), Q8.", 'm')]
        _, page, e = self.table([self.session(KIT, entries)])
        found_nowhere = "Question introuvable dans la session ; son dernier message disait : « C'est en ligne. »"
        self.assertEqual([(l['affiche_titre'], l['detail']) for l in page],
                         [('Le nom du dossier partagé', found_nowhere),
                          ("Une question t'attend dans cette session", found_nowhere)])
        for text in (parc.rendre_md(e), json.dumps(page, ensure_ascii=False)):
            self.assertNotIn('posée plus haut', text)


ASK_4_5 = ("Le plan est prêt.\n\n## À trancher\n**Q5 · Date du COPIL** : jeudi ou vendredi ?\n"
           "**Q4 · Format du CR** : court ou long ? Je recommande court.")


class OwnNumber(Transcripts):
    def test_foreman_studio_page_and_markdown_without_the_number(self):
        self.foreman()
        lignes, page, e = self.table([self.session(KIT, [final(1, ASK_4_5, 'm')])])
        self.assertEqual([l['affiche_titre'] for l in page], ['Format du CR', 'Date du COPIL'])  # still in Q order
        self.assertEqual([l['num'] for l in lignes], [4, 5])  # the number stays for the computation
        self.assertEqual(page[0]['detail'], 'Format du CR : court ou long ? Je recommande court.')
        for text in (parc.rendre_md(e), json.dumps(page, ensure_ascii=False)):
            self.assertNotIn('Q4', text)
            self.assertNotIn('Q5', text)

    def test_the_number_still_finds_the_board(self):
        self.foreman([{'type': 'decision', 'titre': 'Q4 · Format du CR', 'source': KIT, 'depuis': at(30)}])
        lignes, _, _ = self.table([self.session(KIT, [final(1, ASK_4_5, 'm')])])
        own = [l for l in lignes if not l.get('chantier')]
        self.assertEqual([(l['num'], l['affiche_titre']) for l in own], [(5, 'Date du COPIL')])

    def test_a_single_sentence_line_and_a_menu_lose_it_too(self):
        self.foreman()
        menu = {'type': 'assistant', 'timestamp': at(0.5), 'message': {'id': 'q', 'stop_reason': 'tool_use', 'content': [
            {'type': 'tool_use', 'id': 'u', 'name': 'AskUserQuestion',
             'input': {'questions': [{'question': 'Q9 · Je lance la fusion ?', 'options': [{'label': 'Oui (Recommandé)'}, {'label': 'Non'}]}]}}]}}
        sessions = [self.session(KIT, [final(1, 'Le fichier est prêt. Q6 : je le publie maintenant ?', 'm')]),
                    self.session('local_menu', [menu])]
        sessions[1]['etat'] = 'suspens'
        _, page, _ = self.table(sessions)
        texts = sorted(l['affiche_titre'] or l['affiche_suite'] for l in page)
        self.assertEqual(texts, ['Je lance la fusion ?', 'je le publie maintenant ?'])
        self.assertTrue(all('Q9' not in (l['detail'] or '') for l in page))

    def test_the_foreman_keeps_its_numbers(self):
        # Its numbers are the board's: a numbered question of its own is already on the board, a menu keeps its number.
        self.foreman()
        menu = {'type': 'assistant', 'timestamp': at(0.5), 'message': {'id': 'q', 'stop_reason': 'tool_use', 'content': [
            {'type': 'tool_use', 'id': 'u', 'name': 'AskUserQuestion',
             'input': {'questions': [{'question': 'Q72 · Je pose la règle ?', 'options': [{'label': 'Oui'}, {'label': 'Non'}]}]}}]}}
        foreman = self.session(FOREMAN, [menu])
        foreman['etat'] = 'suspens'
        _, page, _ = self.table([foreman])
        self.assertEqual([l['affiche_titre'] for l in page], ['Q72 · Je pose la règle ?'])

    def test_outside_a_foreman_studio_the_number_stays(self):
        self.foreman()
        _, page, e = self.table([self.session(ALONE, [final(1, ASK_4_5, 'm')], OTHER_CWD)])
        self.assertEqual([l['affiche_titre'] for l in page], ['Q4 · Format du CR', 'Q5 · Date du COPIL'])
        self.assertEqual(page[0]['detail'], 'Q4 · Format du CR : court ou long ? Je recommande court.')
        self.assertIn('Q4 · Format du CR', parc.rendre_md(e))


class RawLines(unittest.TestCase):
    """lignes-brutes.py, run as the foreman runs it, on a fake home: the session's own number stays, so that the
    foreman can link the question to its session."""
    def test_lignes_brutes_keeps_the_number(self):
        with tempfile.TemporaryDirectory() as home:
            home = pathlib.Path(home)
            cards = home / 'Library/Application Support/Claude/claude-code-sessions/compte/org'
            cards.mkdir(parents=True)
            for sid, title in ((FOREMAN, 'Contremaître'), (KIT, 'Kit A')):
                (cards / f'{sid}.json').write_text(json.dumps({
                    'sessionId': sid, 'cliSessionId': 'cli-' + sid, 'cwd': STUDIO_CWD, 'title': title,
                    'lastActivityAt': int(NOW * 1000), 'createdAt': int((NOW - 86400) * 1000)}))
            projects = home / '.claude/projects/essai'
            projects.mkdir(parents=True)
            (projects / f'cli-{FOREMAN}.jsonl').write_text('')
            (projects / f'cli-{KIT}.jsonl').write_text(json.dumps(final(1, ASK_4_5, 'm'), ensure_ascii=False) + '\n')
            outils = home / 'Mon Studio/.parc'
            outils.mkdir(parents=True)
            shutil.copy(SCRIPTS / 'parc.py', outils / 'parc.py')
            (home / 'Mon Studio/chantiers').mkdir()
            (home / 'Mon Studio/chantiers/essai.json').write_text(json.dumps(
                {'chantier': 'Essai', 'sessionId': FOREMAN, 'misAJour': at(30), 'attentes': []}))
            # a macOS layout on any OS: the child process is told where the app keeps its cards
            env = dict(os.environ, HOME=str(home), MON_STUDIO_APP_SESSIONS=str(cards.parent.parent))
            out = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'lignes-brutes.py'), 'Essai'],
                                 check=True, capture_output=True, text=True, env=env).stdout
            self.assertIn('Q4 · Format du CR : court ou long ?', out)
            self.assertIn('Q5 · Date du COPIL : jeudi ou vendredi ?', out)


if __name__ == '__main__':
    unittest.main()
