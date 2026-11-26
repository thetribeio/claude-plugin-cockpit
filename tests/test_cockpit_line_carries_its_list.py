"""Tests of the lines the check of 2026-10-20 found mute: python3 -m unittest discover -s tests

1. A line taken from a sentence (not from a numbered question) had the sentence for title and for detail, and the
   list it pointed to (« Dis « ok » ou corrige une ligne : je fais alors les points 4.1 à 4.4. ») was nowhere. Its
   detail now carries, after the sentence, the block it points to: the one before it, or the one after it when the
   sentence announces it (ends with « : ») or opens the message; announced as such, cut. The title does not change.
2. A session of a foreman's Studio recalled two questions of other sessions (« Encore ouvert (autres sessions) : Q112,
   Q113. »), found nowhere in its transcript: two fallback lines, identical once their numbers were removed. A recalled
   question found nowhere, under a number the chantier gave, is the board's: no line. A recall without a number in a
   message that asks numbered questions points to them: no fallback line. Never two identical lines for a session.
3. The foreman wrote that another session « attend ta réponse à une question », without the question: a sentence that
   says another session waits for the PM, when that session has questions open on a board, names them and, in a
   chantier, gives way to their lines.
The real cases are anonymised; the other transcripts are synthetic."""
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
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN, KIT, KIT_B, OTHER_KIT, ALONE = 'local_foreman', 'local_kit', 'local_kitb', 'local_other', 'local_alone'
STUDIO_CWD, OTHER_CWD = '/studios/Studio-Essai', '/studios/Studio-Autre'
NOW = time.time()


def at(hours_ago):
    return dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).isoformat()


def final(hours_ago, text, mid='m'):
    return {'type': 'assistant', 'timestamp': at(hours_ago),
            'message': {'id': mid, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}}


def card(sid, title, cwd=STUDIO_CWD):
    return {'id': sid, 'archivee': False, 'cwd': cwd, 'titre': title, 'parent': None, 'tache': None}


# Case 1, a session of a client Studio (20/10), anonymised: the list to validate is just above the sentence.
OK_OR_FIX = "Dis-moi « ok » ou corrige une ligne : je fais alors les points 4.1 à 4.4."
POINTS = """Une seule famille, quatre points. Mon contrôle me bloque tout travail tant que tu n'as pas validé ce découpage. Une ligne par point, avec mon avis quand tu me le demandes.

- **4.1 Adresse :** la nouvelle adresse du bureau est confirmée. Mon avis : oui, l'ancienne peut nuire au référencement local, parce qu'une adresse différente d'une page à l'autre brouille la cohérence attendue. Je la remplace partout où je la trouve, après avoir listé les pages concernées.
- **4.2 Avis clients :** je retrouve moi-même la fiche à jour. La page locale y renvoie par un seul lien discret, sans chiffres ni étoiles mis en avant, comme tu le suggères.
- **4.3 Ton brouillon fait foi :** je ne redemande plus l'adresse ni les avis au client, et je ne lui parle plus de la page « Conseils » pour l'instant.
- **4.4 Page locale :** j'enlève l'adresse et les avis de la liste « à confirmer ». Il en reste donc moins pour le client.

""" + OK_OR_FIX
# The same mute line on 2026-10-19, anonymised: the sentence announces the list that follows it.
STILL_TO_DO = """Rien à me répondre ici : tout ce que j'attendais de toi est tranché.

Reste à faire de ton côté, hors de cette conversation :
- **La PM du projet** : confirmer le réel de septembre écrit sur ta consigne.
- **La comptabilité** : valider la feuille de temps de septembre à son retour.

Possible ensuite : une fois cette validation faite, je relance le contrôle."""
# Case 2, the light-foreman session of the test Studio (20/10), anonymised: its own questions are on the board, and
# it recalls two questions of another session, never asked in its transcript.
OTHER_SESSIONS = """Les deux suivis sont maintenant au tableau.

**À savoir**
- **Q112 et Q113** (une autre session) t'attendent toujours.

**À trancher**

**Q120 · Hook de démarrage** (bloquante pour la remise à zéro). Qui l'ajoute ?
1. La session du plugin (recommandé : rien n'est publié).
2. Je l'applique moi-même.

**Q121 · Remesure à J+2**. Une tâche planifiée la lance, ou tu me le dis ?
1. Une tâche planifiée unique (recommandé).
2. Tu me le dis ce jour-là.

Encore ouvert (autres sessions) : Q112, Q113."""
# Case 3, the foreman of the test Studio (20/10, 10 h 59), anonymised: another session waits for the PM's answer.
SHE_WAITS = ("Je la vois : [Kit B](#local_kitb). Elle a bien repris le kit sur la branche locale et attend ta réponse "
             "à une question.\n\nÀ savoir : tu l'as ouverte sur un autre dossier, donc la mémoire du chantier n'y est pas.")


