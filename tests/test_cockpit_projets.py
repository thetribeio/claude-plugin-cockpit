"""Tests: the list by project (skills/mon-studio/scripts/projets.py, 2026-11-04): python3 -m unittest discover -s tests

One block per Studio known on this Mac that has something waiting for the viewer: « À toi de jouer » items of the
ingestion runs (the Studio's PM only; they stay until settled or closed by hand), « Ce qui est entré » items (everyone;
they fade once their run leaves the window, which starts at midnight of the previous working day) and the open lines
of the Mon Studio table for that Studio (everyone; closed when they leave the table). Read by the morning brief
(projets.md) and the pinned page (`projets` field of the connector's `lignes`, button « Fait / plus d'actu » calling
`clore`).

Studios, cards, ingestion states and the table are synthetic; the real app, home and git identity are never used."""
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'projets.py'
CONNECTOR = ROOT / 'skills' / 'mon-studio' / 'scripts' / 'mcp_mon_studio.py'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
RUNNER = ROOT / 'tests' / 'tester-epinglee.js'
MAIL = 'local_00000000-0000-0000-0000-0000000000a1'
WORK = 'local_00000000-0000-0000-0000-0000000000c1'
ASKER = 'local_00000000-0000-0000-0000-0000000000d1'
PAGE_URL = 'https://claude.ai/artifact/abcDEF123'


def local(y, mo, d, h=9, mi=0):
    return time.mktime(dt.datetime(y, mo, d, h, mi).timetuple())


def utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


MONDAY = local(2026, 11, 2)          # window from Friday 30/10 00:00
FRIDAY = local(2026, 10, 30, 14)
THURSDAY = local(2026, 10, 29, 14)
WEDNESDAY_AFTER = local(2026, 11, 4)  # window from Tuesday 03/11 00:00

REPORT = ("📬 Alpha · 3 nouveautés · 1 action pour toi\nÀ toi de jouer :\n- Valider le **devis** avant jeudi.\n"
          "Ce qui est entré :\n- Email client (Léo, 30/10 08:10) : devis reçu. Au Studio : [devis](2-cadrage/devis.md).\n"
          "- Réunion A (notes, 29/10) : relevé de décisions.\nDoublon probable à fusionner : `a` et `b`.")


