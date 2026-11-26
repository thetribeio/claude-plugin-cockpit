"""Tests: the morning brief inside Mon Studio (skills/mon-studio/scripts/matin.py, projets.py, 2026-11-05):
python3 -m unittest discover -s tests

A scheduled task (the PM's own, the only place with an LLM) writes ~/Mon Studio/matin.json each morning. Mon Studio reads
it without an LLM: `matin.py` validates and truncates it (never raises), « Fait » is kept for good in matin-etat.json,
the meetings without a minute become `reunion` lines of the list by project, and the pinned page shows the blocks.

Every file lives in a temporary folder: the PM's real ~/Mon Studio is never read."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import datetime as dt
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
from unittest import mock

from test_cockpit_projets import Base, MAIL, WORK, ASKER, MONDAY, utc

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONNECTOR = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'mcp_mon_studio.py'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'


def iso(t):
    return dt.datetime.fromtimestamp(t).isoformat(timespec='seconds')


def item(i, **extra):
    return dict({'cle': f'k{i}', 'titre': f'Titre {i}', 'phrase': f'Phrase {i}.', 'source': 'gmail',
                 'lien': f'https://example.org/{i}', 'projet': 'Alpha'}, **extra)


class MatinBase(Base):
    def setUp(self):
        super().setUp()
        self.m = self.p._charger_matin()

    def write(self, **champs):
        point = dict({'genere_le': iso(MONDAY), 'jour': 'lourde', 'agenda': [], 'a_traiter': [], 'regle': [],
                      'preparer_demain': [], 'reunions_sans_cr': []}, **champs)
        (self.mon_studio / 'matin.json').write_text(json.dumps(point), encoding='utf-8')

    def state_file(self):
        return self.mon_studio / 'matin-etat.json'


class Reading(MatinBase):
    def test_absent_unreadable_or_stale_is_not_yet_passed(self):
        self.assertEqual(self.m.pour_la_page(MONDAY), {'etat': 'pas_passe'})
        (self.mon_studio / 'matin.json').write_text('{oops', encoding='utf-8')
        self.assertEqual(self.m.pour_la_page(MONDAY), {'etat': 'pas_passe'})
        (self.mon_studio / 'matin.json').write_text('["pas", "un", "objet"]', encoding='utf-8')
        self.assertEqual(self.m.pour_la_page(MONDAY), {'etat': 'pas_passe'})
        self.write(genere_le='pas une date', a_traiter=[item(1)])
        self.assertEqual(self.m.pour_la_page(MONDAY), {'etat': 'pas_passe'})
        # Yesterday's point is never shown, content or not.
        self.write(genere_le=iso(MONDAY - 86400), a_traiter=[item(1)])
        self.assertEqual(self.m.pour_la_page(MONDAY), {'etat': 'pas_passe'})
        self.assertIsNone(self.m.lire(MONDAY))

    def test_a_valid_point(self):
        self.write(agenda=[{'heure': '09:30', 'titre': 'Point équipe', 'projet': 'Alpha'}], a_traiter=[item(1)],
                   regle=[{'qui': 'Léo', 'quand': 'hier', 'quoi': 'devis envoyé', 'lien': 'https://example.org/r'}],
                   preparer_demain=[{'titre': 'Relire le devis', 'phrase': 'Avant la réunion.', 'lien': ''}],
                   reunions_sans_cr=[{'cle': 'r1', 'projet': 'Alpha', 'titre': 'Atelier', 'date': '2026-10-30', 'lien': ''}])
        p = self.m.pour_la_page(MONDAY)
        self.assertEqual((p['etat'], p['jour']), ('ok', 'lourde'))
        self.assertEqual(p['agenda'], [{'heure': '09:30', 'titre': 'Point équipe', 'projet': 'Alpha'}])
        self.assertEqual(p['a_traiter'], [item(1)])
        self.assertEqual(p['regle'][0]['quoi'], 'devis envoyé')
        self.assertEqual(p['preparer_demain'][0]['titre'], 'Relire le devis')
        self.assertEqual(p['reunions_sans_cr'][0]['cle'], 'r1')

    def test_blocks_are_cut_at_their_ceilings(self):
        self.write(a_traiter=[item(i) for i in range(12)],
                   regle=[{'qui': 'P', 'quand': 'hier', 'quoi': f'fait {i}', 'lien': ''} for i in range(9)],
                   preparer_demain=[{'titre': f'D{i}', 'phrase': '', 'lien': ''} for i in range(5)])
        p = self.m.pour_la_page(MONDAY)
        self.assertEqual((len(p['a_traiter']), len(p['regle']), len(p['preparer_demain'])), (7, 5, 3))
        self.assertEqual([x['cle'] for x in p['a_traiter']], [f'k{i}' for i in range(7)])
        self.assertEqual((self.m.PLAFOND_A_TRAITER, self.m.PLAFOND_REGLE, self.m.PLAFOND_PREPARER_DEMAIN), (7, 5, 3))
        with mock.patch.object(self.m, 'PLAFOND_A_TRAITER', 2):
            self.assertEqual(len(self.m.pour_la_page(MONDAY)['a_traiter']), 2)

    def test_a_missing_field_costs_an_item_or_a_block_never_an_exception(self):
        self.write(jour='bizarre', agenda='pas une liste',
                   a_traiter=[{'titre': 'sans clé'}, 'pas un objet', {'cle': 'k', 'titre': ''}, item(2, source='fax',
                              lien='http://pas-https.example.org'), item(3)],
                   regle=None, preparer_demain=[{'phrase': 'sans titre'}])
        p = self.m.pour_la_page(MONDAY)
        self.assertEqual((p['etat'], p['jour']), ('ok', 'normale'))
        self.assertEqual((p['agenda'], p['regle'], p['preparer_demain']), ([], [], []))
        self.assertEqual([x['cle'] for x in p['a_traiter']], ['k2', 'k3'])
        self.assertEqual((p['a_traiter'][0]['source'], p['a_traiter'][0]['lien']), ('', ''))
        # Without a block at all.
        (self.mon_studio / 'matin.json').write_text(json.dumps({'genere_le': iso(MONDAY)}), encoding='utf-8')
        p = self.m.pour_la_page(MONDAY)
        self.assertEqual((p['etat'], p['a_traiter'], p['agenda']), ('ok', [], []))

    def test_an_old_file_with_entre_studio_is_read_without_it(self):
        # The ingestion part is computed live by projets.py (Q23 of 2026-11-06): an old matin.json that still carries
        # `entre_studio` is read, the field ignored.
        self.write(a_traiter=[item(1)], entre_studio=[{'cle': 'e1', 'projet': 'Alpha', 'phrase': 'Rangé.', 'lien': 'projet/c.md'}])
        p = self.m.pour_la_page(MONDAY)
        self.assertEqual((p['etat'], [x['cle'] for x in p['a_traiter']]), ('ok', ['k1']))
        self.assertNotIn('entre_studio', p)
        self.assertFalse(hasattr(self.m, 'PLAFOND_ENTRE_STUDIO'))

    def test_a_link_is_https_or_a_safe_relative_path(self):
        ok = ['projet/a.md', 'reunions/2026-11-05 copil.md', 'a']
        bad = ['/etc/passwd', '~/x', 'a/../b', '..', './a', 'a//b', 'C:\\x', 'a\\b', 'file:///x', 'javascript:alert(1)',
               'http://x.org', 'a\nb', 'x' * 501, '', None, 3]
        for v in ok:
            self.assertEqual(self.m._lien_ou_chemin(v), v, v)
        for v in bad:
            self.assertEqual(self.m._lien_ou_chemin(v), '', repr(v))
        self.write(a_traiter=[item(1, source='studio', lien='projet/a.md'), item(2, lien='../a.md')],
                   regle=[{'qui': 'P', 'quand': 'hier', 'quoi': 'fait', 'lien': 'projet/a.md'},
                          {'qui': 'P', 'quand': 'hier', 'quoi': 'fait', 'lien': '../a.md'}])
        p = self.m.pour_la_page(MONDAY)
        self.assertEqual([(x['source'], x['lien']) for x in p['a_traiter']], [('studio', 'projet/a.md'), ('gmail', '')])
        self.assertEqual([x['lien'] for x in p['regle']], ['projet/a.md', ''], 'réglé keeps a studio path, like à traiter')

    def test_a_long_title_is_cut(self):
        self.write(a_traiter=[item(1, titre='mot ' * 100)])
        t = self.m.pour_la_page(MONDAY)['a_traiter'][0]['titre']
        self.assertLessEqual(len(t), self.m.TITRE_MAX)


class Done(MatinBase):
    def test_a_done_item_leaves_and_the_others_stay(self):
        self.write(a_traiter=[item(1), item(2)])
        self.assertEqual(self.m.fait('k1', MONDAY), {'fait': 'k1'})
        self.assertEqual([x['cle'] for x in self.m.pour_la_page(MONDAY)['a_traiter']], ['k2'])
        state = json.loads(self.state_file().read_text(encoding='utf-8'))
        self.assertEqual(list(state['fermes']), ['k1'])
        self.assertEqual(state['fermes']['k1']['le'], dt.date.fromtimestamp(MONDAY).isoformat())

    def test_unknown_or_already_done_is_refused(self):
        self.write(a_traiter=[item(1)])
        with self.assertRaises(ValueError):
            self.m.fait('nope', MONDAY)
        self.m.fait('k1', MONDAY)
        with self.assertRaises(ValueError):
            self.m.fait('k1', MONDAY)
        self.assertFalse((self.mon_studio / 'matin-etat.json.tmp').exists())

    def test_nothing_is_done_without_todays_point(self):
        with self.assertRaises(ValueError):
            self.m.fait('k1', MONDAY)
        self.write(genere_le=iso(MONDAY - 86400), a_traiter=[item(1)])
        with self.assertRaises(ValueError):
            self.m.fait('k1', MONDAY)
        self.assertFalse(self.state_file().exists())

    def test_a_done_item_stays_done_when_the_next_morning_writes_it_again(self):
        # PM, 2026-11-09: « Fait » holds; the morning task may write the same key the next day, it does not come back.
        self.write(a_traiter=[item(1)])
        self.m.fait('k1', MONDAY)
        tuesday = MONDAY + 86400
        self.write(genere_le=iso(tuesday), a_traiter=[item(1), item(2)])
        self.assertEqual([x['cle'] for x in self.m.pour_la_page(tuesday)['a_traiter']], ['k2'])
        self.m.fait('k2', tuesday)
        state = json.loads(self.state_file().read_text(encoding='utf-8'))
        self.assertEqual(sorted(state['fermes']), ['k1', 'k2'])

    def test_a_corrupt_state_file_filters_nothing(self):
        self.write(a_traiter=[item(1)])
        self.state_file().write_text('{oops', encoding='utf-8')
        self.assertEqual(len(self.m.pour_la_page(MONDAY)['a_traiter']), 1)
        self.assertEqual(self.m.fait('k1', MONDAY), {'fait': 'k1'})

    def test_cli(self):
        env = dict(os.environ, MON_STUDIO=str(self.mon_studio))
        script = str(ROOT / 'skills' / 'mon-studio' / 'scripts' / 'matin.py')
        r = subprocess.run(['python3', script], capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'Point du matin pas encore passé.'))
        r = subprocess.run(['python3', script, 'fait', 'x'], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn('Refusé', r.stdout)


class Meetings(MatinBase):
    def reunion(self, cle='r1', projet='Alpha', titre='Atelier cadrage', date='2026-10-30'):
        return {'cle': cle, 'projet': projet, 'titre': titre, 'date': date, 'lien': ''}

    def lines(self, out, type_='reunion', name='Alpha'):
        b = self.block(out, name)
        return [l for l in b['lignes'] if l['type'] == type_] if b else []

    def test_a_meeting_without_minute_is_a_reunion_line_for_the_pm(self):
        self.write(reunions_sans_cr=[self.reunion(), self.reunion('r2', 'Inconnu', 'Autre projet')])
        out = self.compute()
        l = self.lines(out)
        self.assertEqual([(x['titre'], x['detail'], x['session'], x['repli']) for x in l],
                         [('Atelier cadrage', '2026-10-30', MAIL, False)])
        self.assertRegex(l[0]['cle'], r'^[0-9a-f]{12}$')
        self.assertIsNone(self.block(out, 'Inconnu'))
        md = (self.mon_studio / 'projets.md').read_text(encoding='utf-8')
        self.assertIn('- Atelier cadrage · réunion sans compte rendu · ', md)

    def test_a_member_has_no_reunion_line(self):
        self.write(reunions_sans_cr=[self.reunion()])
        with mock.patch.dict(os.environ, {'COCKPIT_IDENTITE': 'Sam Autre'}):
            out = self.compute()
        self.assertEqual(self.types(out), [])
        self.assertEqual(self.p.lire_etat(), {}, 'not even noted')

    def test_a_stale_or_absent_point_adds_none_and_keeps_the_open_ones(self):
        self.assertEqual(self.lines(self.compute()), [])
        self.write(reunions_sans_cr=[self.reunion()])
        self.assertEqual(len(self.lines(self.compute())), 1)
        self.write(genere_le=iso(MONDAY - 86400), reunions_sans_cr=[])
        self.assertEqual(len(self.lines(self.compute())), 1, "yesterday's point says nothing: the open line stays")

    def test_a_meeting_the_point_no_longer_lists_is_closed_by_its_source(self):
        self.write(reunions_sans_cr=[self.reunion()])
        self.compute()
        self.write(reunions_sans_cr=[])
        out = self.compute(MONDAY + 60)
        self.assertEqual(self.lines(out), [])
        self.assertEqual(self.block(out)['fermees_titres'], ['Atelier cadrage'])
        self.write(reunions_sans_cr=[self.reunion()])
        self.assertEqual(len(self.lines(self.compute(MONDAY + 120))), 1, 'listed again: reopened')

    def test_closed_by_hand_with_the_same_mechanism_and_it_stays_closed(self):
        self.write(reunions_sans_cr=[self.reunion()])
        cle = self.lines(self.compute())[0]['cle']
        self.assertEqual(self.p.fermer(cle, MONDAY + 30), {'ferme': cle})
        out = self.compute(MONDAY + 60)
        self.assertEqual(self.lines(out), [])
        self.assertEqual(self.block(out)['fermees_titres'], ['Atelier cadrage'])
        state = json.loads((self.mon_studio / '.parc' / 'projets-etat.json').read_text(encoding='utf-8'))
        self.assertEqual(state['lignes'][cle]['par'], 'main')

    def test_the_project_is_matched_without_accents_or_case(self):
        self.write(reunions_sans_cr=[self.reunion(projet='ALPHA')])
        self.assertEqual(len(self.lines(self.compute())), 1)

    def test_no_alert_type_is_left(self):
        self.assertNotIn('alerte', self.p.ORDRE_TYPES)


class ForThePage(MatinBase):
    def test_a_relative_link_carries_its_studio_folder_and_no_session_is_attached(self):
        self.write(a_traiter=[item(1), item(2, source='studio', lien='projet/a.md'),
                              item(3, source='studio', lien='projet/b.md', projet='Inconnu')],
                   entre_studio=[{'cle': 'e1', 'projet': 'ALPHA', 'phrase': 'Rangé.', 'lien': 'projet/c.md'}])
        out = self.p.matin_pour_la_page(MONDAY, self.metas)
        self.assertEqual([x.get('dossier', '-') for x in out['a_traiter']], ['-', self.alpha, None])
        self.assertEqual(out['entre_studio'], [], 'the old field is never shown: the live part replaces it')
        for x in out['a_traiter']:
            self.assertNotIn('session', x)

    def test_a_studio_item_moved_to_regle_keeps_its_file_link(self):
        self.write(regle=[{'qui': 'Léo', 'quand': 'ce matin', 'quoi': 'CR rangé', 'lien': 'projet/cr.md', 'projet': 'Alpha'},
                          {'qui': 'Dominique', 'quand': 'hier', 'quoi': 'Mail parti', 'lien': 'https://mail.google.com/x'},
                          {'qui': 'Jo', 'quand': 'hier', 'quoi': 'Évasion', 'lien': '../x.md', 'projet': 'Alpha'}])
        out = self.p.matin_pour_la_page(MONDAY, self.metas)
        self.assertEqual([(x['lien'], x.get('dossier', '-')) for x in out['regle']],
                         [('projet/cr.md', self.alpha), ('https://mail.google.com/x', '-'), ('', '-')])

    def test_only_a_known_studio_opens_a_file(self):
        self.assertEqual(self.p.dossier_du_matin(self.alpha, self.metas), self.alpha)
        for d in (str(self.root), '', None, '/etc'):
            with self.assertRaises(ValueError):
                self.p.dossier_du_matin(d, self.metas)

    def test_not_yet_passed_carries_nothing_else(self):
        self.assertEqual(self.p.matin_pour_la_page(MONDAY, self.metas), {'etat': 'pas_passe', 'entre_studio': [], 'demandes': []})


class Connector(MatinBase):
    def connector(self):
        old = os.environ.get('MON_STUDIO')
        os.environ['MON_STUDIO'] = str(self.mon_studio)
        try:
            spec = importlib.util.spec_from_file_location('mcp_matin_essai', CONNECTOR)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
        finally:
            if old is None:
                os.environ.pop('MON_STUDIO', None)
            else:
                os.environ['MON_STUDIO'] = old
        app, tr = self.root / 'app', self.root / 'tr'
        app.mkdir()
        tr.mkdir()
        m.parc.APP, m.parc.TRANSCRIPTS = app, tr
        m.parc.pastilles = lambda: None
        return m

    def call(self, m, *msgs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            for i, (name, args) in enumerate(msgs):
                m.traiter({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}
                          if name != 'list' else {'jsonrpc': '2.0', 'id': i, 'method': 'tools/list'})
        return [json.loads(l) for l in buf.getvalue().splitlines()]

    def test_lignes_carries_matin_and_survives_a_broken_matin(self):
        m = self.connector()
        self.assertEqual(m.lignes()['matin'], {'etat': 'pas_passe', 'entre_studio': [], 'demandes': [], 'sans_reponse': []})
        self.write(genere_le=iso(time.time()), a_traiter=[item(1)])
        d = m.lignes()
        self.assertEqual((d['matin']['etat'], [x['cle'] for x in d['matin']['a_traiter']]), ('ok', ['k1']))
        with mock.patch.object(m, 'charger_projets', side_effect=SyntaxError('cassé')):
            d = m.lignes()
        self.assertIsNone(d['matin'])
        self.assertIn('lignes', d)

    def test_matin_ecrire_writes_matin_json_only_after_the_same_check(self):
        # 2026-11-10: the morning tasks write the point through the connector, never a file tool nor a heredoc.
        m = self.connector()
        outil = [o for o in self.call(m, ('list', None))[0]['result']['tools'] if o['name'] == 'matin_ecrire'][0]
        self.assertFalse(outil['annotations']['readOnlyHint'])
        point = {'genere_le': iso(MONDAY), 'a_traiter': [item(1, titre='l\'été {"x"}')]}
        r = self.call(m, ('matin_ecrire', {'contenu': point}), ('matin_ecrire', {'contenu': {'genere_le': 'hier'}}),
                      ('matin_ecrire', {'contenu': '{"genere_le": "2026-11-02T07:30:00"}'}))
        self.assertEqual(json.loads(r[0]['result']['content'][0]['text']), {'ecrit': True, 'compte_rendu': 'matin.json écrit'})
        self.assertTrue(r[1]['result']['isError'])
        self.assertIn('Refusé : genere_le manquant ou illisible', r[1]['result']['content'][0]['text'])
        self.assertTrue(r[2]['result']['isError'], 'an object, never a text')
        self.assertEqual(json.loads((self.mon_studio / 'matin.json').read_text(encoding='utf-8')), point)
        self.assertEqual(sorted(x.name for x in self.mon_studio.iterdir() if x.name.startswith('matin')), ['matin.json'])

    def test_clore_with_matin_marks_done_and_refuses_the_rest(self):
        m = self.connector()
        self.write(genere_le=iso(time.time()), a_traiter=[item(1)])
        listed, ok, again, unknown, empty, hex_line = self.call(
            m, ('list', None), ('clore', {'cle': 'k1', 'matin': True}), ('clore', {'cle': 'k1', 'matin': True}),
            ('clore', {'cle': 'nope', 'matin': True}), ('clore', {'cle': '', 'matin': True}), ('clore', {'cle': 'k1'}))
        tool = {t['name']: t for t in listed['result']['tools']}['clore']
        self.assertIs(tool['annotations']['readOnlyHint'], False)
        self.assertIn('matin', tool['inputSchema']['properties'])
        self.assertEqual(json.loads(ok['result']['content'][0]['text']), {'fait': 'k1'})
        for r in (again, unknown, empty, hex_line):
            self.assertTrue(r['result']['isError'])
        self.assertEqual(m.lignes()['matin']['a_traiter'], [])

    def test_ouvrir_opens_a_file_of_a_known_studio_and_nothing_else(self):
        m = self.connector()
        p = m.charger_projets()
        runs = []
        fake = lambda args, **kw: runs.append(args) or subprocess.CompletedProcess(args, 0)
        with mock.patch.object(p, 'dossier_du_matin', side_effect=lambda d, metas=None: d if d == str(self.alpha) else
                               (_ for _ in ()).throw(ValueError('Studio inconnu'))), \
                mock.patch.object(m.subprocess, 'run', side_effect=fake):
            listed, ok, escape, unknown, nothing = self.call(
                m, ('list', None), ('ouvrir', {'dossier': str(self.alpha), 'fichier': 'projet/a.md'}),
                ('ouvrir', {'dossier': str(self.alpha), 'fichier': '../a.md'}),
                ('ouvrir', {'dossier': '/etc', 'fichier': 'passwd'}), ('ouvrir', {}))
        tool = {t['name']: t for t in listed['result']['tools']}['ouvrir']
        self.assertIn('fichier', tool['inputSchema']['properties'])
        self.assertEqual(json.loads(ok['result']['content'][0]['text']), {'ouvert': 'projet/a.md'})
        self.assertEqual(runs, [['open', os.path.realpath(os.path.join(str(self.alpha), 'projet/a.md'))]])
        for r in (escape, unknown, nothing):
            self.assertTrue(r['result']['isError'])

    def open_calls(self, m, *fichiers):
        p = m.charger_projets()
        runs = []
        fake = lambda args, **kw: runs.append(args) or subprocess.CompletedProcess(args, 0)
        with mock.patch.object(p, 'dossier_du_matin', side_effect=lambda d, metas=None: d), \
                mock.patch.object(m.subprocess, 'run', side_effect=fake):
            out = self.call(m, *[('ouvrir', {'dossier': str(self.alpha), 'fichier': f}) for f in fichiers])
        return [r['result'].get('isError', False) for r in out], runs

    def test_ouvrir_opens_documents_only(self):
        m = self.connector()
        ok = ['projet/a.md', 'b.PDF', 'c.docx', 'd.xlsx', 'e.pptx', 'f.csv', 'g.png', 'h.JPEG', 'i.odt', 'j.rtf', 'k.html']
        bad = ['run.command', 'App.app', 'x.terminal', 'script.sh', 'tool', 'p.py', '.md', 'a.md/', 'w.webloc']
        errors, runs = self.open_calls(m, *(ok + bad))
        self.assertEqual(errors, [False] * len(ok) + [True] * len(bad))
        self.assertEqual(len(runs), len(ok))

    def test_ouvrir_refuses_a_symlink_that_leaves_the_studio_or_hides_an_app(self):
        m = self.connector()
        outside = self.root / 'ailleurs'
        outside.mkdir()
        (outside / 'secret.md').write_text('x', encoding='utf-8')
        (outside / 'Outil.app').mkdir()
        alpha = pathlib.Path(self.alpha)
        (alpha / 'sortie.md').symlink_to(outside / 'secret.md')
        (alpha / 'leurre.md').symlink_to(outside / 'Outil.app')
        (alpha / 'dossier.md').mkdir()
        (alpha / 'projet' / 'vrai.md').write_text('x', encoding='utf-8')
        (alpha / 'interne.md').symlink_to(alpha / 'projet' / 'vrai.md')
        errors, runs = self.open_calls(m, 'sortie.md', 'leurre.md', 'dossier.md', 'interne.md')
        self.assertEqual(errors, [True, True, True, False])
        self.assertEqual(runs, [['open', os.path.realpath(alpha / 'projet' / 'vrai.md')]])


@unittest.skipUnless(shutil.which('node'), "node absent : la page épinglée n'est pas essayée")
class Page(unittest.TestCase):
    MATIN = {'etat': 'ok', 'genere_le': '2026-11-05T07:30:00', 'jour': 'lourde',
             'agenda': [{'heure': '09:30', 'titre': 'Point <équipe>', 'projet': 'Alpha'}],
             'a_traiter': [item(1, titre='Répondre au <client>'),
                           item(2, projet='', source='slack', lien='https://acme.slack.com/archives/C1/p1'),
                           item(3, source='studio', lien='projet/a.md', dossier='/S/Alpha')],
             'regle': [{'qui': 'Léo', 'quand': 'hier', 'quoi': 'devis envoyé', 'lien': 'https://example.org/r'}],
             'preparer_demain': [{'titre': 'Relire le devis', 'phrase': 'Avant la réunion.', 'lien': ''},
                                 {'titre': 'Préparer la démo', 'phrase': '', 'lien': 'https://drive.google.com/d'}],
             'reunions_sans_cr': [],
             'entre_studio': [{'cle': 'e1', 'projet': 'Beta', 'phrase': 'Le CR du <COPIL> est rangé.', 'lien': 'https://docs.google.com/x'},
                              {'cle': 'e2', 'projet': 'Beta', 'phrase': 'Nouvelle maquette.', 'lien': 'maquettes/v2.md', 'dossier': '/S/Beta'},
                              {'cle': 'e3', 'projet': 'Alpha', 'phrase': 'Mail du client.', 'lien': ''}]}

    def run_page(self, **entree):
        entree.setdefault('lignes', [])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(entree, f)
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_the_page_opens_on_the_board_tab_with_the_count(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes', 'clore'])
        self.assertFalse(out['ongletsHidden'])
        self.assertEqual((out['ongletTableauSelected'], out['ongletMatinSelected']), ('true', 'false'))
        self.assertTrue(out['matinHidden'], 'Today is never the opening tab')
        self.assertFalse(out['vueTableauHidden'])
        self.assertIn('Today', out['ongletMatin'])
        self.assertIn('<span class="pastille">3</span>', out['ongletMatin'])
        self.assertEqual(out['ongletMatinLabel'], 'Today · 3 à traiter')

    def test_the_open_questions_of_a_meeting_open_the_board_on_that_project(self):
        # PM, 2026-11-20: « 26 questions ouvertes » beside a meeting was text. It is a button; one click shows the board
        # filtered on the project (the lines that were counted), on the board tab.
        lignes = [{'studio': 'Alpha', 'session': 's%d' % i, 'cle': 'c%d' % i, 'lien': '', 'type': 'decision', 'verbe': 'Répondre',
                   'affiche_titre': 'Q%d · Format' % i, 'affiche_suite': 'lequel ?', 'question': 'Q%d' % i,
                   'retrait': 'r00000000000%d' % i, 'bloque': False, 'proche': False} for i in (1, 2)]
        lignes.append(dict(lignes[0], studio='Beta', cle='c9', retrait='r000000000099', affiche_titre='Q9 · Autre'))
        out = self.run_page(matin=self.MATIN, lignes=lignes, outils=['lignes', 'clore'], cliquer=[['data-voir-questions', 'Alpha']])
        self.assertIn('data-voir-questions="Alpha"', out['matinAvant'])
        self.assertIn('2 questions ouvertes', out['matinAvant'])
        self.assertEqual(out['ongletTableauSelected'], 'true')
        self.assertFalse(out['vueTableauHidden'])
        self.assertIn('aria-pressed="true"', out['studios'])
        self.assertNotIn('Q9', out['tableau'])
        self.assertIn('Q1', out['tableau'])

    def test_no_count_when_nothing_is_open_and_no_tabs_without_matin(self):
        out = self.run_page(matin=dict(self.MATIN, a_traiter=[]))
        self.assertNotIn('pastille', out['ongletMatin'])
        out = self.run_page(matin={'etat': 'pas_passe'})
        self.assertNotIn('pastille', out['ongletMatin'])
        out = self.run_page()
        self.assertTrue(out['ongletsHidden'])
        self.assertTrue(out['matinHidden'])
        self.assertFalse(out['vueTableauHidden'])

    def test_the_tab_shows_ce_matin_and_hides_the_board(self):
        out = self.run_page(matin=self.MATIN, cliquer=[['data-onglet', 'matin']])
        self.assertEqual((out['ongletTableauSelected'], out['ongletMatinSelected']), ('false', 'true'))
        self.assertFalse(out['matinHidden'])
        self.assertTrue(out['vueTableauHidden'])
        out = self.run_page(matin=self.MATIN, cliquer=[['data-onglet', 'matin'], ['data-onglet', 'tableau']])
        self.assertTrue(out['matinHidden'])
        self.assertFalse(out['vueTableauHidden'])

    def test_a_project_view_goes_back_to_the_board_tab(self):
        out = self.run_page(matin=self.MATIN, cliquer=[['data-onglet', 'matin'], ['data-projet', '/S/Alpha']])
        self.assertTrue(out['matinHidden'])
        self.assertFalse(out['vueTableauHidden'])
        self.assertFalse(out['projetCache'])

    def test_the_band_the_lists_and_the_source_buttons(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes', 'clore'])
        h = out['matin']
        self.assertIn('Journée lourde · 3 à traiter aujourd&#39;hui', h)
        self.assertIn('Point &lt;équipe&gt;', h)
        self.assertIn('Répondre au &lt;client&gt;', h)
        self.assertNotIn('Ouvrir ↗', h, 'a line leads to its source, never to a session')
        self.assertNotIn('data-sid', h)
        self.assertIn('href="https://example.org/1" target="_blank" rel="noopener noreferrer">Gmail ↗', h)
        self.assertIn('>Slack ↗</button>', h)   # through the connector, into the Slack app (Q14)
        self.assertIn('data-fichier="projet/a.md" data-dossier="/S/Alpha"', h)
        self.assertIn('>Fichier ↗</button>', h)
        self.assertIn('data-matin-fait="k1"', h)
        self.assertIn('Préparer demain', h)
        self.assertIn('Relire le devis', h)
        self.assertIn('href="https://drive.google.com/d" target="_blank" rel="noopener noreferrer">Drive ↗', h)
        self.assertIn('Réglé · 1', h)
        self.assertNotIn('devis envoyé', h, 'Réglé is folded')

    def test_the_label_follows_the_link(self):
        cases = {'https://mail.google.com/mail/u/0/#inbox/1': 'Gmail', 'https://calendar.google.com/event?e=1': 'Agenda',
                 'https://acme.slack.com/archives/C1': 'Slack', 'https://docs.google.com/document/d/1': 'Drive'}
        for lien, libelle in cases.items():
            out = self.run_page(matin=dict(self.MATIN, a_traiter=[item(1, source='studio', lien=lien)]))
            fin = '</button>' if libelle == 'Slack' else '</a>'   # a Slack message opens in the app (Q14)
            self.assertIn(f'>{libelle} ↗{fin}', out['matin'], lien)

    def test_slack_calls_ouvrir_with_the_message_address(self):
        u = 'https://acme.slack.com/archives/C0ABC1234/p1793900000000100'
        out = self.run_page(matin=self.MATIN, cliquer=[['data-slack', u]])
        self.assertIn(['ouvrir', {'slack': u}], out['appels'])

    def test_a_file_without_its_studio_has_no_button(self):
        out = self.run_page(matin=dict(self.MATIN, a_traiter=[item(1, source='studio', lien='projet/a.md', dossier=None)]))
        self.assertNotIn('Fichier ↗', out['matin'])

    def test_fichier_calls_ouvrir_with_the_folder_and_the_path(self):
        out = self.run_page(matin=self.MATIN, cliquer=[['data-fichier', 'projet/a.md']], attributs={'data-dossier': '/S/Alpha'})
        self.assertIn(['ouvrir', {'dossier': '/S/Alpha', 'fichier': 'projet/a.md'}], out['appels'])

    def test_entre_studio_is_for_information_one_short_line_per_entry(self):
        # PM, Q34 of 2026-11-06: grouped by project, one short line per entry, the detail on a click, one button.
        out = self.run_page(matin=self.MATIN)
        h = out['matin']
        self.assertIn('<h3>Pour info : ce qui est entré au Studio</h3>', h)
        self.assertIn('Pour info. Ce qui te demande un geste est dans le tableau.', h)
        self.assertNotIn('Rien à faire ici', h, 'not next to a « Fait » button (PM, 2026-11-09)')
        self.assertLess(h.index('Beta <span class="n">· 2'), h.index('Alpha <span class="n">· 1'))
        self.assertIn('data-entre="e1"', h)
        self.assertIn('>Drive ↗</a>', h)
        self.assertNotIn('data-fichier', h.split('Pour info', 1)[1].split('Réglé', 1)[0])   # no « Fichier ↗ » here
        out = self.run_page(matin=self.MATIN, cliquer=[['data-entre', 'e1']])
        self.assertIn('data-entre="e1" role="button" tabindex="0" aria-expanded="true"', out['matin'])

    def test_fait_calls_clore_with_matin_and_the_item_leaves(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes', 'clore'], cliquer=[['data-matin-fait', 'k1']])
        self.assertIn(['clore', {'cle': 'k1', 'matin': True}], out['appels'])
        self.assertIn('data-matin-fait="k1"', out['matinAvant'])
        self.assertNotIn('data-matin-fait="k1"', out['matin'])
        self.assertIn('data-matin-fait="k2"', out['matin'])
        self.assertIn('Journée lourde · 2 à traiter aujourd&#39;hui', out['matin'])
        self.assertIn('<span class="pastille">2</span>', out['ongletMatin'])

    def test_no_clore_tool_no_fait_button(self):
        out = self.run_page(matin=self.MATIN, outils=['lignes'])
        self.assertNotIn('data-matin-fait', out['matin'])

    def test_not_yet_passed_shows_the_state_never_the_old_content(self):
        out = self.run_page(matin={'etat': 'pas_passe'}, cliquer=[['data-onglet', 'matin']])
        self.assertFalse(out['matinHidden'])
        self.assertIn('Point du matin pas encore passé', out['matin'])
        self.assertNotIn('À traiter', out['matin'])

    def test_nothing_to_do_says_so(self):
        out = self.run_page(matin=dict(self.MATIN, a_traiter=[], regle=[], preparer_demain=[], agenda=[]))
        self.assertIn('Journée lourde · rien à traiter', out['matin'])

    def test_the_project_buttons_sit_in_their_studio_group(self):
        lignes = [{'studio': 'Alpha', 'session': 'S', 'cle': 'local_00000000-0000-0000-0000-0000000000b1', 'type': 'go',
                   'verbe': 'Go', 'question': 'Q1', 'affiche_titre': 'T'}]
        out = self.run_page(lignes=lignes, projets=[{'studio': 'Alpha', 'dossier': '/S/Alpha', 'nom': 'Alpha'}])
        self.assertRegex(out['studios'], r'<span class="studio-et-vue"><button type="button" class="aller"[^>]*>Alpha[^<]*'
                                         r'<span class="n">[^<]*</span></button><button type="button" class="vue-projet"')
        css = PAGE.read_text(encoding='utf-8')
        self.assertIn('.studio-et-vue { display:inline-flex; align-items:stretch; max-width:100%; border:1px solid var(--line)', css)


class ScriptsForTheTasks(MatinBase):
    """matin.py preparer / verifier (2026-11-09): what a script can read, the tasks no longer read with an LLM."""

    def test_preparer_stops_when_today_is_written(self):
        self.write(a_traiter=[item(1)])
        self.assertIn('stop', self.m.preparer(MONDAY))

    def test_preparer_gives_studios_requests_and_minutes(self):
        studio = pathlib.Path(self.tmp.name) / 'StudioA'
        (studio / '3-run' / 'reunions').mkdir(parents=True)
        day = dt.date.fromtimestamp(MONDAY).isoformat()
        (studio / '3-run' / 'reunions' / f'{day}-atelier.md').write_text('cr', encoding='utf-8')
        (self.mon_studio / 'projets.json').write_text(json.dumps({
            'studios': [{'nom': 'Alpha', 'dossier': str(studio), 'role': 'pm'},
                        {'nom': 'Beta', 'dossier': str(studio), 'role': 'membre'}],
            'projets': [{'nom': 'Alpha', 'lignes': [
                {'type': 'a_toi', 'titre': 'Valider le devis', 'lien': 'https://example.org/d'},
                {'type': 'question', 'titre': 'Q1'}]}]}), encoding='utf-8')
        r = self.m.preparer(MONDAY)
        self.assertNotIn('stop', r)
        self.assertEqual([s['nom'] for s in r['studios']], ['Alpha', 'Beta'])
        self.assertEqual(r['deja_releve'], [{'projet': 'Alpha', 'titre': 'Valider le devis', 'lien': 'https://example.org/d'}])
        self.assertEqual(r['comptes_rendus'], {'Alpha': [day]})

    def test_preparer_gives_only_the_drafts_to_check(self):
        # 2026-11-10: the task reads no file; at most 10 Gmail reads, Slack only inside its 3 working days.
        def jour(n):   # n calendar days before MONDAY
            return (dt.date.fromtimestamp(MONDAY) - dt.timedelta(days=n)).isoformat() + 'T09:00:00'
        notes = [{'cle': f'gmail:d{i}', 'outil': 'gmail', 'brouillon': f'd{i}', 'objet': f'Objet {i}',
                  'destinataire': 'a@example.org', 'lien': 'https://mail.google.com/x', 'dossier': '/S/Alpha/sous',
                  'cree_le': jour(10 + i)} for i in range(12)]
        notes += [{'cle': 'gmail:vendredi', 'outil': 'gmail', 'cree_le': jour(3)},    # last working day: not yet
                  {'cle': 'slack:C1', 'outil': 'slack', 'canal': 'C1', 'cree_le': jour(4)},     # Thursday: 2 days
                  {'cle': 'slack:C2', 'outil': 'slack', 'canal': 'C2', 'cree_le': jour(7)},     # past 3 days
                  {'cle': 'autre', 'outil': 'teams', 'cree_le': jour(5)}, 'pas un objet']
        (self.mon_studio / '.parc').mkdir(exist_ok=True)
        (self.mon_studio / '.parc' / 'brouillons.json').write_text(json.dumps({'brouillons': notes}), encoding='utf-8')
        (self.mon_studio / 'projets.json').write_text(json.dumps({'studios': [
            {'nom': 'Alpha', 'dossier': '/S/Alpha', 'role': 'pm'}, {'nom': 'Al', 'dossier': '/S/Al', 'role': 'pm'}]}),
            encoding='utf-8')
        b = self.m.preparer(MONDAY)['brouillons']
        gmail = [x for x in b if x['outil'] == 'gmail']
        self.assertEqual(len(gmail), self.m.BROUILLONS_GMAIL_MAX)
        self.assertEqual(gmail[0]['cle'], 'gmail:d11', 'the oldest first')
        self.assertEqual((gmail[0]['projet'], gmail[0]['depuis']), ('Alpha', jour(21)[:10]))
        self.assertEqual([x['cle'] for x in b if x['outil'] == 'slack'], ['slack:C1'])
        self.assertNotIn('gmail:vendredi', [x['cle'] for x in b])

    def test_preparer_leaves_out_a_draft_marked_done(self):
        jour = (dt.date.fromtimestamp(MONDAY) - dt.timedelta(days=10)).isoformat()
        (self.mon_studio / '.parc').mkdir(exist_ok=True)
        (self.mon_studio / '.parc' / 'brouillons.json').write_text(json.dumps({'brouillons': [
            {'cle': 'gmail:d1', 'outil': 'gmail', 'objet': 'O', 'destinataire': 'D', 'cree_le': jour}]}), encoding='utf-8')
        self.assertEqual(len(self.m.preparer(MONDAY)['brouillons']), 1)
        empreinte = self.m.empreinte('brouillons', {'objet': 'O', 'destinataire': 'D'})
        self.state_file().write_text(json.dumps({'fermes': {'gmail:d1': {'le': jour, 'empreinte': empreinte}}}),
                                     encoding='utf-8')
        self.assertEqual(self.m.preparer(MONDAY)['brouillons'], [])

    def test_verifier_stops_without_a_point_or_without_anything_open(self):
        self.assertIn('stop', self.m.verifier(MONDAY))
        self.write(a_traiter=[])
        self.assertIn('stop', self.m.verifier(MONDAY))
        self.write(a_traiter=[item(1)])
        self.m.fait('k1', MONDAY)
        self.assertIn('stop', self.m.verifier(MONDAY))

    def test_verifier_gives_only_open_items_and_runs_three_times_a_day_at_most(self):
        self.write(a_traiter=[item(1), item(2)])
        self.m.fait('k1', MONDAY)
        for _ in range(self.m.VERIFS_MAX):
            r = self.m.verifier(MONDAY)
            self.assertEqual(r.pop('maintenant')[:10], self.m._aujourdhui(MONDAY))
            self.assertEqual([x['cle'] for x in r.pop('point')['a_traiter']], ['k1', 'k2'], 'the whole point, read for the task')
            self.assertEqual(r, {'a_verifier': [{'cle': 'k2', 'source': 'gmail', 'lien': 'https://example.org/2'}]})
        self.assertIn('stop', self.m.verifier(MONDAY))
        self.assertEqual(self.m.fait('k2', MONDAY), {'fait': 'k2'}, 'the count lives apart from « fait »')


if __name__ == '__main__':
    unittest.main()