class Lines(unittest.TestCase):
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

    def session(self, sid, text, cwd=STUDIO_CWD):
        """A session as construire() builds it, its last message written on disk."""
        path = pathlib.Path(self.tmp.name) / f'{sid}.jsonl'
        path.write_text(json.dumps(final(1, text), ensure_ascii=False) + '\n', encoding='utf-8')
        r = parc._analyser(str(path), NOW)
        s = dict(card(sid, 'Session ' + sid, cwd), chemin=str(path), derniere=r['depuis'], non_lue=False, **r)
        s['lignes'], s['reste'], s['tete'], s['prio'] = parc.trier(s.get('texte', ''))
        return s

    def foreman(self, waits=(), counter=None, name='essai', chantier='Essai', sid=FOREMAN):
        (parc.CHANTIERS / f'{name}.json').write_text(json.dumps(
            {'chantier': chantier, 'sessionId': sid, 'misAJour': at(30), 'attentes': list(waits)}))
        if counter is not None:
            (parc.CHANTIERS / f'{name}.numero').write_text(f'{counter}\n')

    def table(self, sessions):
        metas = [card(FOREMAN, 'Contremaître'), card(KIT, 'Kit A'), card(KIT_B, 'Kit B'), card(OTHER_KIT, 'Kit C'),
                 card(ALONE, 'Seule', OTHER_CWD), card('local_foreman2', 'Contremaître 2')]
        lignes = parc.tableau(sessions, metas, [], 7, NOW, {})
        e = {'genere': NOW, 'pastilles_lues': True, 'tableau': lignes, 'fils_rouges': [], 'sans_action': []}
        return lignes, parc.pour_la_page(e)['lignes'], e