def load(mon_studio):
    old = os.environ.get('MON_STUDIO')
    os.environ['MON_STUDIO'] = str(mon_studio)
    try:
        spec = importlib.util.spec_from_file_location('projets_essai', SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        if old is None:
            os.environ.pop('MON_STUDIO', None)
        else:
            os.environ['MON_STUDIO'] = old
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.mon_studio = self.root / 'Mon Studio'
        (self.mon_studio / '.parc').mkdir(parents=True)
        self.p = load(self.mon_studio)
        self.alpha = self.studio('Studio - Alpha', pm='Éric  EXEMPLE')
        env = mock.patch.dict(os.environ, {'COCKPIT_IDENTITE': 'eric exemple'})
        env.start()
        self.addCleanup(env.stop)
        self.metas = [self.card(MAIL, self.alpha, '📬 Alpha', 100), self.card(WORK, self.alpha, 'Kit A', 200),
                      self.card(ASKER, self.alpha, 'Cadrage', 50)]
        self.table = []

    def tearDown(self):
        self.tmp.cleanup()

    def studio(self, name, pm=None, fiche=True):
        d = self.root / 'studios' / name
        (d / 'projet').mkdir(parents=True)
        if fiche:
            rows = ['| Champ | Valeur |', '|---|---|', '| **Client** | Exemple |']
            if pm is not None:
                rows.append(f'| **PM** | {pm} |')
            (d / 'projet' / 'fiche-projet.md').write_text('# Fiche projet\n\n' + '\n'.join(rows) + '\n', encoding='utf-8')
        return str(d)

    def card(self, sid, cwd, title, activity, archived=False):
        return {'id': sid, 'cli': None, 'cwd': cwd, 'titre': title, 'archivee': archived, 'tache': None,
                'activite': activity}

    def runs(self, studio, *runs, reglees=None):
        state = {'nouvelles': [{'ts': utc(t), 'machine': 'mac', 'texte': text} for t, text in runs]}
        if reglees is not None:
            state['reglees'] = reglees
        (pathlib.Path(studio) / 'projet' / '.ingestion-auto-state.json').write_text(json.dumps(state), encoding='utf-8')

    def question(self, title='Format du CR', num='Q5', sid=ASKER, since=None, studio='Alpha'):
        return {'studio': studio, 'cle': sid, 'lien': f'claude://claude.ai/epitaxy/{sid}', 'question': num,
                'affiche_titre': title, 'affiche_suite': 'deux options', 'session': 'Cadrage', 'type': 'decision',
                'depuis': since or MONDAY - 3600}

    def compute(self, when=MONDAY, write=True):
        e = {'tableau': self.table, 'lecture_app': {'etat': 'ok', 'raison': ''}}
        return self.p.calculer(e=e, maintenant=when, metas=self.metas, ecrire=write)

    def block(self, out, name='Alpha'):
        return next((b for b in out['projets'] if b['nom'] == name), None)

    def types(self, out, name='Alpha'):
        b = self.block(out, name)
        return sorted(l['type'] for l in b['lignes']) if b else []


class Role(Base):
    def test_pm_matches_without_accents_case_or_spaces(self):
        self.assertEqual(self.p.role(self.alpha, 'eric exemple'), 'pm')
        self.assertEqual(self.p.role(self.alpha, 'ÉRIC   Exemple'), 'pm')
        self.assertEqual(self.p.role(self.alpha, 'Sam Autre'), 'membre')

    def test_placeholder_absent_or_no_identity_is_member(self):
        self.assertEqual(self.p.role(self.studio('Studio - B', pm='_À compléter_'), 'eric exemple'), 'membre')
        self.assertEqual(self.p.role(self.studio('Studio - C', pm=''), 'eric exemple'), 'membre')
        self.assertEqual(self.p.role(self.studio('Studio - D'), 'eric exemple'), 'membre')
        with mock.patch.dict(os.environ, {'COCKPIT_IDENTITE': ''}):
            self.assertEqual(self.p.role(self.alpha), 'membre')

    def test_identity_from_gitconfig_when_git_is_not_on_the_path(self):
        # The app starts the connector without git on its PATH: the name comes from ~/.gitconfig.
        home = pathlib.Path(self.tmp.name) / 'home'
        home.mkdir()
        (home / '.gitconfig').write_text('[core]\n\tname = no\n[user]\n\temail = e@x.io\n\tname = Eric Exemple\n')
        env = {k: v for k, v in os.environ.items() if k != 'COCKPIT_IDENTITE'}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(self.p.subprocess, 'run', side_effect=OSError), \
                mock.patch.object(self.p.pathlib.Path, 'home', return_value=home):
            self.assertEqual(self.p.identite(), 'Eric Exemple')
            self.assertEqual(self.p.role(self.alpha), 'pm')
        self.assertIsNone(self.p.nom_du_gitconfig(home / 'absent'))

    def sans_essai(self, run, gitconfig=None, setting=None):
        """identite_et_source() as on a PM's Mac: no COCKPIT_IDENTITE nor COCKPIT_COMPTE, `run` instead of the commands."""
        home = pathlib.Path(self.tmp.name) / 'home-pm'
        home.mkdir(exist_ok=True)
        if gitconfig:
            (home / '.gitconfig').write_text(f'[user]\n\tname = {gitconfig}\n')
        if setting is not None:
            (self.mon_studio / '.parc' / 'cockpit.json').write_text(json.dumps(setting), encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if k not in ('COCKPIT_IDENTITE', 'COCKPIT_COMPTE')}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(self.p.subprocess, 'run', side_effect=run), \
                mock.patch.object(self.p.pathlib.Path, 'home', return_value=home):
            return self.p.identite_et_source(), self.p.role(self.alpha)

    @staticmethod
    def commandes(git=None, compte=None, erreur_compte=None):
        appels = []

        def run(cmd, **kw):
            appels.append((cmd, kw))
            if cmd[0] == '/usr/bin/id':
                if erreur_compte:
                    raise erreur_compte
                return subprocess.CompletedProcess(cmd, 0 if compte else 1, stdout=compte or '', stderr='')
            if git:
                return subprocess.CompletedProcess(cmd, 0, stdout=git + '\n', stderr='')
            raise OSError('git absent')
        return run, appels

    def test_pm_name_from_the_setting_first(self):
        run, _ = self.commandes(git='Sam Autre', compte='Robin Autre')
        (nom, source), role = self.sans_essai(run, gitconfig='Sam Autre', setting={'page': 'x', 'pm': ' Éric   Exemple '})
        self.assertEqual((nom, source, role), ('Éric Exemple', 'reglage', 'pm'))

    def test_pm_name_from_git_without_the_setting(self):
        run, _ = self.commandes(git='Eric Exemple', compte='Robin Autre')
        self.assertEqual(self.sans_essai(run, setting={'page': 'x', 'pm': '  '}), (('Eric Exemple', 'git'), 'pm'))

    def test_pm_name_from_the_mac_account_without_git(self):
        # A PM who never configured git still has their projects « à toi » (audit of 2026-11-18).
        run, appels = self.commandes(compte='Eric  Exemple\n')
        self.assertEqual(self.sans_essai(run), (('Eric Exemple', 'compte'), 'pm'))
        cmd, kw = next((c, k) for c, k in appels if c[0] == '/usr/bin/id')
        self.assertEqual(cmd, ['/usr/bin/id', '-F'])
        self.assertFalse(kw.get('shell'))
        self.assertLessEqual(kw['timeout'], 5)

    def test_no_name_anywhere_is_member_without_an_error(self):
        for erreur in (None, OSError('id absent'), subprocess.TimeoutExpired(['/usr/bin/id'], 2)):
            run, _ = self.commandes(erreur_compte=erreur)
            self.assertEqual(self.sans_essai(run), ((None, 'aucun'), 'membre'))

    def test_a_cell_with_a_remark_or_two_names(self):
        self.assertEqual(self.p.role(self.studio('Studio - E', pm='**Eric Exemple** (theTribe)'), 'eric exemple'), 'pm')
        self.assertEqual(self.p.role(self.studio('Studio - F', pm='Ana B / Eric Exemple'), 'eric exemple'), 'pm')
        self.assertEqual(self.p.role(self.studio('Studio - G', pm='Ana B (après Eric Exemple)'), 'eric exemple'), 'membre')


class Sections(Base):
    def test_report_split(self):
        entres, actions = self.p.sections_nouvelle(REPORT)
        self.assertEqual(actions, ['Valider le **devis** avant jeudi.'])
        self.assertEqual(len(entres), 2)
        self.assertTrue(entres[0].startswith('Email client (Léo, 30/10 08:10) : devis reçu.'))

    def test_markdown_to_plain(self):
        self.assertEqual(self.p.texte_simple('Voir [le devis](a/b.md) et **vite** `x`'), 'Voir le devis et vite x')


class Window(Base):
    def test_previous_working_day_midnight(self):
        self.assertEqual(self.p.debut_fenetre(MONDAY), local(2026, 10, 30, 0))
        self.assertEqual(self.p.debut_fenetre(WEDNESDAY_AFTER), local(2026, 11, 3, 0))
        self.assertEqual(self.p.debut_fenetre(local(2026, 11, 1, 10)), local(2026, 10, 30, 0))   # Sunday

    def test_age_words(self):
        self.assertEqual(self.p.age(MONDAY - 600, MONDAY), "aujourd'hui")
        self.assertEqual(self.p.age(local(2026, 11, 1, 20), MONDAY), 'depuis hier')
        self.assertEqual(self.p.age(FRIDAY, MONDAY), 'depuis 3 j')


class Modes(Base):
    def test_pm_sees_actions_entries_and_questions(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.table = [self.question()]
        out = self.compute()
        self.assertEqual(self.types(out), ['a_toi', 'entree', 'entree', 'question'])
        b = self.block(out)
        self.assertEqual(b['role'], 'pm')
        a = next(l for l in b['lignes'] if l['type'] == 'a_toi')
        self.assertEqual(a['titre'], 'Valider le devis avant jeudi.')
        self.assertEqual(a['depuis'], int(FRIDAY) * 1000)
        e = next(l for l in b['lignes'] if l['type'] == 'entree')
        self.assertEqual((e['titre'], e['detail']), ('Email client (Léo, 30/10 08:10)', 'devis reçu. Au Studio : devis.'))
        q = next(l for l in b['lignes'] if l['type'] == 'question')
        self.assertEqual((q['titre'], q['session'], q['repli']), ('Q5 · Format du CR', ASKER, False))
        self.assertRegex(a['cle'], r'^[0-9a-f]{12}$')

    def test_question_number_is_not_doubled(self):
        # The register may already carry the number in the title: « Q1 · Q1 · … » must not appear.
        self.table = [self.question(title='Q1 · Périmètre', num='Q1'), self.question(title='Q10 · Budget', num='Q1', sid=WORK)]
        titles = sorted(l['titre'] for l in self.block(self.compute())['lignes'] if l['type'] == 'question')
        self.assertEqual(titles, ['Q1 · Périmètre', 'Q1 · Q10 · Budget'])

    def test_member_never_sees_actions(self):
        with mock.patch.dict(os.environ, {'COCKPIT_IDENTITE': 'Sam Autre'}):
            self.runs(self.alpha, (FRIDAY, REPORT))
            self.table = [self.question()]
            out = self.compute()
        self.assertEqual(self.types(out), ['entree', 'entree', 'question'])
        self.assertEqual(self.block(out)['role'], 'membre')
        state = json.loads((self.mon_studio / '.parc' / 'projets-etat.json').read_text(encoding='utf-8'))
        self.assertNotIn('a_toi', {l['type'] for l in state['lignes'].values()})
        self.assertNotIn('devis avant jeudi', (self.mon_studio / 'projets.md').read_text(encoding='utf-8'))
        self.assertNotIn('devis avant jeudi', (self.mon_studio / 'projets.json').read_text(encoding='utf-8'))

    def test_old_runs_show_their_requests_only(self):
        # Entries fade after the window; a request is noted while its run is less than 14 days old (Q21, 2026-11-06).
        self.runs(self.alpha, (THURSDAY, REPORT))
        self.assertEqual(self.types(self.compute()), ['a_toi'])

    def test_seen_action_stays_with_its_age_entries_fade(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute(MONDAY)
        out = self.compute(WEDNESDAY_AFTER)
        self.assertEqual(self.types(out), ['a_toi'])
        md = (self.mon_studio / 'projets.md').read_text(encoding='utf-8')
        self.assertIn('- Valider le devis avant jeudi. · à toi de jouer (ingestion) · depuis 5 j', md)


class Closing(Base):
    def test_a_question_closes_when_it_leaves_the_table(self):
        self.table = [self.question()]
        self.compute(MONDAY)
        self.table = []
        out = self.compute(MONDAY + 600)
        b = self.block(out)
        self.assertEqual((b['lignes'], b['fermees_depuis_hier'], b['fermees_titres']), ([], 1, ['Q5 · Format du CR']))
        self.assertIn('Fermé depuis hier : Q5 · Format du CR', (self.mon_studio / 'projets.md').read_text(encoding='utf-8'))
        self.assertIsNone(self.block(self.compute(local(2026, 11, 13))), 'gone from the window, then purged')

    def test_nothing_closes_when_the_app_cannot_be_read(self):
        self.table = [self.question()]
        self.compute(MONDAY)
        e = {'tableau': [], 'lecture_app': {'etat': 'hors_service', 'raison': 'x'}}
        self.p.calculer(e=e, maintenant=MONDAY + 600, metas=self.metas)
        self.table = [self.question()]
        self.assertEqual(self.types(self.compute(MONDAY + 700)), ['question'])

    def test_closed_by_hand_and_unknown_key_refused(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        out = self.compute()
        cle = next(l['cle'] for l in self.block(out)['lignes'] if l['type'] == 'a_toi')
        self.assertEqual(self.p.fermer(cle, MONDAY + 60), {'ferme': cle})
        with self.assertRaises(ValueError):
            self.p.fermer(cle)
        with self.assertRaises(ValueError):
            self.p.fermer('0123456789ab')
        out = self.compute(MONDAY + 120)
        self.assertEqual(self.types(out), ['entree', 'entree'])
        self.assertEqual(self.block(out)['fermees_titres'], ['Valider le devis avant jeudi.'])
        state = json.loads((self.mon_studio / '.parc' / 'projets-etat.json').read_text(encoding='utf-8'))
        self.assertEqual(state['lignes'][cle]['par'], 'main')

    def test_cli_fait(self):
        env = dict(os.environ, MON_STUDIO=str(self.mon_studio))
        r = subprocess.run(['python3', str(SCRIPT), 'fait', 'ffffffffffff'], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn('Refusé', r.stdout)

    def test_settled_by_ingestion(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute()
        self.runs(self.alpha, (FRIDAY, REPORT), reglees=[{'ts': utc(MONDAY + 60), 'texte': 'Valider le devis avant jeudi',
                                                          'preuve': 'mail envoyé'}])
        out = self.compute(MONDAY + 120)
        self.assertEqual(self.types(out), ['entree', 'entree'])
        state = json.loads((self.mon_studio / '.parc' / 'projets-etat.json').read_text(encoding='utf-8'))
        self.assertEqual([l['par'] for l in state['lignes'].values() if l['type'] == 'a_toi'], ['source'])

    def test_a_corrupt_state_starts_empty(self):
        (self.mon_studio / '.parc' / 'projets-etat.json').write_text('{oops', encoding='utf-8')
        self.table = [self.question()]
        self.assertEqual(self.types(self.compute()), ['question'])


class Output(Base):
    def test_studio_without_ingestion_lists_questions_and_empty_ones_are_omitted(self):
        beta = self.studio('Studio-Beta-Projet', pm='Quelqu Un')
        gamma = self.studio('Studio - Gamma', pm='Eric Exemple')
        self.metas += [self.card('local_00000000-0000-0000-0000-0000000000e1', beta, 'Dev', 10),
                       self.card('local_00000000-0000-0000-0000-0000000000e2', gamma + '/.claude/worktrees/x', 'Wt', 10)]
        self.table = [self.question(studio='Beta Projet', sid='local_00000000-0000-0000-0000-0000000000e1')]
        out = self.compute()
        self.assertEqual([b['nom'] for b in out['projets']], ['Beta Projet'])
        self.assertEqual(self.types(out, 'Beta Projet'), ['question'])
        self.assertEqual(sorted((s['nom'], s['dossier'], s['role']) for s in out['studios']),
                         [('Alpha', self.alpha, 'pm'), ('Beta Projet', beta, 'membre'), ('Gamma', gamma, 'pm')])
        md = (self.mon_studio / 'projets.md').read_text(encoding='utf-8')
        self.assertNotIn('Gamma', md)
        self.assertIn('## Beta Projet (vue membre)', md)
        self.assertEqual(json.loads((self.mon_studio / 'projets.json').read_text(encoding='utf-8'))['studios'], out['studios'])

    def test_studios_need_a_fiche_and_studios_json_adds_some(self):
        sans = self.studio('Studio - Sans', fiche=False)
        extra = self.studio('Studio - Extra', pm='X')
        (self.mon_studio / 'studios.json').write_text(json.dumps([extra]), encoding='utf-8')
        self.metas.append(self.card('local_00000000-0000-0000-0000-0000000000e3', sans, 'S', 1))
        self.assertEqual(self.p.studios(self.metas), sorted([self.alpha, extra]))

    def test_a_studio_manifest_is_enough(self):
        # A Studio just created has its manifest and projet/ but no fiche yet: it is a Studio all the same.
        neuf = _isolation.make_studio(self.studio('Studio - Neuf', fiche=False))
        self.metas.append(self.card('local_00000000-0000-0000-0000-0000000000e4', neuf, 'N', 1))
        self.assertEqual(self.p.studios(self.metas), sorted([self.alpha, neuf]))
        self.assertIn(neuf, [s['dossier'] for s in self.compute()['studios']])

    def test_md_has_the_page_link_and_one_line_per_item(self):
        (self.mon_studio / '.parc' / 'cockpit.json').write_text(json.dumps({'page': PAGE_URL}), encoding='utf-8')
        self.runs(self.alpha, (MONDAY - 60, REPORT))
        self.table = [self.question()]
        out = self.compute()
        self.assertEqual(out['page'], PAGE_URL)
        md = (self.mon_studio / 'projets.md').read_text(encoding='utf-8')
        self.assertIn(PAGE_URL, md.splitlines()[2])
        self.assertIn('## Alpha', md)
        self.assertIn("- Valider le devis avant jeudi. · à toi de jouer (ingestion) · aujourd'hui", md)
        self.assertIn("- Q5 · Format du CR · question de « Cadrage » · aujourd'hui", md)
        self.assertIn("- Email client (Léo, 30/10 08:10) : devis reçu. Au Studio : devis. · entré au Studio (ingestion)", md)

    def test_no_write_in_trial(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute(write=False)
        self.assertEqual(sorted(p.name for p in self.mon_studio.rglob('*') if p.is_file()), [])


class Sessions(Base):
    def test_mail_session_or_most_recent_flagged(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        a = next(l for l in self.block(self.compute())['lignes'] if l['type'] == 'a_toi')
        self.assertEqual((a['session'], a['repli']), (MAIL, False))
        self.metas[0]['archivee'] = True
        a = next(l for l in self.block(self.compute())['lignes'] if l['type'] == 'a_toi')
        self.assertEqual((a['session'], a['repli']), (WORK, True))


class Connector(Base):
    def connector(self):
        old = os.environ.get('MON_STUDIO')
        os.environ['MON_STUDIO'] = str(self.mon_studio)
        try:
            spec = importlib.util.spec_from_file_location('mcp_projets_essai', CONNECTOR)
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

    def test_clore_is_listed_and_closes_a_known_line(self):
        m = self.connector()
        self.runs(self.alpha, (time.time() - 60, REPORT))
        cle = next(l['cle'] for l in self.block(self.p.calculer(e={'tableau': []}, metas=self.metas))['lignes']
                   if l['type'] == 'a_toi')
        listed, bad, unknown, ok = self.call(m, ('list', None), ('clore', {'cle': 'x'}), ('clore', {'cle': 'f' * 12}),
                                             ('clore', {'cle': cle}))
        tools = {t['name']: t for t in listed['result']['tools']}
        self.assertIs(tools['clore']['annotations']['readOnlyHint'], False)
        self.assertEqual(tools['clore']['inputSchema']['required'], ['cle'])
        self.assertTrue(bad['result']['isError'])
        self.assertTrue(unknown['result']['isError'])
        self.assertEqual(json.loads(ok['result']['content'][0]['text']), {'ferme': cle})

    def test_lignes_carries_projets_and_survives_a_broken_projets(self):
        m = self.connector()
        d = m.lignes()
        self.assertEqual((d['liste_projets']['projets'], d['liste_projets']['studios']), ([], []))
        with mock.patch.object(m, 'charger_projets', side_effect=SyntaxError('cassé')):
            d = m.lignes()
        self.assertIsNone(d['liste_projets'])
        self.assertIn('lignes', d)


    def test_projet_carries_the_open_conflicts_and_survives_a_broken_reader(self):
        m = self.connector()
        (pathlib.Path(self.alpha) / 'projet' / 'conflits.md').write_text(
            '# Registre des conflits\n\n### C1 · Jour du comité\n- **Détecté le** : 10/11/2026\n'
            '- **Ancienne valeur** : mardi (source : 2-cadrage/roadmap.md, 02/09/2026)\n'
            '- **Nouvelle valeur** : jeudi (source : sources/2026-10-20-mail.md, 20/10/2026)\n'
            '- **Déjà communiqué au client** : non\n- **Options** : remplacer · à confirmer avec le client · simple discussion\n'
            '- **État** : ouvert\n', encoding='utf-8')
        d = m.projet({'dossier': str(self.alpha)})
        self.assertEqual([c['id'] for c in d['conflits']['ouverts']], ['C1'])
        with mock.patch.object(m, 'charger_projets', side_effect=SyntaxError('cassé')):
            d = m.projet({'dossier': str(self.alpha)})
        self.assertIsNone(d['conflits'])

@unittest.skipUnless(shutil.which('node'), 'node absent : la page épinglée n\'est pas essayée')
class Page(unittest.TestCase):
    PROJETS = {'genere': 0, 'page': None, 'studios': [], 'projets': [
        {'nom': 'Alpha', 'role': 'pm', 'fermees_depuis_hier': 1, 'fermees_titres': ['Q2 · <b>vieux</b>'], 'lignes': [
            {'cle': 'aaaaaaaaaaaa', 'type': 'a_toi', 'titre': 'Valider <le> devis', 'detail': '', 'depuis': int(time.time() * 1000) - 3600000,
             'session': MAIL, 'repli': True},
            {'cle': 'bbbbbbbbbbbb', 'type': 'question', 'titre': 'Q5 · Format', 'detail': 'deux options', 'depuis': 0,
             'session': ASKER, 'repli': False}]},
        {'nom': 'Beta', 'role': 'membre', 'fermees_depuis_hier': 0, 'fermees_titres': [], 'lignes': [
            {'cle': 'cccccccccccc', 'type': 'reunion', 'titre': 'Point client', 'detail': '2026-11-02', 'depuis': 0,
             'session': ASKER, 'repli': False},
            {'cle': 'dddddddddddd', 'type': 'entree', 'titre': 'Email', 'detail': 'reçu', 'depuis': 0,
             'session': None, 'repli': True}]}]}

    def run_page(self, **entree):
        entree.setdefault('lignes', [])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(entree, f)
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run([shutil.which('node'), str(RUNNER), str(PAGE), f.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_blocks_badge_buttons_and_closing(self):
        out = self.run_page(liste_projets=self.PROJETS, outils=['lignes', 'clore'], cliquer=[['data-retirer', 'cccccccccccc']],
                            matin={'etat': 'pas_passe'})
        h, avant = out['matin'], out['matinAvant']
        # « Projets » keeps only the reminder of the conflicts (PM, 2026-11-17): the meetings without minutes are in
        # Today, the morning stand-up, and « Fermé depuis hier » is gone.
        self.assertTrue(out['projetsHidden'])
        self.assertNotIn('Fermé depuis hier', out['projetsAvant'] + avant + h)
        self.assertIn('Valider &lt;le&gt; devis', out['tableau'])
        self.assertNotIn(f'data-sid="{MAIL}"', out['tableau'], 'no mail session: no « Ouvrir » to another session')
        self.assertIn('data-retirer="aaaaaaaaaaaa"', out['tableau'])
        self.assertIn('Réunions sans compte rendu', avant)
        self.assertIn('Point client', avant)
        self.assertIn(f'data-sid="{ASKER}"', avant)
        self.assertIn('data-retirer="cccccccccccc"', avant)
        self.assertNotIn('Q5 · Format', avant)
        # The click only greys the row out for 10 s (the timer never fires here): « clore » is not called yet.
        self.assertEqual([a for a in out['appels'] if a[0] == 'clore'], [])
        self.assertIn(10000, out['minuteurs'])
        self.assertNotIn('data-retirer="cccccccccccc"', h)
        self.assertIn('data-annuler="cccccccccccc"', h)

    def test_no_studio_yet_says_how_one_appears(self):
        out = self.run_page(liste_projets={'genere': 0, 'page': None, 'studios': [], 'projets': []})
        self.assertIn("Aucun Studio trouvé pour l'instant", out['tableau'])
        self.assertNotIn("Rien ne t'attend", out['tableau'])
        known = {'genere': 0, 'page': None, 'studios': [{'nom': 'Alpha', 'dossier': '/x', 'role': 'pm'}], 'projets': []}
        self.assertIn("Rien ne t'attend.", self.run_page(liste_projets=known)['tableau'])

    def test_first_day_shows_the_welcome_line_not_the_alert(self):
        out = self.run_page(lecture_app={'etat': 'pas_encore', 'raison': 'x'})
        self.assertEqual(out['alerte'], '')
        self.assertIn("Aucun Studio trouvé pour l'instant", out['tableau'])
        out = self.run_page(lecture_app={'etat': 'hors_service', 'raison': 'x'})
        self.assertIn("Mon Studio ne lit plus l'app", out['alerte'])
        self.assertNotIn("Aucun Studio trouvé", out['tableau'])

    def test_an_unfound_project_is_headed_with_its_name(self):
        out = self.run_page(projetFixe='/Users/pm/Drive/Studio - Alpha')
        self.assertEqual(out['projetNom'], 'Studio - Alpha')

    def test_no_clore_tool_no_button_and_hidden_without_projets(self):
        out = self.run_page(liste_projets=self.PROJETS, outils=['lignes'], matin={'etat': 'pas_passe'})
        self.assertNotIn('data-retirer', out['matin'])
        self.assertIn('Ouvrir ↗', out['matin'])
        self.assertTrue(self.run_page()['projetsHidden'])
        self.assertTrue(self.run_page(liste_projets={'projets': [], 'studios': []})['projetsHidden'])


if __name__ == '__main__':
    unittest.main()
