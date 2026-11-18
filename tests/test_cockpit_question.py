"""Tests of the question number taken as the question is asked: python3 -m unittest discover -s tests

Every session of a project takes the next number from a counter shared on the Mac and writes its line in the
project's mirror, in one call, so Mon Studio and its project view show it at once (no published board since
2026-11-03). Mon Studio folders, app session cards and mirrors here are synthetic."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import concurrent.futures
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
QUESTION = SCRIPTS / 'question.py'
spec = importlib.util.spec_from_file_location('parc', SCRIPTS / 'parc.py')
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)

FOREMAN, KIT, OTHER = 'local_foreman', 'local_kit', 'local_elsewhere'
BOARD = 'https://claude.ai/artifact/AbCdEf'


class Chantier(unittest.TestCase):
    """A Mon Studio folder with one chantier, and the app's cards of three sessions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.studio = root / 'studios' / 'Studio-Essai'
        (self.studio / 'projet').mkdir(parents=True)
        _isolation.make_studio(self.studio)
        self.mon_studio = root / 'Mon Studio'
        (self.mon_studio / 'chantiers').mkdir(parents=True)
        self.app = root / 'app'
        self.card(FOREMAN, '* Studio-Essai · contremaître', self.studio)
        self.card(KIT, 'ᐅ Kit A · tâche', self.studio / 'projet')
        self.card(OTHER, 'Ailleurs', root / 'studios' / 'Autre')
        self.mirror = self.mon_studio / 'chantiers' / 'essai.json'
        self.write_mirror({'chantier': 'Essai', 'studio': 'Studio-Essai', 'tableau': BOARD, 'sessionId': FOREMAN,
                           'session': '* Studio-Essai · contremaître', 'attentes': [],
                           'lanes': [{'id': 'A', 'name': 'Kit A', 'sessionId': KIT, 'pillarId': 'local_pillar'}]})

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, sid, title, cwd, **more):
        folder = self.app / 'acct' / 'org'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{sid}.json').write_text(json.dumps(dict({'sessionId': sid, 'title': title, 'cwd': str(cwd)}, **more)))

    def write_mirror(self, m):
        self.mirror.write_text(json.dumps(m, ensure_ascii=False))

    def run_tool(self, *args, sid=None, stdin='', cwd=None, now=None):
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_HOST_SESSION_ID', 'MON_STUDIO_NOW')}
        env.update(MON_STUDIO=str(self.mon_studio), MON_STUDIO_APP_SESSIONS=str(self.app))
        if sid:
            env['CLAUDE_CODE_HOST_SESSION_ID'] = sid
        if now:
            env['MON_STUDIO_NOW'] = now
        r = subprocess.run([sys.executable, '-I', str(QUESTION), *args], input=stdin, capture_output=True,
                           text=True, env=env, cwd=cwd or self.tmp.name)
        return r

    def take(self, now=None):
        """The number `take` gives (its first line), « Q3 »."""
        return self.run_tool('take', 'Essai', now=now).stdout.splitlines()[0]

    def line(self, n):
        """The mirror line `new` wrote for question n."""
        (a,) = [a for a in json.loads(self.mirror.read_text())['attentes'] if parc.num_question(a.get('titre')) == n]
        return a

    def hook(self, sid, cwd):
        return self.run_tool('hook', sid=sid, stdin=json.dumps({'session_id': 'cli', 'cwd': str(cwd)})).stdout


