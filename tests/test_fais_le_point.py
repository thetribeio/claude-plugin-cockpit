"""Tests of skills/point/scripts/fais_le_point.py (the point of the cockpit plugin, from the foreman-pm kit 0.8):
python3 -m unittest discover -s tests. Invented names, fake folders."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_08 = ROOT / 'skills' / 'point' / 'scripts' / 'fais_le_point.py'

def iso(days_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return t.strftime('%Y-%m-%dT%H:%M:%S.000Z')

class FaisLePoint(unittest.TestCase):
    """The point of the cockpit plugin."""
    SCRIPT = SCRIPT_08
    SUIVI = 'la vue projet de Mon Studio les montre ensemble'
    SEUIL = 2   # active sessions from which the follow-up is offered

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = pathlib.Path(self.tmp.name)
        self.studio = r / 'studio'
        self.studio.mkdir()
        self.app, self.tr = r / 'app', r / 'tr'
        (self.app / 'a' / 'b').mkdir(parents=True)
        (self.tr / 'p').mkdir(parents=True)
        self.home = r / 'home'
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, n, title, cwd=None, archived=False):
        d = {'sessionId': f'local_{n}', 'title': title, 'cwd': str(cwd or self.studio), 'cliSessionId': f'cli{n}', 'isArchived': archived}
        (self.app / 'a' / 'b' / f'local_{n}.json').write_text(json.dumps(d))

    def history(self, n, days_ago, context=1000, pm=True, sub_tokens=0):
        lines = []
        if pm:
            lines.append({'type': 'user', 'timestamp': iso(days_ago), 'message': {'content': 'Bonjour'}})
            lines.append({'type': 'user', 'timestamp': iso(days_ago), 'message': {'content': '<system-reminder>x</system-reminder>'}})
            lines.append({'type': 'user', 'timestamp': iso(days_ago), 'message': {'content': 'text task-notification'}})
        lines.append({'type': 'assistant', 'timestamp': iso(days_ago), 'message': {'id': f'm{n}', 'usage': {
            'input_tokens': 10, 'cache_read_input_tokens': context - 20, 'cache_creation_input_tokens': 10, 'output_tokens': 5}}})
        (self.tr / 'p' / f'cli{n}.jsonl').write_text('\n'.join(json.dumps(l) for l in lines) + '\n')
        if sub_tokens:
            sd = self.tr / 'p' / f'cli{n}' / 'subagents'
            sd.mkdir(parents=True)
            (sd / 'agent-x.jsonl').write_text(json.dumps({'type': 'assistant', 'isSidechain': True, 'timestamp': iso(days_ago),
                'message': {'id': 'sx', 'usage': {'input_tokens': sub_tokens, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}}) + '\n')

    def run_script(self, *args):
        env = dict(os.environ, HOME=str(self.home), MON_STUDIO_APP_SESSIONS=str(self.app), MON_STUDIO_TRANSCRIPTS=str(self.tr))
        return subprocess.run([sys.executable, '-I', str(self.SCRIPT), '--dossier', str(self.studio), *args], env=env,
                              capture_output=True, text=True).stdout

    def test_comptage_et_filtres(self):
        self.session(1, 'Alpha'); self.history(1, 1)
        self.session(2, 'Beta'); self.history(2, 2)
        self.session(3, 'Gamma', cwd=self.studio / 'wt'); self.history(3, 1)
        self.session(4, 'Hors', cwd=self.studio.parent / 'ailleurs'); self.history(4, 1)
        self.session(5, 'Archivee', archived=True); self.history(5, 1)
        d = json.loads(self.run_script('--json'))
        self.assertEqual(d['actives_n'], 3)
        self.assertEqual(sorted(d['actives']), ['Alpha', 'Beta', 'Gamma'])
        self.assertTrue(d['attente_absente'])
        self.assertIn('Vue Mon Studio absente', self.run_script())

    def test_studio_sans_session_ne_dit_pas_rien_a_faire(self):
        self.session(4, 'Hors', cwd=self.studio.parent / 'ailleurs'); self.history(4, 1)
        out = self.run_script()
        self.assertIn("Aucune session Claude ouverte dans ce Studio cette semaine", out)
        self.assertNotIn('À alléger : rien', out)

    def test_session_lourde(self):
        self.session(1, 'Lourde'); self.history(1, 1, context=200000)
        self.session(2, 'Legere'); self.history(2, 1, context=50000)
        d = json.loads(self.run_script('--json'))
        self.assertEqual([x['titre'] for x in d['lourdes']], ['Lourde'])

    def test_execution_planifiee_et_pilier_jamais_proposes(self):
        self.session(1, 'Vieille'); self.history(1, 10)
        self.session(2, 'Pilier'); self.history(2, 10)
        d = {'sessionId': 'local_3', 'title': 'Routine', 'cwd': str(self.studio), 'cliSessionId': 'cli3', 'scheduledTaskId': 'tache'}
        (self.app / 'a' / 'b' / 'local_3.json').write_text(json.dumps(d)); self.history(3, 10)
        (self.home / 'Mon Studio' / 'chantiers').mkdir(parents=True)
        (self.home / 'Mon Studio' / 'chantiers' / 'c.json').write_text(json.dumps({'chantier': 'C', 'piliers': [{'sessionId': 'local_2'}]}))
        d = json.loads(self.run_script('--json'))
        self.assertEqual(d['a_archiver'], ['Vieille'])

    def test_seuil_de_proposition(self):
        for i in range(self.SEUIL - 1):
            self.session(i, f'S{i}'); self.history(i, 1)
        self.assertNotIn(self.SUIVI, self.run_script())
        self.session(9, 'S9'); self.history(9, 1)
        out = self.run_script()
        self.assertIn(self.SUIVI, out)
        # The proposal points to Mon Studio's project view, never to a follow-up the plugin no longer ships.
        self.assertIn('Vue projet', out)
        self.assertNotIn('/cockpit:suivre', out)
        self.assertNotIn('contremaître', out)

    def test_candidates_a_archiver(self):
        self.session(1, 'Ancienne'); self.history(1, 10)
        self.session(2, 'Recente'); self.history(2, 1)
        d = json.loads(self.run_script('--json'))
        self.assertEqual(d['a_archiver'], ['Ancienne'])
        self.assertEqual(d['actives_n'], 1)

    def test_semaine_avec_sous_agent(self):
        self.session(1, 'Alpha'); self.history(1, 1, context=1000, sub_tokens=500)
        d = json.loads(self.run_script('--json', '--semaine'))
        w = d['semaine']
        self.assertEqual(w['jetons_relus'], 1000)
        self.assertEqual(w['jetons_sous_agents'], 500)
        self.assertEqual(w['part_sous_agents'], 33)
        self.assertEqual(w['plus_cheres'][0]['titre'], 'Alpha')
        self.assertIn('jetons des sous-agents', self.run_script('--semaine'))
        self.assertIn('contexte relu', self.run_script('--semaine'))
        self.assertNotIn('jetons relus', self.run_script('--semaine'))

    def test_semaine_compte_les_archivees_actives(self):
        self.session(1, 'Alpha'); self.history(1, 1, context=1000)
        self.session(2, 'Rangee', archived=True); self.history(2, 2, context=3000, sub_tokens=500)
        self.session(3, 'Vieille rangee', archived=True); self.history(3, 10, context=9000)
        d = json.loads(self.run_script('--json', '--semaine'))
        w = d['semaine']
        self.assertEqual(w['jetons_relus'], 4000)
        self.assertEqual(w['jetons_sous_agents'], 500)
        self.assertEqual(w['archivees_n'], 1)
        self.assertEqual([(r['titre'], r['archivee']) for r in w['plus_cheres']], [('Rangee', True), ('Alpha', False)])
        # The rest of the point still ignores archived sessions.
        self.assertEqual(d['actives'], ['Alpha'])
        self.assertEqual(d['a_archiver'], [])
        out = self.run_script('--semaine')
        self.assertIn('contexte relu : 4 000 (dont 1 session archivée)', out)
        self.assertIn('Rangee (archivée) : 3 500', out)
        self.assertNotIn('Alpha (archivée)', out)

    def test_semaine_archivee_planifiee_exclue_et_sans_mention(self):
        self.session(1, 'Alpha'); self.history(1, 1, context=1000)
        d = {'sessionId': 'local_3', 'title': 'Routine', 'cwd': str(self.studio), 'cliSessionId': 'cli3',
             'scheduledTaskId': 'tache', 'isArchived': True}
        (self.app / 'a' / 'b' / 'local_3.json').write_text(json.dumps(d)); self.history(3, 1, context=5000)
        self.assertEqual(json.loads(self.run_script('--json', '--semaine'))['semaine']['jetons_relus'], 1000)
        out = self.run_script('--semaine')
        self.assertNotIn('archivée', out)
        self.assertIn('contexte relu : 1 000', out)

def load_08():
    spec = importlib.util.spec_from_file_location('fais_le_point_08', SCRIPT_08)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Point08(FaisLePoint):
    """What only 0.8 does: Mon Studio folder override, follow-up offered early or reported, no foreman word."""

    def mirror(self, name, **fields):
        d = self.home / 'Mon Studio' / 'chantiers'
        d.mkdir(parents=True, exist_ok=True)
        (d / f'{name}.json').write_text(json.dumps(fields))

    def test_suivi_existant_par_dossiers(self):
        self.session(1, 'A'); self.history(1, 1)
        self.session(2, 'B'); self.history(2, 1)
        self.mirror('p', chantier='Projet A', dossiers=[str(self.studio)], tableau='https://claude.ai/artifact/abc')
        d = json.loads(self.run_script('--json'))
        self.assertFalse(d['proposer_suivi'])
        self.assertEqual(d['suivi']['tableau'], 'https://claude.ai/artifact/abc')
        out = self.run_script()
        self.assertIn('Ce Studio est déjà suivi : projet « Projet A »', out)
        self.assertNotIn(self.SUIVI, out)

    def test_suivi_existant_par_la_session_du_suivi(self):
        self.session(1, 'A'); self.history(1, 1)
        self.session(2, 'Suivi'); self.history(2, 1)
        self.mirror('p', chantier='Projet A', sessionId='local_2')
        self.assertIn('suivi : projet « Projet A »', self.run_script())

    def test_dossiers_s_ajoutent_au_studio_du_suivi(self):
        # `dossiers` adds folders (parc.py reading): the Studio of the follow-up's own session stays covered.
        self.session(1, 'A'); self.history(1, 1)
        self.session(2, 'Suivi'); self.history(2, 1)
        self.mirror('p', chantier='Projet A', sessionId='local_2', dossiers=[str(self.studio.parent / 'ailleurs')])
        self.assertIn('suivi : projet « Projet A »', self.run_script())

    def test_miroir_d_un_autre_studio_ou_archive(self):
        self.session(1, 'A'); self.history(1, 1)
        self.session(2, 'B'); self.history(2, 1)
        self.session(3, 'Vieux suivi', archived=True)
        self.mirror('autre', chantier='Projet B', dossiers=[str(self.studio.parent / 'ailleurs')])
        self.mirror('vieux', chantier='Projet C', sessionId='local_3')
        self.mirror('vieux.pass', dossiers=[str(self.studio)])
        d = json.loads(self.run_script('--json'))
        self.assertIsNone(d['suivi'])
        self.assertTrue(d['proposer_suivi'])

    def test_un_seul_sujet_pas_de_proposition(self):
        self.session(1, 'A'); self.history(1, 1)
        self.assertNotIn(self.SUIVI, self.run_script())

    def test_dossier_mon_studio_surcharge(self):
        autre = pathlib.Path(self.tmp.name) / 'ailleurs-mon-studio'
        (autre / 'chantiers').mkdir(parents=True)
        (autre / 'chantiers' / 'c.json').write_text(json.dumps({'piliers': [{'sessionId': 'local_2'}]}))
        self.session(1, 'Vieille'); self.history(1, 10)
        self.session(2, 'Pilier'); self.history(2, 10)
        env = dict(os.environ, HOME=str(self.home), MON_STUDIO=str(autre), MON_STUDIO_APP_SESSIONS=str(self.app),
                   MON_STUDIO_TRANSCRIPTS=str(self.tr))
        out = subprocess.run([sys.executable, '-I', str(SCRIPT_08), '--dossier', str(self.studio), '--json'], env=env,
                             capture_output=True, text=True).stdout
        self.assertEqual(json.loads(out)['a_archiver'], ['Vieille'])

    def test_ligne_de_suivi_sans_le_mot(self):
        for i in range(5):
            self.session(i, f'S{i}'); self.history(i, 1)
        out = self.run_script()
        self.assertIn('Tu as 5 sessions actives cette semaine : la vue projet de Mon Studio les montre ensemble', out)
        self.assertNotIn('contremaître', out.lower())


    def run_full(self, *args, app=None, tr=None):
        env = dict(os.environ, HOME=str(self.home), MON_STUDIO_APP_SESSIONS=str(app or self.app),
                   MON_STUDIO_TRANSCRIPTS=str(tr or self.tr))
        return subprocess.run([sys.executable, '-I', str(SCRIPT_08), '--dossier', str(self.studio), *args], env=env,
                              capture_output=True, text=True)

    def fake_parc(self, body):
        d = self.home / 'Mon Studio' / '.parc'
        d.mkdir(parents=True)
        (d / 'parc.py').write_text(body)

    def test_app_absente_arret_code_2(self):
        absent = pathlib.Path(self.tmp.name) / 'nulle-part'
        r = self.run_full(app=absent)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout.strip(), f"Je ne lis pas les sessions de l'app ({absent}) : point impossible.")
        self.assertNotIn('Sessions actives', r.stdout)
        j = self.run_full('--json', app=absent)
        self.assertEqual(j.returncode, 2)
        d = json.loads(j.stdout)
        self.assertEqual(d['chemin'], str(absent))
        self.assertIn('point impossible', d['erreur'])

    def test_app_sans_fiche_lisible_arret_code_2(self):
        (self.app / 'a' / 'b' / 'local_1.json').write_text('{pas du json')
        r = self.run_full()
        self.assertEqual(r.returncode, 2)
        self.assertIn('point impossible', r.stdout)
        self.assertNotIn('En attente de toi', r.stdout)
        self.assertNotIn('Finies', r.stdout)

    def test_transcripts_absents_ni_finies_ni_lourdes(self):
        for n, t in ((1, 'Alpha'), (2, 'Beta')):
            self.session(n, t)
            f = self.app / 'a' / 'b' / f'local_{n}.json'
            f.write_text(json.dumps(dict(json.loads(f.read_text()), lastActivityAt=int(datetime.datetime.now().timestamp() * 1000))))
        absent = pathlib.Path(self.tmp.name) / 'pas-de-transcripts'
        r = self.run_full(tr=absent)
        self.assertEqual(r.returncode, 0)
        lignes = r.stdout.splitlines()
        self.assertEqual(lignes[0], f'Je ne lis pas les transcripts ({absent}) : sessions finies et sessions lourdes non évaluées.')
        self.assertTrue(lignes[1].startswith('Sessions actives'))
        self.assertNotIn('Finies', r.stdout)
        self.assertNotIn('alléger', r.stdout)
        self.assertIn('Sessions actives cette semaine : 2', r.stdout)
        d = json.loads(self.run_full('--json', tr=absent).stdout)
        self.assertEqual(d['a_archiver'], [])
        self.assertEqual(d['lourdes'], [])
        self.assertEqual(d['avertissements'], [lignes[0]])

    def test_parc_hors_service_en_tete(self):
        self.session(1, 'Alpha'); self.history(1, 1)
        self.fake_parc("def charger_cache():\n    return {}\n"
                       "def construire(a, b, c, d):\n    return {'tableau': [], 'anciennes': [], "
                       "'lecture_app': {'etat': 'hors_service', 'raison': 'dossier illisible'}}\n")
        r = self.run_full()
        self.assertEqual(r.stdout.splitlines()[0],
                         "Mon Studio ne lit plus l'app : dossier illisible. Les demandes en attente ne sont pas fiables.")
        self.assertTrue(r.stdout.splitlines()[1].startswith('Sessions actives'))
        self.assertNotIn('En attente de toi', r.stdout)
        d = json.loads(self.run_full('--json').stdout)
        self.assertEqual(d['en_attente'], [])
        self.assertEqual(len(d['avertissements']), 1)

    def test_vingt_deux_attentes_toutes_listees(self):
        for i in range(22):
            self.session(i, f'Sujet{i}'); self.history(i, 1)
        rows = ",".join(f"{{'cle': 'local_{i}', 'session': 'Sujet{i}', 'detail': 'Q{i} titre{i}'}}" for i in range(22))
        self.fake_parc("def charger_cache():\n    return {}\n"
                       f"def construire(a, b, c, d):\n    return {{'tableau': [{rows}], 'anciennes': []}}\n")
        r = self.run_full()
        for i in range(22):
            self.assertIn(f'  - Sujet{i} : Q{i} titre{i}', r.stdout)
        self.assertEqual(len(json.loads(self.run_full('--json').stdout)['en_attente']), 22)

    def test_parc_en_echec_distinct_de_l_absence(self):
        self.session(1, 'Alpha'); self.history(1, 1)
        self.fake_parc("raise ValueError('cassé')\n")
        r = self.run_full()
        self.assertEqual(r.stdout.splitlines()[0],
                         'Mon Studio est installé mais ne répond pas (ValueError) : demandes en attente non listées.')
        self.assertNotIn('Vue Mon Studio absente', r.stdout)
        self.assertNotIn('En attente de toi', r.stdout)
        d = json.loads(self.run_full('--json').stdout)
        self.assertEqual(len(d['avertissements']), 1)


class Chemins08(unittest.TestCase):
    """Paths resolved per OS, in one place, without running anything."""

    def setUp(self):
        self.m = load_08()

    def test_sessions_app_macos(self):
        p = self.m.app_sessions_dir(env={}, platform='darwin', home='/h')
        self.assertEqual(p, pathlib.Path('/h/Library/Application Support/Claude/claude-code-sessions'))

    def test_sessions_app_windows(self):
        p = self.m.app_sessions_dir(env={'APPDATA': 'C:/Users/pm/AppData/Roaming'}, platform='win32', home='/h')
        self.assertEqual(p, pathlib.Path('C:/Users/pm/AppData/Roaming/Claude/claude-code-sessions'))

    def test_sessions_app_windows_sans_appdata(self):
        p = self.m.app_sessions_dir(env={}, platform='win32', home='/h')
        self.assertEqual(p, pathlib.Path('/h/AppData/Roaming/Claude/claude-code-sessions'))

    def test_variable_prioritaire_partout(self):
        for plat in ('darwin', 'win32', 'linux'):
            p = self.m.app_sessions_dir(env={'MON_STUDIO_APP_SESSIONS': '/x', 'APPDATA': '/y'}, platform=plat, home='/h')
            self.assertEqual(p, pathlib.Path('/x'))

    def test_mon_studio(self):
        self.assertEqual(self.m.mon_studio_dir(env={}, home='/h'), pathlib.Path('/h/Mon Studio'))
        self.assertEqual(self.m.mon_studio_dir(env={'MON_STUDIO': '/m'}, home='/h'), pathlib.Path('/m'))

    def test_transcripts(self):
        self.assertEqual(self.m.transcripts_dir(env={}, home='/h'), pathlib.Path('/h/.claude/projects'))
        self.assertEqual(self.m.transcripts_dir(env={'CLAUDE_CONFIG_DIR': '/c'}, home='/h'), pathlib.Path('/c/projects'))
        self.assertEqual(self.m.transcripts_dir(env={'MON_STUDIO_TRANSCRIPTS': '/t', 'CLAUDE_CONFIG_DIR': '/c'}), pathlib.Path('/t'))


class Proprete08(unittest.TestCase):
    """The 0.8 plugin skills are ready to ship: no machine path, the foreman word kept out of the point."""
    PLUGIN = ROOT
    SKILL = PLUGIN / 'skills' / 'point'
    KIT_PARTS = (PLUGIN / 'skills' / 'point', PLUGIN / 'regles')

    def test_pas_de_chemin_de_poste(self):
        for f in (f for part in self.KIT_PARTS for f in part.rglob('*')):
            if f.is_file() and '__pycache__' not in f.parts:
                t = f.read_text(encoding='utf-8', errors='replace')
                for motif in ('/Users/', '~/.claude/skills', 'launchd', 'installer.py', 'Library/Application Support/Claude/claude'):
                    if motif == 'Library/Application Support/Claude/claude' and f.suffix == '.py':
                        continue
                    self.assertNotIn(motif, t, f'{f.relative_to(ROOT)} : {motif}')

    def test_plus_de_pilote(self):
        for f in (f for part in self.KIT_PARTS for f in part.rglob('*')):
            if f.is_file() and '__pycache__' not in f.parts:
                self.assertNotIn('pilote:', f.read_text(encoding='utf-8', errors='replace'), f.name)

    def test_le_mot_reste_dans_le_mode_suivi(self):
        for f in (self.SKILL / 'SKILL.md', self.SKILL / 'scripts' / 'fais_le_point.py'):
            self.assertNotIn('contremaître', f.read_text(encoding='utf-8').lower(), f.name)


if __name__ == '__main__':
    unittest.main()