class SentenceCarriesItsBlock(Lines):
    def line(self, text, sid=ALONE, cwd=OTHER_CWD):
        _, page, _ = self.table([self.session(sid, text, cwd)])
        l, = page
        return l

    def test_the_real_case_carries_the_list_just_above(self):
        l = self.line(POINTS)
        self.assertEqual((l['affiche_titre'], l['affiche_suite']), ('', OK_OR_FIX))  # the title does not change
        self.assertTrue(l['detail'].startswith(OK_OR_FIX + ' Juste avant, son message disait : « 4.1 Adresse : '))
        for point in ('4.1 Adresse :', '4.2 Avis clients :', '4.3 Ton brouillon fait foi :', '4.4 Page locale :'):
            self.assertIn(point, l['detail'])
        self.assertNotIn('Une seule famille', l['detail'])  # the block just above only
        self.assertNotEqual(l['detail'].strip(), OK_OR_FIX)

    def test_in_a_foreman_studio_too(self):
        self.foreman()
        _, page, _ = self.table([self.session(KIT, POINTS)])
        l, = page
        self.assertEqual((l['affiche_suite'], l['a_numeroter']), (OK_OR_FIX, FOREMAN))
        self.assertIn('4.4 Page locale :', l['detail'])

    def test_a_sentence_that_announces_a_list_carries_the_list_after_it(self):
        l = self.line(STILL_TO_DO)
        self.assertEqual(l['affiche_suite'], 'Reste à faire de ton côté, hors de cette conversation')
        self.assertEqual(l['detail'], "Reste à faire de ton côté, hors de cette conversation. Juste après, son message "
                                      "disait : « La PM du projet : confirmer le réel de septembre écrit sur ta consigne. "
                                      "· La comptabilité : valider la feuille de temps de septembre à son retour. »")

    def test_an_item_that_announces_its_sub_list(self):
        text = ("## Cette semaine\n\n3. **Les questions ouvertes, à toi de les poser** :\n   - à la comptable : que veut "
                "dire le magenta ;\n   - au chef de projet : la mission est-elle vivante ?\n4. **Mettre le rapport à jour.**")
        l = self.line(text)
        self.assertEqual(l['detail'], "Les questions ouvertes, à toi de les poser. Juste après, son message disait : "
                                      "« à la comptable : que veut dire le magenta ; · au chef de projet : la mission "
                                      "est-elle vivante ? »")

    def test_an_item_carries_the_items_before_it(self):
        text = ("**Ce qu'il te reste à faire**\n- Enregistre le fichier sur le Drive, avec son nom d'origine : le "
                "prochain passage le reprendra.\n- Si tu me dis où tu l'as mis, je le lis tout de suite.")
        l = self.line(text)
        self.assertEqual(l['affiche_suite'], 'Si tu me dis où tu l\'as mis, je le lis tout de suite.')
        self.assertIn("Juste avant, son message disait : « Enregistre le fichier sur le Drive", l['detail'])

    def test_a_table_just_above(self):
        text = ("| Point | Proposition |\n|---|---|\n| Titre | Garder |\n| Date | Reporter au 12 |\n\n"
                "Dis-moi si le tableau te va : je l'applique dès que c'est fait.")
        l = self.line(text)
        self.assertTrue(l['detail'].endswith("Juste avant, son message disait : « Point / Proposition · Titre / Garder "
                                             "· Date / Reporter au 12 »"))

    def test_the_start_of_its_own_paragraph(self):
        l = self.line("Le plan est prêt. J'ai trois pistes pour le titre : court, long ou sans. Dis-moi laquelle te va.")
        self.assertEqual(l['affiche_suite'], 'Dis-moi laquelle te va.')
        self.assertEqual(l['detail'], "Dis-moi laquelle te va. Juste avant, son message disait : « Le plan est prêt. "
                                      "J'ai trois pistes pour le titre : court, long ou sans. »")

    def test_a_long_list_keeps_every_item_and_is_cut(self):
        items = '\n'.join(f"- **Point {i} :** " + 'une explication assez longue du point, ' * 6 for i in range(1, 13))
        l = self.line(items + '\n\n' + OK_OR_FIX)
        bloc = l['detail'].split('disait : « ', 1)[1]
        self.assertLessEqual(len(bloc), parc.CONTEXTE_PHRASE_MAX + 2)
        for i in range(1, 9):  # 900 characters, at least 100 per item: the first eight items
            self.assertIn(f'Point {i} :', bloc)

    def test_nothing_around_says_so(self):
        l = self.line("Dis-moi quand c'est fait.")
        self.assertEqual(l['detail'], "Dis-moi quand c'est fait. Son message n'en dit pas plus.")

    def test_never_beyond_a_heading(self):
        l = self.line("Voici le compte rendu.\n\n## Ce que j'attends de toi\n\nDis-moi si le plan te va ?")
        self.assertEqual(l['detail'], "Dis-moi si le plan te va ? Son message n'en dit pas plus.")


class NoFallbackForTheBoard(Lines):
    def waits_120_121(self):
        return [{'type': 'decision', 'titre': 'Q120 · Hook de démarrage : qui l\'ajoute ?', 'source': KIT, 'depuis': at(1.2)},
                {'type': 'decision', 'titre': 'Q121 · Remesure à J+2 : tâche planifiée ou rappel ?', 'source': KIT,
                 'depuis': at(1.2)}]

    def session_lines(self, lignes):
        return [l for l in lignes if not l.get('chantier')]

    def test_the_real_case_gives_no_line_of_its_own(self):
        # Q112 is open on the board for another session; Q113 has been solded (the counter gave it).
        self.foreman(self.waits_120_121() + [{'type': 'task', 'titre': 'Q112 · Recoller le script', 'source': OTHER_KIT,
                                              'depuis': at(20)}], counter=121)
        lignes, page, _ = self.table([self.session(KIT, OTHER_SESSIONS)])
        self.assertEqual(self.session_lines(lignes), [])
        self.assertEqual(sorted(l['question'] for l in page), ['Q112', 'Q120', 'Q121'])  # the board's lines
        self.assertFalse(any(parc.QUESTION_SANS_TEXTE in (l['affiche_titre'] + l['affiche_suite']) for l in page))

    def test_without_a_counter_the_board_numbers_count(self):
        self.foreman(self.waits_120_121() + [{'type': 'task', 'titre': 'Q113 · Autre', 'source': OTHER_KIT,
                                              'depuis': at(20)}])
        lignes, _, _ = self.table([self.session(KIT, OTHER_SESSIONS)])
        self.assertEqual(self.session_lines(lignes), [])  # Q112 is under 121, the highest number on the board

    def test_numbers_the_chantier_never_gave_keep_one_line_never_two(self):
        self.foreman(counter=100)
        lignes, page, _ = self.table([self.session(KIT, OTHER_SESSIONS.replace('Q120', 'Q90').replace('Q121', 'Q91'))])
        own = [(l['affiche_titre'], l['affiche_suite']) for l in page]
        self.assertEqual(len(own), len(set(own)))
        self.assertEqual(sum(1 for t, _ in own if t == parc.QUESTION_SANS_TEXTE), 1)
        self.assertEqual(sorted(l['num'] for l in self.session_lines(lignes)), [90, 91, 112])

    def test_outside_a_chantier_the_numbers_stay_and_differ(self):
        self.foreman(counter=200)
        _, page, _ = self.table([self.session(ALONE, OTHER_SESSIONS, OTHER_CWD)])
        titles = [l['affiche_titre'] for l in page]
        self.assertIn("Q112 · Une question t'attend dans cette session", titles)
        self.assertIn("Q113 · Une question t'attend dans cette session", titles)

    def test_a_recall_without_number_points_to_the_questions_of_its_message(self):
        text = ("Le plan est prêt.\n\n## À trancher\n\n**Q5 · Format du CR** : court ou long ? Je recommande court.\n\n"
                "Encore ouvert : la question ci-dessus, en attente de ta réponse.")
        s = self.session(ALONE, text, OTHER_CWD)
        self.assertEqual(parc.debut_section(s['tete']), 'ouvert')  # the sentence that used to give the fallback
        self.assertEqual([(d['titre'], d['lecture']) for d in parc.demandes(s)], [('Q5 · Format du CR', 'format')])