class Counter(Chantier):
    def test_simultaneous_takes_never_get_the_same_number(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            got = list(pool.map(lambda _: self.take(), range(48)))
        self.assertEqual(sorted(got, key=lambda q: int(q[1:])), [f'Q{n}' for n in range(1, 49)])

    def test_a_number_open_in_the_mirror_is_never_given(self):
        m = json.loads(self.mirror.read_text())
        m['attentes'] = [{'type': 'decision', 'titre': 'Q1 · Kit A : la suite ?'},
                         {'type': 'decision', 'titre': 'Q3 · Kit A : et après ?'}]
        self.write_mirror(m)
        self.assertEqual(self.take(), 'Q2')
        self.assertEqual(self.take(), 'Q4')



class Hook(Chantier):
    def test_silent_without_a_chantier(self):
        self.assertEqual(self.hook(OTHER, pathlib.Path(self.tmp.name) / 'studios' / 'Autre'), '')

    def test_silent_outside_the_app(self):
        self.assertEqual(self.hook(None, self.studio), '')

    def test_silent_without_mirrors(self):
        self.mirror.unlink()
        self.assertEqual(self.hook(KIT, self.studio), '')

    def test_an_archived_anchor_session_keeps_the_project(self):
        self.write_mirror(dict(json.loads(self.mirror.read_text()), registre=True))
        self.card(FOREMAN, '* Studio-Essai · contremaître', self.studio, isArchived=True)
        self.assertIn('du projet « Essai »', self.hook(KIT, self.studio))

    def test_silent_when_the_foreman_of_a_mirror_from_before_is_archived(self):
        self.card(FOREMAN, '* Studio-Essai · contremaître', self.studio, isArchived=True)
        self.assertEqual(self.hook(KIT, self.studio), '')

    def test_a_session_of_the_studio_gets_the_instruction(self):
        out = self.hook('local_new', self.studio / 'projet')
        self.assertIn('fait partie du projet « Essai »', out)
        self.assertNotIn('contremaître', out)
        self.assertIn('question.py', out)
        self.assertIn('« Qn · <titre court, 60 caractères au plus> : <la question précise> »', out)

    def test_a_session_the_mirror_names_elsewhere_gets_it_too(self):
        m = json.loads(self.mirror.read_text())
        m['couloirs'] = [{'titre': 'Ailleurs', 'sessionId': OTHER}]
        self.write_mirror(m)
        self.assertIn('du projet « Essai »', self.hook(OTHER, pathlib.Path(self.tmp.name) / 'studios' / 'Autre'))



class KnownStudios(unittest.TestCase):
    """Two Studios known in ~/Mon Studio/projets.json, no register yet, and a folder outside both."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.mon_studio = root / 'Mon Studio'
        self.mon_studio.mkdir()
        self.app = root / 'app'
        self.a, self.b, self.out = root / 'studios' / 'Studio-A', root / 'studios' / 'Studio-B', root / 'ailleurs'
        for d in (self.a / 'projet', self.b / 'projet', self.out):
            d.mkdir(parents=True)
        _isolation.make_studio(self.a)
        _isolation.make_studio(self.b)
        (self.mon_studio / 'projets.json').write_text(json.dumps({'studios': [
            {'nom': 'Studio A', 'dossier': str(self.a), 'role': 'pm'},
            {'nom': 'Studio B', 'dossier': str(self.b), 'role': 'membre'}]}))
        self.cards = {'local_a1': self.a / 'projet', 'local_a2': self.a, 'local_b1': self.b, 'local_out': self.out}
        for sid, cwd in self.cards.items():
            folder = self.app / 'acct' / 'org'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f'{sid}.json').write_text(json.dumps({'sessionId': sid, 'title': sid, 'cwd': str(cwd)}))

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args, sid):
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_HOST_SESSION_ID', 'MON_STUDIO_NOW')}
        env.update(MON_STUDIO=str(self.mon_studio), MON_STUDIO_APP_SESSIONS=str(self.app), CLAUDE_CODE_HOST_SESSION_ID=sid)
        stdin = json.dumps({'cwd': str(self.cards[sid])}) if args == ('hook',) else ''
        return subprocess.run([sys.executable, '-I', str(QUESTION), *args], input=stdin, capture_output=True, text=True,
                              env=env, cwd=self.tmp.name)

    def registers(self):
        d = self.mon_studio / 'chantiers'
        return sorted(p.name for p in d.glob('*.json') if not p.name.endswith('.numeros.json')) if d.is_dir() else []

    def ask(self, sid, title):
        r = self.run_tool('new', '--kind', 'decision', '--title', title, sid=sid)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout.splitlines()[0].split(' · ')[0]


class StudioRegister(KnownStudios):
    """A Studio known in ~/Mon Studio/projets.json needs no init: its sessions get the instruction, its first `new`
    creates its register, numbers are per Studio, and Mon Studio shows the number the session wrote."""

    def test_a_session_of_a_known_studio_without_register_gets_the_instruction(self):
        out = self.run_tool('hook', sid='local_a1').stdout
        self.assertIn('fait partie du projet « Studio A »', out)
        self.assertIn('question.py', out)
        self.assertEqual(self.registers(), [])   # nothing written before the first question

    def test_a_session_outside_any_known_studio_gets_nothing(self):
        self.assertEqual(self.run_tool('hook', sid='local_out').stdout, '')
        r = self.run_tool('new', '--title', 'Ici ?', sid='local_out')
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.registers(), [])

    def test_first_new_creates_the_register_with_number_one(self):
        self.assertEqual(self.ask('local_a1', 'On garde le logo ?'), 'Q1')
        self.assertEqual(self.registers(), ['studio-a.json'])
        m = json.loads((self.mon_studio / 'chantiers' / 'studio-a.json').read_text())
        self.assertEqual((m['chantier'], m['dossiers'], m['sessionId']), ('Studio A', [str(self.a)], 'local_a1'))
        self.assertEqual([a['titre'] for a in m['attentes']], ['Q1 · On garde le logo ?'])
        self.assertEqual(self.ask('local_a2', 'Et la couleur ?'), 'Q2')   # same Studio, same register
        self.assertEqual(self.registers(), ['studio-a.json'])

    def test_a_second_studio_has_its_own_numbering(self):
        self.ask('local_a1', 'Un ?')
        self.ask('local_a1', 'Deux ?')
        self.assertEqual(self.ask('local_b1', 'Chez B ?'), 'Q1')
        self.assertEqual(self.registers(), ['studio-a.json', 'studio-b.json'])
        self.assertEqual(self.ask('local_a2', 'Trois ?'), 'Q3')

    def test_settle_closes_on_proof_as_elsewhere(self):
        self.ask('local_a1', 'On publie ?')
        self.assertEqual(self.run_tool('settle', 'Q1', '--decision', 'go', sid='local_b1').returncode, 3)
        r = self.run_tool('settle', 'Q1', '--decision', 'go', sid='local_a1')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(json.loads((self.mon_studio / 'chantiers' / 'studio-a.json').read_text())['attentes'], [])

    def test_mon_studio_and_the_project_view_show_the_number_new_gave(self):
        # The answer buttons send « Qn <choice> » back to the session: the number shown must be the one it wrote.
        self.ask('local_b1', 'Chez B ?')
        given = self.ask('local_a1', 'On garde le logo ? Réponds « Qn : oui » ou « Qn : non ».')
        self.assertEqual(given, 'Q1')
        metas = [{'id': sid, 'archivee': False, 'cwd': str(cwd), 'titre': sid, 'parent': None, 'tache': None}
                 for sid, cwd in self.cards.items()]
        saved = parc.CHANTIERS
        parc.CHANTIERS = self.mon_studio / 'chantiers'
        try:
            fresh, old = parc.lignes_et_anciennes([], metas, [], 7, __import__('time').time(), {})
            cle_de = parc.projets_des_sessions(metas)   # as construire() keys each line to its project
            for l in fresh + old:
                l['projet'] = cle_de(l.get('ouvrir') or l.get('cle') or '', l.get('chantier'))
            e = {'genere': __import__('time').time(), 'tableau': fresh, 'anciennes': old, '_metas': metas, '_sessions': []}
            view = parc.vue_projet(e, str(self.a))
        finally:
            parc.CHANTIERS = saved
        (line,) = [l for l in fresh if l.get('projet') == str(self.a)]
        self.assertEqual(line['question'], given)
        self.assertEqual(line['ouvrir'], 'local_a1')   # the buttons answer the session that asked
        self.assertTrue(line['copie_numero'])            # so the page shows and sends its number
        self.assertIn('« Q1 : oui »', line['complet'])
        self.assertEqual([l['question'] for l in view['questions']], [given])


class OddStudios(KnownStudios):
    """A Studio known by its project card only (no manifest yet), and a Studio folder holding another Studio: a
    question asked from one session is settled from another session of the same Studio."""

    def setUp(self):
        super().setUp()
        root = pathlib.Path(self.tmp.name)
        self.c, self.inner = root / 'studios' / 'Studio-C', self.a / 'sous' / 'Studio-D'
        (self.c / 'projet').mkdir(parents=True)
        (self.c / 'projet' / 'fiche-projet.md').write_text('# Studio C\n')
        _isolation.make_studio(self.inner)
        (self.mon_studio / 'projets.json').write_text(json.dumps({'studios': [
            {'nom': 'Studio A', 'dossier': str(self.a), 'role': 'pm'},
            {'nom': 'Studio C', 'dossier': str(self.c), 'role': 'pm'},
            {'nom': 'Studio D', 'dossier': str(self.inner), 'role': 'pm'}]}))
        for sid, cwd in {'local_c1': self.c, 'local_c2': self.c / 'projet'}.items():
            self.cards[sid] = cwd
            (self.app / 'acct' / 'org' / f'{sid}.json').write_text(
                json.dumps({'sessionId': sid, 'title': sid, 'cwd': str(cwd)}))

    def test_a_card_only_studio_settles_from_its_other_session(self):
        self.assertEqual(self.ask('local_c1', 'Un ?'), 'Q1')
        self.assertEqual(self.ask('local_c2', 'Deux ?'), 'Q2')
        r = self.run_tool('settle', 'Q2', '--decision', 'oui', sid='local_c2')
        self.assertEqual(r.returncode, 0, r.stdout)
        m = json.loads((self.mon_studio / 'chantiers' / 'studio-c.json').read_text())
        self.assertEqual([a['titre'] for a in m['attentes']], ['Q1 · Un ?'])

    def test_a_studio_holding_another_settles_from_its_other_session(self):
        self.assertEqual(self.ask('local_a1', 'Un ?'), 'Q1')
        self.assertEqual(self.ask('local_a2', 'Deux ?'), 'Q2')
        r = self.run_tool('settle', 'Q2', '--decision', 'oui', sid='local_a2')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.registers(), ['studio-a.json'])


class MirrorFromBefore(Chantier):
    """A chantier mirror as main wrote it: no `dossiers`, no `registre`, its foreman in a folder with no Studio mark,
    or in a folder grouping several Studios. The upgrade keeps main's covering rule for it: nothing renumbered, nothing
    orphaned."""

    def setUp(self):
        super().setUp()
        (self.studio / '.claude' / '.studio-manifest.json').unlink()
        m = json.loads(self.mirror.read_text())
        m['attentes'] = [{'type': 'decision', 'titre': 'Q1 · ancienne question', 'sessionId': 'local_by_hand'}]
        self.write_mirror(m)
        self.card('local_by_hand', 'Réflexion', self.studio / 'projet')   # a session no mirror names

    def test_a_new_question_keeps_the_mirror_and_its_numbering(self):
        r = self.run_tool('new', '--title', 'Et ensuite ?', sid='local_by_hand')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('Q2 ·', r.stdout)
        self.assertEqual(sorted(p.name for p in (self.mon_studio / 'chantiers').glob('*.json')
                                if not p.name.endswith('.numeros.json')), ['essai.json'])

    def test_its_old_line_can_still_be_settled(self):
        r = self.run_tool('settle', 'Q1', '--decision', 'oui', sid='local_by_hand')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(json.loads(self.mirror.read_text())['attentes'], [])

    def test_a_folder_grouping_studios_still_covers_its_sessions(self):
        _isolation.make_studio(self.studio / 'sous' / 'Autre-Studio')
        self.assertEqual(self.hook('local_by_hand', self.studio / 'projet').count('du projet « Essai »'), 1)


class NewLine(Chantier):
    def new(self, *extra):
        return self.run_tool('new', '--kind', 'decision', '--subject', 'Kit A', '--title', 'Q9 · la suite, garder ou arrêter ?',
                             '--detail', 'Réponds « Qn : garder » ou « Qn : arrêter ».', *extra, sid=KIT)

    def test_one_call_writes_the_mirror_line(self):
        r = self.new()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('ArtifactData', r.stdout)
        a = self.line(1)
        self.assertEqual((a['titre'], a['ou'], a['source'], a['pilier'], a['type'], a['sessionId']),
                         ('Q1 · Kit A : la suite, garder ou arrêter ?', 'Kit A', KIT, 'local_pillar', 'decision', KIT))
        self.assertRegex(a['doc'], r'^n\d{8}-1$')
        self.assertTrue(a['declencheur'].startswith('posée par la session « ᐅ Kit A · tâche »'))
        self.assertFalse((self.mon_studio / '.parc' / 'questions').exists())   # no pending file any more
        # Mon Studio no longer shows the session's own « Q1 · » line apart: the project's mirror carries it.
        on_board = parc.au_tableau([json.loads(self.mirror.read_text())])
        asked = {'num': 1, 'titre': 'Q1 · Kit A : la suite', 'suite': '', 'depuis': parc.ts_iso(a['depuis']) + 5}
        self.assertTrue(parc.deja_au_tableau(asked, KIT, FOREMAN, on_board))

    def test_qn_in_the_detail_becomes_the_number_taken(self):
        self.run_tool('take', 'Essai')   # Q1 is taken: this question gets Q2
        self.new()
        self.assertEqual(self.line(2)['detail'], 'Réponds « Q2 : garder » ou « Q2 : arrêter ».')

    def test_a_bare_qn_in_a_sentence_stays(self):
        r = self.run_tool('new', '--title', 'Je remplace « Qn » par le vrai numéro ?',
                          '--detail', 'Le script met le numéro à la place de « Qn ». Réponds « Qn : 1 ».', sid=KIT)
        doc = self.line(1)
        self.assertEqual(doc['titre'], 'Q1 · Kit A : Je remplace « Qn » par le vrai numéro ?', r.stdout)
        self.assertEqual(doc['detail'], 'Le script met le numéro à la place de « Qn ». Réponds « Q1 : 1 ».')

    def test_a_session_without_a_lane_enters_under_chantier(self):
        self.card('local_new', 'Nouvelle', self.studio)
        r = self.run_tool('new', '--title', 'Une question', sid='local_new')
        doc = self.line(1)
        self.assertEqual((doc['ou'], doc['titre']), ('Nouvelle', 'Q1 · Une question'), r.stdout)

    def test_no_chantier_no_number(self):
        r = self.run_tool('new', '--title', 'Une question', sid=OTHER)
        self.assertEqual(r.returncode, 3)
        self.assertFalse((self.mon_studio / 'chantiers' / 'essai.numero').exists())


if __name__ == '__main__':
    unittest.main()
