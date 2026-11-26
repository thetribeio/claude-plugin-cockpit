"""Short titles (PM, 2026-11-18): python3 -m unittest discover -s tests

1. A numbered question in the new format (« Qn · <short title> : <precise question> », options « 1) **label** : … »)
   shows its title alone on the board; its unfold gives the precise question, never the title again, the options in
   full and the rubrics it writes.
2. An older question (its title a topic) holds on one line: title and start of its text, cut on a word, with « … ».
3. Answer buttons are worded: the bold label, else the option cut on a word under 28 characters; the recommended one
   first, « (recommandée) » read too; the answer sent stays the number.
4. A « Vérifier » line that waits for nothing (information only) leaves the board.
5. The Stop hook format_questions.py blocks once on a malformed « À trancher » block, stays silent on a compliant one
   or after a block, logs one line per message without its text, and stays silent once Mon Studio is disabled.
6. Rule 2 of regles/format-reponses.md says the format, with an example the hook accepts.
Sessions and texts are made up."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
HOOK = ROOT / 'hooks' / 'format_questions.py'
HOOKS_JSON = ROOT / 'hooks' / 'hooks.json'

spec = importlib.util.spec_from_file_location('parc_titres_courts', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
_VIDE = tempfile.TemporaryDirectory()
parc.CHANTIERS = pathlib.Path(_VIDE.name)   # no real mirror ever read here

NOUVEAU = ("C'est prêt.\n\n**À trancher**\n\n"
           "Q43 · Envoyer le mail demain matin ? : Tu le relis et l'envoies demain depuis Gmail après avoir vérifié les "
           "suggestions des Docs.\n"
           "1) **L'envoyer demain** : tel quel, après ta relecture (recommandé)\n"
           "2) **Le resserrer d'abord** : autour des villes, de la page zones et des créneaux.\n"
           "Pourquoi : le client l'attend. Si tu ne fais rien : le mail attend.\n")
ANCIEN = ("Fait.\n\n**À trancher**\n\n"
          "Q43 · Suite du mail : tu le relis et l'envoies demain matin depuis Gmail, après avoir vérifié les suggestions "
          "dans les Docs partagés avec le client.\n")
KPI = ("Relu.\n\n**À trancher**\n\nQ8 · Promesse KPI : que fait-on de la phrase ? 1. Retirer la phrase (recommandée) "
       "2. Remplacer « les KPI » par « ce qui rend le projet acceptable », que les critères de décision "
       "3. Laisser la page telle quelle\n")
WEEKLY = ("Bloqué.\n\n**À trancher**\n\nQ6 · Weekly : options 1) attendre la remise à zéro du quota et relancer "
          "l'analyse (recommandé) ; 2) je lis le panneau commentaires dans le navigateur intégré (long, coûteux) ; "
          "3) demander un siège Dev/Full au staff\n")


def board(texte, non_lue=True):
    s = {'id': 'local_a', 'cwd': '/studios/Studio-Beta', 'titre': 'Démarrage', 'non_lue': non_lue, 'derniere': 1e9,
         'etat': 'attend', 'depuis': 1e9, 'texte': texte, 'chemin': '/dev/null'}
    cards = [{'id': 'local_a', 'archivee': False, 'cwd': s['cwd'], 'titre': s['titre'], 'parent': None}]
    return [parc.rang_page(l) for l in parc.tableau([s], cards, [], 7, 1e9 + 60, {})]


def run_page(lignes):
    lignes = [dict(l, depuis=int(time.time() * 1000) - 60000) for l in lignes]   # recent: on the main board
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump({'lignes': lignes, 'outils': ['lignes', 'projet', 'ouvrir', 'clore', 'lire']}, f)
    try:
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)['tableau']


class Line(unittest.TestCase):
    def test_new_format_shows_the_title_alone(self):
        l = board(NOUVEAU)[0]
        self.assertEqual((l['affiche_titre'], l['affiche_suite']), ('Q43 · Envoyer le mail demain matin ?', ''))

    def test_its_unfold_is_the_precise_question_never_the_title(self):
        d = board(NOUVEAU)[0]['depli']
        self.assertEqual(d['question'], "Tu le relis et l'envoies demain depuis Gmail après avoir vérifié les "
                                        "suggestions des Docs.")
        self.assertNotIn('Envoyer le mail demain matin', d['question'])
        self.assertEqual([o['entiere'] for o in d['options']],
                         ["L'envoyer demain : tel quel, après ta relecture",
                          "Le resserrer d'abord : autour des villes, de la page zones et des créneaux."])
        self.assertEqual([o['recommande'] for o in d['options']], [True, False])
        self.assertEqual((d['pourquoi'], d['sinon']), ("le client l'attend.", 'le mail attend.'))

    def test_old_format_holds_on_one_line(self):
        l = board(ANCIEN)[0]
        affiche = f"{l['affiche_titre']} : {l['affiche_suite']}"
        self.assertTrue(affiche.startswith('Q43 · Suite du mail : tu le relis'))
        self.assertNotIn('…', affiche)
        self.assertLessEqual(len(affiche), parc.LIGNE_MAX + 2)
        self.assertIn('Docs partagés avec le client', board(ANCIEN)[0]['depli']['question'])   # the click: in full

    def test_an_unnumbered_line_holds_on_one_line_too(self):
        texte = "J'ai fini. " + 'Valide le périmètre du lot deux, avec les écrans de recherche, de fiche et de paiement, ' \
                'avant la réunion de jeudi avec le client.'
        l = board(texte)[0]
        self.assertLessEqual(len(l['affiche_titre'] + l['affiche_suite']), parc.LIGNE_MAX + 2)

    def test_impact_label_does_not_cut_the_title(self):
        t = "Ok.\n\n**À trancher**\n\nQ4 · Date de recette (impact fort : échéance) : on la fixe au 3 ou au 10 ?\n"
        l = board(t)[0]
        self.assertEqual((l['affiche_titre'], l['impact'], l['raison']), ('Q4 · Date de recette', 'fort', 'échéance'))
        self.assertEqual(l['depli']['question'], 'on la fixe au 3 ou au 10 ?')


class Buttons(unittest.TestCase):
    def test_bold_labels_recommended_first(self):
        l = board(NOUVEAU)[0]
        self.assertEqual(l['question'], 'Q43')
        self.assertIn('1', l['choix'])
        self.assertEqual((l['choix_libelles'], l['choix_reco']), ({'1': "L'envoyer demain", '2': "Le resserrer d'abord"}, '1'))

    def test_options_without_label_are_cut_on_a_word(self):
        l = board(KPI)[0]
        self.assertEqual(l['choix_libelles'], {'1': 'Retirer la phrase', '2': 'Remplacer « les KPI » par…',
                                               '3': 'Laisser la page telle…'})
        self.assertEqual(l['choix_reco'], '1')   # « (recommandée) », feminine
        w = board(WEEKLY)[0]
        self.assertEqual(w['choix_reco'], '1')
        self.assertTrue(all(len(x) < parc.BOUTON_MAX for x in w['choix_libelles'].values()), w['choix_libelles'])

    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_the_page_shows_words_not_numbers(self):
        html = run_page([board(KPI)[0]])
        boutons = [b.split('>', 1)[1] for b in html.split('<button type="button" class="decide choix"')[1:]]
        textes = [b.split('</button>')[0] for b in boutons]
        self.assertEqual(textes, ['Retirer la phrase (recommandé)', 'Remplacer « les KPI » par…', 'Laisser la page telle…'])
        self.assertIn('data-choix="1"', html)              # the answer sent stays the number
        self.assertNotIn('data-choix="recommandé : ', html)  # no second button for the recommendation

    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_the_page_unfolds_question_options_and_rubrics_without_the_title(self):
        html = run_page([board(NOUVEAU)[0]])
        detail = html.split('class="detail"')[1]
        self.assertNotIn('Envoyer le mail demain matin', detail)
        self.assertIn("Tu le relis et l&#39;envoies demain", detail)
        self.assertIn('autour des villes, de la page zones et des créneaux.', detail)
        for rubrique in ('Recommandé', 'Pourquoi', 'Si tu ne fais rien'):
            self.assertIn(f'<dt>{rubrique}</dt>', detail)

    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_every_line_opens(self):
        l = {'studio': 'Beta', 'session': 'S', 'cle': 'local_a', 'type': 'task', 'verbe': 'Faire', 'ouvrir': 'local_a',
             'affiche_titre': '', 'affiche_suite': 'Relis la page', 'complet': 'Relis la page', 'detail': 'Relis la page',
             'depuis': int(time.time() * 1000) - 60000}
        self.assertIn('data-deplier=', run_page([l]))


class InformationLeaves(unittest.TestCase):
    def test_a_sentence_that_waits_for_nothing_makes_no_check_line(self):
        for texte in ("Voilà.\n\nPour toi :\n- Le reste de la préparation de la publication est chez "
                      "[Cockpit · finitions avant le go](#local_x), qui travaille encore.\n",
                      "Fait.\n\n- L'inventaire des ateliers est rendu dans le dossier 1-cadrage.\n"):
            lignes = board(texte, non_lue=False)
            self.assertEqual([l for l in lignes if l['type'] == 'check'], [], texte)

    def test_a_request_keeps_its_line(self):
        self.assertTrue(parc.demande_au_pm('Valide le périmètre avant jeudi.'))
        self.assertTrue(parc.demande_au_pm('Le fichier est prêt à relire.'))
        self.assertFalse(parc.demande_au_pm("L'inventaire des ateliers est rendu."))


def transcript(dossier, texte):
    now = dt.datetime.now(dt.timezone.utc)
    lignes = [{'type': 'user', 'timestamp': (now - dt.timedelta(seconds=60)).isoformat(), 'message': {'role': 'user', 'content': 'Avance.'}},
              {'type': 'assistant', 'timestamp': now.isoformat(),
               'message': {'id': 'm1', 'role': 'assistant', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': texte}]}}]
    p = pathlib.Path(dossier) / 't.jsonl'
    p.write_text(''.join(json.dumps(o, ensure_ascii=False) + '\n' for o in lignes), encoding='utf-8')
    return str(p)


HOST = 'local_00000000-0000-0000-0000-0000000000a1'


def env_app(home, host=HOST, **autres):
    """The environment of a hook in a session of the desktop app (host=None: a terminal session or a `claude -p`)."""
    env = dict(os.environ, HOME=home, **autres)
    env.pop('CLAUDE_CODE_HOST_SESSION_ID', None)
    if host is not None:
        env['CLAUDE_CODE_HOST_SESSION_ID'] = host
    return env


class Hook(unittest.TestCase):
    MAUVAIS = ("Fini.\n\n**À trancher**\n\nQ7 · Le format du compte rendu hebdomadaire envoyé au client chaque vendredi "
               "matin : lequel ?\n1. Une page (recommandé)\n2. Un mail\n")

    def run_hook(self, texte, host=HOST, state=None, **entree):
        with tempfile.TemporaryDirectory() as home:
            (pathlib.Path(home) / 'Mon Studio' / '.parc').mkdir(parents=True)
            if state is not None:
                (pathlib.Path(home) / 'Mon Studio' / '.parc' / 'cockpit.json').write_text(json.dumps(state))
            entree = dict({'session_id': 'abc', 'transcript_path': transcript(home, texte)}, **entree)
            r = subprocess.run(['python3', str(HOOK)], input=json.dumps(entree), capture_output=True, text=True,
                               timeout=30, env=env_app(home, host))
            journal = pathlib.Path(home) / 'Mon Studio' / '.parc' / 'format-questions.jsonl'
            return r.stdout, [json.loads(x) for x in journal.read_text().splitlines()] if journal.exists() else []

    def test_blocks_once_on_a_malformed_block(self):
        out, journal = self.run_hook(self.MAUVAIS)
        r = json.loads(out)
        self.assertEqual(r['decision'], 'block')
        self.assertIn('Q7', r['reason'])
        self.assertIn('titre de', r['reason'])
        self.assertIn('options sans libellé', r['reason'])
        self.assertIn('Reposte seulement le bloc « À trancher »', r['reason'])
        self.assertEqual(journal[0]['questions'], 1)
        self.assertEqual(journal[0]['ecarts'], ['options_sans_libelle', 'titre_long'])
        self.assertNotIn('compte rendu', json.dumps(journal))   # never the message's text

    def test_silent_after_a_block(self):
        out, journal = self.run_hook(self.MAUVAIS, stop_hook_active=True)
        self.assertEqual(out, '')
        self.assertTrue(journal[0]['relance'])

    def test_silent_on_a_compliant_block(self):
        out, journal = self.run_hook(NOUVEAU)
        self.assertEqual(out, '')
        self.assertEqual(journal[0]['ecarts'], [])

    def test_missing_question_and_long_label(self):
        t = ("Ok.\n\n**À trancher**\n\nQ2 · Publier la page\n1) **Publier maintenant sans attendre la relecture** : tout de "
             "suite\n2) **Attendre** : lundi\n")
        out, journal = self.run_hook(t)
        self.assertIn('pas de question précise', json.loads(out)['reason'])
        self.assertEqual(journal[0]['ecarts'], ['libelle_long', 'sans_question'])

    def test_switch_off_reads_and_notes_nothing(self):
        self.assertEqual(self.run_hook(self.MAUVAIS, state={'page': 'x', 'controle_format': False}), ('', []))
        out, _ = self.run_hook(self.MAUVAIS, state={'page': 'x', 'controle_format': True})
        self.assertEqual(json.loads(out)['decision'], 'block')

    def test_silent_outside_a_session_of_the_desktop_app(self):
        # A terminal session, a `claude -p`, and the connector's wake `claude --resume <id> -p "<answer>"`, whose
        # environment drops every CLAUDE_* variable (mcp_mon_studio.env_terminal): never a block.
        self.assertEqual(self.run_hook(self.MAUVAIS, host=None), ('', []))
        self.assertEqual(self.run_hook(self.MAUVAIS, host=''), ('', []))

    def test_nothing_logged_without_numbered_question(self):
        out, journal = self.run_hook('Fait.\n\nRien à faire de ton côté.')
        self.assertEqual((out, journal), ('', []))

    def test_never_crashes(self):
        r = subprocess.run(['python3', str(HOOK)], input='pas du json', capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_registered_before_direct_answers_and_guarded(self):
        stop = [h['command'] for g in json.loads(HOOKS_JSON.read_text(encoding='utf-8'))['hooks']['Stop'] for h in g['hooks']]
        i = next(i for i, c in enumerate(stop) if 'format_questions.py' in c)
        j = next(i for i, c in enumerate(stop) if 'reponse_directe.py' in c)
        self.assertLess(i, j)
        self.assertIn('"disabled": true', stop[i])

    def test_silent_once_disabled(self):
        commande = next(h['command'] for g in json.loads(HOOKS_JSON.read_text(encoding='utf-8'))['hooks']['Stop']
                        for h in g['hooks'] if 'format_questions.py' in h['command'])
        with tempfile.TemporaryDirectory() as home:
            parc_dir = pathlib.Path(home) / 'Mon Studio' / '.parc'
            parc_dir.mkdir(parents=True)
            (parc_dir / 'cockpit.json').write_text(json.dumps({'page': 'x', 'disabled': True}, indent=2) + '\n')
            entree = json.dumps({'session_id': 'abc', 'transcript_path': transcript(home, self.MAUVAIS)})
            env = env_app(home, CLAUDE_PLUGIN_ROOT=str(ROOT))
            r = subprocess.run(['bash', '-c', commande], input=entree, capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(r.stdout, '')
            self.assertFalse((parc_dir / 'format-questions.jsonl').exists())
            (parc_dir / 'cockpit.json').write_text(json.dumps({'page': 'x'}, indent=2) + '\n')
            r = subprocess.run(['bash', '-c', commande], input=entree, capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(json.loads(r.stdout)['decision'], 'block')


class Rule(unittest.TestCase):
    TEXTE = (ROOT / 'regles' / 'format-reponses.md').read_text(encoding='utf-8')

    def test_rule_two_says_the_format(self):
        for mots in ('60 caractères au plus', '<la question précise>', '**<libellé de 4 mots au plus>**',
                     '« (recommandé) »', 'Si tu ne fais rien', 'règle 10'):
            self.assertIn(mots, self.TEXTE)
        self.assertNotIn('titrées en quelques mots', self.TEXTE)

    def test_its_example_passes_the_hook(self):
        exemple = self.TEXTE.split('Exemple :', 1)[1].split('»\n', 1)[0].replace('« ', '', 1)
        exemple = '\n'.join(x.strip() for x in exemple.splitlines())
        item = [it for it in parc.a_trancher('À trancher\n' + exemple)[0] if it['num']]
        self.assertEqual(len(item), 1)
        spec_h = importlib.util.spec_from_file_location('format_questions_essai', HOOK)
        hook = importlib.util.module_from_spec(spec_h)
        spec_h.loader.exec_module(hook)
        self.assertEqual(hook.ecarts(parc, item[0]), [])
        self.assertEqual(len(parc.options_entieres(item[0]['brut'])), 2)


if __name__ == '__main__':
    unittest.main()
