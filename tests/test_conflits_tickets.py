"""Tests of the ticket corrections of a settled conflict (/cockpit:conflits, PM 2026-11-11): python3 -m unittest
discover -s tests

- a draft per ticket touched, the description only (never a comment), the original kept: a dated addition at the top;
- the PM sees every draft grouped, before and after, each ticket by its title, no code; one form;
- set aside or change a ticket in free text; a word that points at no ticket or at several writes nothing;
- nothing pushed without the go; out of business hours (Paris, Monday to Friday, 8:00 to 20:00, holidays) the go is
  a preparation; just before each push the ticket is read again, a changed one does not go and the PM is told.
Never a call to Jira or Linear: the script does not talk to any tool. Synthetic data."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import datetime as dt
import io
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tickets_tests', ROOT / 'skills' / 'conflits' / 'scripts' / 'tickets.py')
tickets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets)
spec = importlib.util.spec_from_file_location('conflits_tickets_tests', ROOT / 'skills' / 'conflits' / 'scripts' / 'conflits.py')
conflits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conflits)

REGISTER = """# Registre des conflits

### C1 · Connexion par code
- **Détecté le** : 05/11/2026
- **Ancienne valeur** : code envoyé par e-mail (source : cadrage.md, 01/10/2026)
- **Nouvelle valeur** : code PIN à six chiffres (source : sources/2026-11-05-mail.md, 05/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : tranché le 06/11/2026 par Alex : remplacer

### C2 · Jour du comité
- **Détecté le** : 05/11/2026
- **Ancienne valeur** : mardi (source : cadrage.md, 01/10/2026)
- **Nouvelle valeur** : jeudi (source : sources/2026-11-05-mail.md, 05/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : tranché le 06/11/2026 par Alex : simple discussion

### C3 · Couleur du bouton
- **Détecté le** : 05/11/2026
- **Ancienne valeur** : bleu (source : cadrage.md, 01/10/2026)
- **Nouvelle valeur** : vert (source : sources/2026-11-05-mail.md, 05/11/2026)
- **Déjà communiqué au client** : non
- **Options** : remplacer · à confirmer avec le client · simple discussion
- **État** : ouvert
"""

ADF = {'type': 'doc', 'version': 1, 'content': [
    {'type': 'paragraph', 'content': [{'type': 'text', 'text': "L'utilisateur reçoit un code envoyé par e-mail."}]}]}
TUESDAY_10 = dt.datetime(2026, 11, 10, 10, 0)
WEDNESDAY_NIGHT = dt.datetime(2026, 11, 18, 23, 0)
DAY = '12/11/2026'


def studio(tool='Jira'):
    d = pathlib.Path(tempfile.mkdtemp(prefix='studio-tickets-'))
    (d / 'projet').mkdir()
    (d / 'projet' / 'conflits.md').write_text(REGISTER, encoding='utf-8')
    (d / 'projet' / 'fiche-projet.md').write_text(f"# Fiche projet\n\n- **Outil ticketing** : {tool}\n", encoding='utf-8')
    return d


def two_tickets():
    return [{'cle': 'PRJ-12', 'titre': 'Connexion à l\'application', 'statut': 'À faire', 'description': ADF},
            {'cle': 'PRJ-14', 'titre': 'Mot de passe oublié', 'statut': 'En cours', 'description': json.loads(json.dumps(ADF))}]


class BusinessHours(unittest.TestCase):
    def test_week_day_in_hours(self):
        self.assertTrue(tickets.business_hours(TUESDAY_10)['ouvre'])

    def test_bounds(self):
        self.assertFalse(tickets.business_hours(dt.datetime(2026, 11, 10, 7, 59))['ouvre'])
        self.assertTrue(tickets.business_hours(dt.datetime(2026, 11, 10, 8, 0))['ouvre'])
        self.assertTrue(tickets.business_hours(dt.datetime(2026, 11, 10, 19, 59))['ouvre'])
        self.assertFalse(tickets.business_hours(dt.datetime(2026, 11, 10, 20, 0))['ouvre'])

    def test_weekend_goes_to_monday(self):
        h = tickets.business_hours(dt.datetime(2026, 11, 14, 11, 0))
        self.assertFalse(h['ouvre'])
        self.assertEqual(h['prochain'], 'lundi 16/11 à 8 h')

    def test_holiday_is_closed(self):
        h = tickets.business_hours(dt.datetime(2026, 11, 11, 10, 0))        # 11 November
        self.assertFalse(h['ouvre'])
        self.assertEqual(h['prochain'], 'jeudi 12/11 à 8 h')

    def test_early_morning_same_day(self):
        self.assertEqual(tickets.business_hours(dt.datetime(2026, 11, 10, 6, 0))['prochain'], 'mardi 10/11 à 8 h')

    def test_easter_monday_and_ascension(self):
        self.assertIn(dt.date(2026, 4, 6), tickets.holidays(2026))
        self.assertIn(dt.date(2026, 5, 14), tickets.holidays(2026))
        self.assertIn(dt.date(2027, 3, 29), tickets.holidays(2027))

    def test_time_is_read_with_date_in_paris(self):
        done = subprocess.CompletedProcess([], 0, stdout='2026-11-10 09:30\n', stderr='')
        with unittest.mock.patch.object(tickets.subprocess, 'run', return_value=done) as run:
            now = tickets.now_paris()
        self.assertEqual(now, dt.datetime(2026, 11, 10, 9, 30))
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], 'date')
        self.assertEqual(kwargs['env']['TZ'], 'Europe/Paris')


class Drafts(unittest.TestCase):
    def setUp(self):
        self.s = studio()

    def test_dated_addition_keeps_the_original(self):
        r = tickets.prepare(self.s, 'C1', two_tickets(), today='2026-11-12')
        self.assertEqual(r['prepares'], 2)
        d = tickets.load(self.s)['brouillons'][0]
        self.assertEqual(d['mode'], 'ajout')
        self.assertEqual(d['apres']['content'][1:], ADF['content'])          # original nodes untouched
        first = tickets.plain(d['apres']['content'][0])
        self.assertTrue(first.startswith(f'Mise à jour du {DAY}'))
        self.assertIn('code PIN à six chiffres remplace code envoyé par e-mail', first)

    def test_only_a_case_settled_replace(self):
        self.assertEqual(tickets.prepare(self.s, 'C2', two_tickets())['prepares'], 0)
        self.assertEqual(tickets.prepare(self.s, 'C3', two_tickets())['prepares'], 0)
        self.assertTrue(tickets.prepare(self.s, 'C9', two_tickets())['erreurs'])

    def test_jira_description_must_be_adf(self):
        t = two_tickets()[:1]
        t[0]['description'] = 'texte brut'
        r = tickets.prepare(self.s, 'C1', t)
        self.assertEqual(r['prepares'], 0)
        self.assertIn('ADF', r['erreurs'][0])

    def test_linear_markdown(self):
        s = studio('Linear')
        r = tickets.prepare(s, 'C1', [{'cle': 'PRJB-3', 'titre': 'Écran de connexion', 'description': 'Le code part par e-mail.\n'}],
                            today='2026-11-12')
        self.assertEqual(r['prepares'], 1)
        d = tickets.load(s)['brouillons'][0]
        self.assertTrue(d['apres'].startswith(f'> **Mise à jour du {DAY} :** code PIN'))
        self.assertTrue(d['apres'].endswith('\n\nLe code part par e-mail.\n'))

    def test_no_second_addition(self):
        tickets.prepare(self.s, 'C1', two_tickets(), today='2026-11-12')
        already = tickets.load(self.s)['brouillons'][0]['apres']
        r = tickets.prepare(self.s, 'C1', [{'cle': 'PRJ-12', 'titre': 'Connexion', 'description': already}], today='2026-11-12')
        self.assertEqual(r['prepares'], 0)
        self.assertEqual(r['deja_corriges'], ['Connexion'])

    def test_never_a_second_addition(self):
        tickets.prepare(self.s, 'C1', two_tickets()[:1], today='2026-11-12')
        tickets.validate(self.s, 'Alex', change=[{'quoi': 'connexion', 'texte': 'autre texte'}], now=TUESDAY_10, today='2026-11-12')
        tickets.pushed(self.s, 'T1')
        pushed_desc = tickets.load(self.s)['brouillons'][0]['apres']
        r = tickets.prepare(self.s, 'C1', [{'cle': 'PRJ-12', 'titre': 'Connexion', 'description': pushed_desc}], today='2026-11-19')
        self.assertEqual(r['prepares'], 0)
        other = tickets.with_addition(ADF, 'Mise à jour du 12/11/2026 : code PIN à six chiffres remplace code envoyé par e-mail.', 'jira')
        r = tickets.prepare(self.s, 'C1', [{'cle': 'PRJ-30', 'titre': 'Autre écran', 'description': other}], today='2026-11-19')
        self.assertEqual((r['prepares'], r['deja_corriges']), (0, ['Autre écran']))

    def test_rich_description_is_never_rewritten(self):
        rich = {'type': 'doc', 'version': 1, 'content': [{'type': 'table', 'content': []}]}
        linked = {'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': [
            {'type': 'text', 'text': 'maquette', 'marks': [{'type': 'link', 'attrs': {'href': 'https://exemple.test'}}]}]}]}
        for desc in (rich, linked):
            t = [{'cle': 'PRJ-40', 'titre': 'Riche', 'description': desc, 'reecriture_permise': True, 'apres': 'texte'}]
            tickets.prepare(self.s, 'C1', t)
            self.assertEqual(tickets.load(self.s)['brouillons'][-1]['mode'], 'ajout')
        self.assertFalse(tickets.is_simple('Voir [la maquette](https://exemple.test)'))
        self.assertTrue(tickets.is_simple('# Titre\n\n- un\n- deux'))

    def test_rewrite_only_when_allowed_and_given(self):
        t = two_tickets()[:1]
        t[0]['apres'] = '# Connexion\n\nLe code PIN à six chiffres **remplace** le code par e-mail.\n\n- saisie\n- contrôle'
        tickets.prepare(self.s, 'C1', t)
        self.assertEqual(tickets.load(self.s)['brouillons'][-1]['mode'], 'ajout')
        t[0]['reecriture_permise'] = True
        tickets.prepare(self.s, 'C1', t)
        data = tickets.load(self.s)['brouillons']
        self.assertEqual(data[-1]['mode'], 'reecriture')
        self.assertEqual([n['type'] for n in data[-1]['apres']['content']], ['heading', 'paragraph', 'bulletList'])
        self.assertEqual(data[0]['etat'], 'remplace')          # the older draft of the same ticket is replaced

    def test_finished_ticket_is_only_named(self):
        t = two_tickets()
        t[1]['termine'] = True
        r = tickets.prepare(self.s, 'C1', t)
        self.assertEqual((r['prepares'], r['termines']), (1, ['Mot de passe oublié']))
        text = tickets.drafts(self.s)['texte']
        self.assertIn('Tickets terminés, jamais corrigés', text)
        self.assertIn('« Mot de passe oublié »', text)
        self.assertNotIn('terminés', tickets.drafts(self.s)['texte'])          # told once

    def test_preview_grouped_by_title_without_code(self):
        tickets.prepare(self.s, 'C1', two_tickets(), today='2026-11-12')
        r = tickets.drafts(self.s)
        self.assertEqual(r['n'], 2)
        self.assertIn('Conflit « Connexion par code »', r['texte'])
        self.assertIn("« Connexion à l'application » (Jira, à faire)", r['texte'])
        self.assertIn("Avant : L'utilisateur reçoit un code envoyé par e-mail.", r['texte'])
        self.assertIn('Après : ajout en tête', r['texte'])
        self.assertNotIn('PRJ-12', r['texte'] + r['formulaire']['question'])
        self.assertNotIn('C1', r['texte'])
        self.assertEqual(r['formulaire']['options'][0]['label'], 'Valider et pousser (Recommandé)')
        self.assertIn('aucun commentaire', r['formulaire']['question'])

    def test_no_draft_no_form(self):
        self.assertIsNone(tickets.drafts(self.s)['formulaire'])


class GoAndPush(unittest.TestCase):
    def setUp(self):
        self.s = studio()
        tickets.prepare(self.s, 'C1', two_tickets(), today='2026-11-12')

    def test_nothing_without_go(self):
        self.assertEqual(tickets.to_push(self.s, TUESDAY_10)['pousser'], [])
        r = tickets.verify(self.s, 'T1', ADF, now=TUESDAY_10)
        self.assertFalse(r['pousser'])

    def test_set_aside_and_change_in_free_text(self):
        r = tickets.validate(self.s, 'Alex', aside=['mot de passe'],
                             change=[{'quoi': 'connexion', 'texte': 'la connexion se fait par code PIN'}], now=TUESDAY_10,
                             today='2026-11-12')
        self.assertEqual((r['valides'], r['ecartes']), (1, 1))
        data = tickets.load(self.s)['brouillons']
        self.assertEqual(data[1]['etat'], 'ecarte')
        self.assertEqual(data[0]['ajout'], f'Mise à jour du {DAY} : la connexion se fait par code PIN')
        self.assertEqual(data[0]['apres']['content'][1:], ADF['content'])

    def test_unknown_or_ambiguous_word_writes_nothing(self):
        r = tickets.validate(self.s, 'Alex', aside=['facturation'], now=TUESDAY_10)
        self.assertEqual(r['point'], 'Rien écrit.')
        tickets.prepare(self.s, 'C1', [{'cle': 'PRJ-20', 'titre': 'Connexion par lien', 'description': ADF}])
        r = tickets.validate(self.s, 'Alex', aside=['connexion'], now=TUESDAY_10)
        self.assertIn('plusieurs tickets', r['erreurs'][0])
        self.assertTrue(all(d['etat'] == 'brouillon' for d in tickets.load(self.s)['brouillons']))

    def test_go_out_of_hours_is_a_preparation(self):
        r = tickets.validate(self.s, 'Alex', now=WEDNESDAY_NIGHT)
        self.assertIn('rien ne part', r['point'])
        self.assertIn('jeudi 19/11 à 8 h', r['point'])
        self.assertEqual(tickets.to_push(self.s, WEDNESDAY_NIGHT)['pousser'], [])
        self.assertFalse(tickets.verify(self.s, 'T1', ADF, now=WEDNESDAY_NIGHT)['pousser'])
        self.assertIn('à pousser à partir de jeudi 19/11', tickets.status(self.s, WEDNESDAY_NIGHT)['texte'])
        self.assertEqual(len(tickets.to_push(self.s, TUESDAY_10)['pousser']), 2)     # offered at the next pass

    def test_reread_unchanged_then_pushed(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        out = pathlib.Path(tempfile.mkdtemp()) / 'adf.json'
        r = tickets.verify(self.s, 'T1', json.loads(json.dumps(ADF)), out, now=TUESDAY_10)
        self.assertTrue(r['pousser'])
        self.assertEqual(r['format'], 'adf')
        pushed = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(pushed['content'][1:], ADF['content'])
        tickets.pushed(self.s, 'T1')
        self.assertEqual([x['id'] for x in tickets.to_push(self.s, TUESDAY_10)['pousser']], ['T2'])

    def test_reread_changed_is_not_pushed_and_said(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        edited = json.loads(json.dumps(ADF))
        edited['content'][0]['content'][0]['text'] += ' Ajouté par le client.'
        out = pathlib.Path(tempfile.mkdtemp()) / 'adf.json'
        r = tickets.verify(self.s, 'T1', edited, out, now=TUESDAY_10)
        self.assertFalse(r['pousser'])
        self.assertIn("a changé dans Jira depuis le brouillon : rien n'est poussé", r['message'])
        self.assertFalse(out.exists())
        self.assertIn('changé depuis le brouillon', tickets.status(self.s, TUESDAY_10)['texte'])

    def test_reread_after_push(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        r = tickets.pushed(self.s, 'T1', reread={'key': 'PRJ-12', 'fields': {'description': ADF}})
        self.assertIn("n'est pas corrigé", r['message'])
        good = tickets.load(self.s)['brouillons'][0]['apres']
        self.assertIn('corrigé', tickets.pushed(self.s, 'T1', reread={'key': 'PRJ-12', 'fields': {'description': good}})['message'])
        self.assertEqual(tickets.load(self.s)['brouillons'][0]['etat'], 'pousse')

    def test_reread_accepts_the_tool_shape(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        r = tickets.verify(self.s, 'T1', {'key': 'PRJ-12', 'fields': {'summary': 'x', 'description': ADF}}, now=TUESDAY_10)
        self.assertTrue(r['pousser'])

    def test_finished_since_the_go_is_not_pushed(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        done = {'key': 'PRJ-12', 'fields': {'status': {'name': 'Terminé', 'statusCategory': {'key': 'done'}}, 'description': ADF}}
        r = tickets.verify(self.s, 'T1', done, now=TUESDAY_10)
        self.assertFalse(r['pousser'])
        self.assertIn('terminé depuis le brouillon', r['message'])
        self.assertEqual(tickets.load(self.s)['brouillons'][0]['etat'], 'termine')

    def test_rewrite_needs_an_internal_status_at_push_time(self):
        (self.s / 'projet' / 'fiche-projet.md').write_text('- **Outil ticketing** : Jira\n- **Statuts internes** : À  rédiger\n',
                                                           encoding='utf-8')
        t = two_tickets()[:1]
        t[0].update(statut='À  rédiger', reecriture_permise=True, apres='La connexion se fait par code PIN.')
        tickets.prepare(self.s, 'C1', t)
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        rid = tickets.load(self.s)['brouillons'][-1]['id']
        moved = {'key': 'PRJ-12', 'fields': {'status': {'name': 'Validé client', 'statusCategory': {'key': 'indeterminate'}}, 'description': ADF}}
        r = tickets.verify(self.s, rid, moved, now=TUESDAY_10)
        self.assertFalse(r['pousser'])
        self.assertIn("n'est plus dans un statut interne", r['message'])
        self.assertEqual(tickets.load(self.s)['brouillons'][-1]['mode'], 'reecriture')     # « À  rédiger » was recognized
        self.assertEqual(tickets.load(self.s)['brouillons'][-1]['etat'], 'change')

    def test_a_failed_reread_never_pushes_nor_changes_the_state(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        for bad in (None, {}, [], {'errorMessages': ['not found']}):
            r = tickets.verify(self.s, 'T1', bad, now=TUESDAY_10)
            self.assertFalse(r['pousser'], bad)
            self.assertIn("n'a pas pu être relu", r['message'])
        self.assertEqual(tickets.load(self.s)['brouillons'][0]['etat'], 'valide')

    def test_same_ticket_shape_from_search_and_view(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        viewed = json.loads(json.dumps(ADF))
        viewed['content'][0]['attrs'] = {'localId': 'abc-123'}
        self.assertTrue(tickets.verify(self.s, 'T1', {'key': 'PRJ-12', 'fields': {'description': viewed}}, now=TUESDAY_10)['pousser'])
        as_string = {'key': 'PRJ-12', 'fields': {'description': json.dumps(ADF)}}
        self.assertTrue(tickets.verify(self.s, 'T1', as_string, now=TUESDAY_10)['pousser'])

    def test_failed_push_stays_validated(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        tickets.pushed(self.s, 'T1', failure='acli non authentifié')
        self.assertEqual(len(tickets.to_push(self.s, TUESDAY_10)['pousser']), 2)

    def test_all_aside(self):
        r = tickets.validate(self.s, 'Alex', all_aside=True, now=TUESDAY_10)
        self.assertEqual((r['valides'], r['ecartes']), (0, 2))
        self.assertEqual(tickets.status(self.s, TUESDAY_10)['texte'], '1 conflit tranché dont les tickets restent à chercher.')
        tickets.prepare(self.s, 'C1', [], mark_searched=True)
        self.assertEqual(tickets.status(self.s, TUESDAY_10)['texte'], '')

    def test_only_the_state_file_is_written_in_the_studio(self):
        tickets.validate(self.s, 'Alex', now=TUESDAY_10)
        tickets.verify(self.s, 'T1', ADF, pathlib.Path(tempfile.mkdtemp()) / 'x.json', now=TUESDAY_10)
        files = sorted(str(p.relative_to(self.s)) for p in self.s.rglob('*') if p.is_file())
        self.assertEqual(files, ['projet/.conflits/tickets.json', 'projet/conflits.md', 'projet/fiche-projet.md'])
        self.assertEqual((self.s / 'projet' / 'conflits.md').read_text(encoding='utf-8'), REGISTER)

    def test_next_pass_offers_the_push(self):
        tickets.prepare(self.s, 'C1', [], mark_searched=True)
        tickets.validate(self.s, 'Alex', now=WEDNESDAY_NIGHT)
        (self.s / '.claude').mkdir()
        (self.s / '.claude' / '.studio-manifest.json').write_text('{}', encoding='utf-8')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            conflits.main(['attente', str(self.s)])
        self.assertIn('Tickets : 2 tickets validés, à pousser', out.getvalue())

    def test_script_never_calls_a_ticketing_tool(self):
        text = (ROOT / 'skills' / 'conflits' / 'scripts' / 'tickets.py').read_text(encoding='utf-8')
        for word in ('acli', 'urllib', 'http', 'requests', 'socket'):
            self.assertNotIn(f'import {word}', text)
        self.assertNotIn("'acli'", text)


class ProjectSheet(unittest.TestCase):
    def sheet(self, text):
        d = pathlib.Path(tempfile.mkdtemp(prefix='studio-fiche-'))
        (d / 'projet').mkdir()
        (d / 'projet' / 'fiche-projet.md').write_text(text, encoding='utf-8')
        return d

    def test_jira_rows_as_studios_write_them(self):
        cases = {'| **Jira** | PRJ — https://exemple.atlassian.net/jira/software/projects/PRJ/boards/12 |': 'PRJ',
                 '| **Jira** | https://exemple.atlassian.net/browse/SHOP |': 'SHOP',
                 '| **Jira** | Projet `ABC`, board 12 |': 'ABC',
                 '| **Jira** | [DEF — Accueil](https://exemple.atlassian.net/jira/software/projects/DEF/boards/1) |': 'DEF',
                 '| **Jira** | GHI |': 'GHI'}
        for row, key in cases.items():
            self.assertEqual(tickets.project_ref(self.sheet(f'# Fiche\n\n| Champ | Valeur |\n|---|---|\n{row}\n')),
                             {'outil': 'jira', 'projet': key}, row)

    def test_no_tool(self):
        for row in ('| **Jira** | _N/A_ |', '| **Jira** | _Non utilisé_ |', '| **Jira** | _À compléter_ |', ''):
            self.assertIsNone(tickets.project_ref(self.sheet(f'# Fiche\n\n{row}\n'))['outil'], row)

    def test_template_row_is_not_a_choice(self):
        template = '| **Outil ticketing** | `linear` ou `jira` — détermine quel MCP est utilisé | `/studio:recette` |\n'
        self.assertIsNone(tickets.project_ref(self.sheet('| **Jira** | _À compléter_ |\n' + template))['outil'])
        self.assertEqual(tickets.project_ref(self.sheet('| **Jira** | _N/A_ |\n| **Outil ticketing** | `linear` | `/studio:recette` |\n')),
                         {'outil': 'linear', 'projet': None})
        self.assertEqual(tickets.project_ref(self.sheet('| **Jira** | Jira + JSM (à renseigner : URL espace) |\n'
                                                        '| **Outil ticketing** | `jira` (Jira + JSM) | `/studio:recette` |\n')),
                         {'outil': 'jira', 'projet': None})
        self.assertEqual(tickets.project_ref(self.sheet('| **Jira** | — (non utilisé sur ce projet) |\n'))['outil'], None)

    def test_jira_without_key_asks_for_it(self):
        s = studio('Jira')
        (s / 'projet' / 'fiche-projet.md').write_text('| **Outil ticketing** | `jira` | `/studio:recette` |\n', encoding='utf-8')
        r = tickets.search(s)
        self.assertEqual(r['conflits'], [])
        self.assertIn("La clé du projet Jira n'est pas sur la fiche", r['message'])

    def test_declared_linear_with_team(self):
        r = tickets.project_ref(self.sheet('- **Outil ticketing** : Linear\n- **Équipe Linear** : Produit\n'))
        self.assertEqual(r, {'outil': 'linear', 'projet': 'Produit'})

    def test_internal_statuses(self):
        d = self.sheet('- **Statuts internes** : À rédiger, Brouillon\n')
        self.assertEqual(tickets.internal_statuses(d), {'a rediger', 'brouillon'})


class Search(unittest.TestCase):
    def setUp(self):
        self.s = studio('Jira')
        (self.s / 'projet' / 'fiche-projet.md').write_text(
            '# Fiche\n\n| **Jira** | https://exemple.atlassian.net/browse/PRJ |\n- **Statuts internes** : À rédiger\n',
            encoding='utf-8')

    def test_queries_and_cost(self):
        r = tickets.search(self.s)
        self.assertEqual([c['cas'] for c in r['conflits']], ['C1'])
        c = r['conflits'][0]
        self.assertEqual(c['phrase'], 'code envoyé par e-mail')
        self.assertIn('envoyé', c['mots'])
        self.assertNotIn('code', [norm.lower() for norm in c['mots']])      # the new value says « code » too
        self.assertTrue(c['jql_ouverts'].startswith('project = "PRJ" AND statusCategory != Done AND'))
        self.assertIn('statusCategory = Done', c['jql_termines'])
        self.assertIn('8 tickets ouverts lus au plus', r['message'])
        self.assertLess(r['cout']['pourcent_semaine'], 0.05)

    def test_word_without_letter_is_not_searched(self):
        case = {'ancienne': {'texte': 'code ---- envoyé'}, 'nouvelle': {'texte': 'PIN'}}
        self.assertNotIn('----', tickets.terms(case)['mots'])

    def test_estimate_line_in_conflits_estimer(self):
        (self.s / '.claude').mkdir()
        (self.s / '.claude' / '.studio-manifest.json').write_text('{}', encoding='utf-8')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            conflits.main(['estimer', str(self.s)])
        self.assertIn('Retrouver les tickets de', out.getvalue())

    def folder(self):
        f = pathlib.Path(tempfile.mkdtemp(prefix='tickets-lus-'))
        opened = [{'key': f'PRJ-{i}', 'fields': {'summary': f'Écran {i}', 'status': {'name': 'À faire', 'statusCategory': {'key': 'new'}},
                                                'description': ADF}} for i in range(1, 12)]
        opened[0]['fields']['status'] = {'name': 'À rédiger', 'statusCategory': {'key': 'new'}}
        (f / 'C1.json').write_text(json.dumps(opened), encoding='utf-8')
        done = [{'key': 'PRJ-90', 'fields': {'summary': 'Ancienne connexion', 'status': {'name': 'Terminé', 'statusCategory': {'key': 'done'}}}}]
        (f / 'C1-termines.json').write_text(json.dumps({'issues': done}), encoding='utf-8')
        return f

    def test_batch_is_capped_and_says_who_may_be_rewritten(self):
        f = self.folder()
        text = tickets.batch_text(self.s, f, 1)
        self.assertEqual(text.count('### Ticket'), tickets.OPEN_PER_CASE)
        self.assertIn('PRJ-1 · Écran 1\nStatut : À rédiger (statut interne : réécriture permise)', text)
        self.assertNotIn('PRJ-90', text)
        self.assertIn(str(f / 'jugements-1.json'), text)
        self.assertLess(len(text), tickets.BATCH_CHARS + 500)

    def test_prepare_from_judgments(self):
        f = self.folder()
        (f / 'jugements-1.json').write_text(json.dumps([
            {'cas': 'C1', 'cle': 'PRJ-1', 'touche': True, 'apres': 'La connexion se fait par code PIN.'},
            {'cas': 'C1', 'cle': 'PRJ-2', 'touche': True, 'apres': 'ignoré : statut non interne'},
            {'cas': 'C1', 'cle': 'PRJ-3', 'touche': False}]), encoding='utf-8')
        r = tickets.prepare_folder(self.s, f, today='2026-11-12')
        self.assertEqual((r['prepares'], r['termines']), (2, ['Ancienne connexion']))
        d = {x['cle']: x for x in tickets.load(self.s)['brouillons']}
        self.assertEqual(d['PRJ-1']['mode'], 'reecriture')
        self.assertEqual(d['PRJ-2']['mode'], 'ajout')
        self.assertNotIn('PRJ-3', d)
        self.assertEqual(tickets.search(self.s)['conflits'], [])                # searched once
        self.assertEqual([c['cas'] for c in tickets.search(self.s, ['C1'])['conflits']], ['C1'])

    def test_linear_shapes(self):
        t = tickets.normalize({'identifier': 'PRJB-3', 'title': 'Écran', 'state': {'name': 'Done', 'type': 'completed'}, 'description': 'x'})
        self.assertEqual((t['cle'], t['termine']), ('PRJB-3', True))
        t = tickets.normalize({'identifier': 'PRJB-4', 'title': 'Écran', 'status': 'In Progress', 'description': 'x'})
        self.assertFalse(t['termine'])


class Skill(unittest.TestCase):
    def test_every_command_of_the_skill_exists(self):
        text = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')
        used = set(__import__('re').findall(r'tickets\.py (\w+)', text))
        self.assertGreaterEqual(used, {'recherche', 'dossier', 'lot', 'preparer', 'brouillons', 'valider', 'pousser',
                                       'verifier', 'pousse'})
        for cmd in used:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as e:
                    tickets.main([cmd, '--help'])
            self.assertEqual(e.exception.code, 0, cmd)

    def test_skill_rules(self):
        text = (ROOT / 'skills' / 'conflits' / 'SKILL.md').read_text(encoding='utf-8')
        for rule in ('jamais un commentaire', 'heures ouvrées', 'relu dans l\'outil', 'ajout daté en tête',
                     'Statuts internes', 'terminé n\'est jamais corrigé', 'Ni l\'un ni l\'autre'):
            self.assertIn(rule, text)
        self.assertNotIn('backlog', text.lower())


if __name__ == '__main__':
    unittest.main()