class AnotherSessionWaits(Lines):
    def wait_21(self):
        return {'type': 'decision', 'titre': 'Q21 · Kit B : quel essai ensuite ?', 'source': KIT_B, 'depuis': at(2)}

    def test_the_real_case_gives_way_to_the_board_line(self):
        self.foreman([self.wait_21()])
        _, page, _ = self.table([self.session(FOREMAN, SHE_WAITS)])
        self.assertEqual([(l['question'], l['session']) for l in page], [('Q21', 'Kit B')])

    def test_its_question_on_another_chantier_board(self):
        self.foreman()
        self.foreman([self.wait_21()], name='autre', chantier='Autre', sid='local_foreman2')
        _, page, _ = self.table([self.session(FOREMAN, SHE_WAITS)])
        self.assertEqual([l['question'] for l in page], ['Q21'])

    def test_outside_a_chantier_the_line_names_the_questions(self):
        self.foreman([self.wait_21()])
        _, page, _ = self.table([self.session(ALONE, SHE_WAITS, OTHER_CWD)])
        mine = [l for l in page if l['cle'] == ALONE]
        # One line on the board (PM, 2026-11-18): the sentence is cut at a natural break or a whole word, never « … », the questions it names stay; the click has it all.
        self.assertEqual([l['affiche_suite'] for l in mine],
                         ["Elle a bien repris le kit sur la branche locale et attend · Q21 au tableau Essai"])
        self.assertEqual([l['complet'] for l in mine],
                         ["Elle a bien repris le kit sur la branche locale et attend ta réponse à une question · Q21 "
                          "au tableau Essai"])

    def test_named_by_its_title(self):
        self.foreman([self.wait_21()])
        text = "La session « Kit B » attend ta réponse sur son plan d'essai."
        _, page, _ = self.table([self.session(KIT, text)])
        self.assertEqual([l['question'] for l in page], ['Q21'])

    def test_no_question_on_a_board_keeps_the_line(self):
        self.foreman()
        _, page, _ = self.table([self.session(FOREMAN, SHE_WAITS)])
        l, = page
        self.assertEqual(l['affiche_suite'], 'Elle a bien repris le kit sur la branche locale et attend ta réponse à une '
                                             'question.')
        self.assertIn('Juste avant, son message disait : « Je la vois : Kit B. »', l['detail'])

    def test_a_request_of_the_session_itself_never_hides(self):
        self.foreman([self.wait_21()])
        for text in ("J'attends ton go pour publier ; [Kit B](#local_kitb) attend ta réponse.",
                     "[Kit B](#local_kitb) attend ta réponse : tu la lui donnes maintenant ?",
                     "Je relance le passage dès que tu me dis go : [Kit B](#local_kitb) attend ta réponse."):
            _, page, _ = self.table([self.session(KIT, text)])
            self.assertEqual(len([l for l in page if l['cle'] == KIT]), 1, text)


if __name__ == '__main__':
    unittest.main()
