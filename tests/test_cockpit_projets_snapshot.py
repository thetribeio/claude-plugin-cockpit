"""Tests: the snapshot of the Studios for the connector (projets-sources.json, 2026-11-05): python3 -m unittest discover -s tests

The connector is launched by the desktop app, and macOS refuses it any read in the Drive (PermissionError): the list
by project then showed every Studio as « membre », with no « À toi » and no entries. A run of projets.py outside the
connector writes what it read of each Studio to ~/Mon Studio/.parc/projets-sources.json; the connector falls back to it
for a Studio it cannot read, questions staying live. A SessionStart and Stop hook (hooks/projets_instantane.py) keeps
it fresh in the background, throttled, silent.

The refusal is played with file modes (chmod 000), on synthetic Studios; the real app, home and identity are never used."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from test_cockpit_projets import FRIDAY, MONDAY, REPORT, ROOT, Base

HOOK = ROOT / 'hooks' / 'projets_instantane.py'
HOOKS = json.loads((ROOT / 'hooks' / 'hooks.json').read_text(encoding='utf-8'))['hooks']


@unittest.skipIf(os.geteuid() == 0, 'root lit tout : le refus ne se joue pas')
class Snapshot(Base):
    def snapshot(self):
        return json.loads((self.mon_studio / '.parc' / 'projets-sources.json').read_text(encoding='utf-8'))

    def tearDown(self):
        for p, mode in reversed(getattr(self, 'refused', [])):   # before the temporary folder goes
            os.chmod(p, mode)
        super().tearDown()

    def refuse(self, *paths):
        self.refused = getattr(self, 'refused', [])
        for p in paths:
            self.refused.append((p, os.stat(p).st_mode))
            os.chmod(p, 0)

    def files(self):
        projet = pathlib.Path(self.alpha) / 'projet'
        return projet / 'fiche-projet.md', projet / '.ingestion-auto-state.json'

    def connector(self, when=MONDAY + 60):
        e = {'tableau': self.table, 'lecture_app': {'etat': 'ok', 'raison': ''}}
        return self.p.calculer(e=e, maintenant=when, metas=self.metas, depuis_connecteur=True)

    def test_a_run_outside_the_connector_writes_what_it_read(self):
        self.runs(self.alpha, (FRIDAY, REPORT), reglees=[{'ts': '2026-11-01T10:00:00Z', 'texte': 'Autre chose',
                                                          'preuve': 'x'}])
        self.compute()
        d = self.snapshot()['dossiers'][self.alpha]
        self.assertEqual((d['pm'], d['ingestion'], d['lu']), ('Éric  EXEMPLE', True, MONDAY))
        self.assertEqual([(n['ts'], n['actions']) for n in d['passages']], [(FRIDAY, ['Valider le **devis** avant jeudi.'])])
        self.assertEqual(len(d['passages'][0]['entres']), 2)
        self.assertEqual(d['reglees'], [{'ts': '2026-11-01T10:00:00Z', 'texte': 'Autre chose', 'preuve': 'x'}])
        self.assertNotIn('refus', d)

    def test_the_connector_falls_back_when_the_drive_refuses(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute()
        self.refuse(*self.files())
        self.table = [self.question()]
        out = self.connector()
        b = self.block(out)
        self.assertEqual(b['role'], 'pm')
        self.assertEqual(self.types(out), ['a_toi', 'entree', 'entree', 'question'])   # the question stays live
        self.assertEqual(b['lu'], int(MONDAY * 1000))
        self.assertEqual(out['studios'][0]['lu'], int(MONDAY * 1000))

    def test_without_a_snapshot_the_connector_does_as_before(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.refuse(*self.files())
        self.table = [self.question()]
        out = self.connector()
        self.assertEqual((self.block(out)['role'], self.types(out)), ('membre', ['question']))
        self.assertNotIn('lu', self.block(out))

    def test_a_readable_studio_stays_live_in_the_connector(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute()
        self.runs(self.alpha)                                        # no run any more: the live read wins
        out = self.connector()
        self.assertEqual(self.types(out), ['a_toi'])                 # seen once, it stays; the entries are gone
        self.assertNotIn('lu', out['studios'][0])

    def test_a_refused_stat_keeps_a_known_studio(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute()
        self.refuse(pathlib.Path(self.alpha) / 'projet')
        out = self.connector()
        self.assertEqual(self.types(out), ['a_toi', 'entree', 'entree'])
        self.assertEqual([s['dossier'] for s in out['studios']], [self.alpha])

    def test_the_connector_never_writes_it_and_a_refused_run_keeps_the_last_one(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute()
        before = self.snapshot()
        self.refuse(*self.files())
        self.connector(MONDAY + 600)
        self.assertEqual(self.snapshot(), before)
        self.compute(MONDAY + 900)                                   # outside the connector, refused too
        self.assertEqual(self.snapshot()['dossiers'], before['dossiers'])

    def test_the_trial_writes_no_snapshot(self):
        self.runs(self.alpha, (FRIDAY, REPORT))
        self.compute(write=False)
        self.assertFalse((self.mon_studio / '.parc' / 'projets-sources.json').exists())


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ms = pathlib.Path(self.tmp.name) / 'Mon Studio'
        self.parc = self.ms / '.parc'
        self.parc.mkdir(parents=True)
        self.ran = pathlib.Path(self.tmp.name) / 'ran'
        # A stand-in for the installed projets.py: it notes each run, then writes the snapshot as the real one does.
        (self.parc / 'projets.py').write_text(
            'import pathlib, sys\n'
            f'with open({str(self.ran)!r}, "a") as f: f.write("x")\n'
            'pathlib.Path(__file__).with_name("projets-sources.json").write_text("{}")\n'
            'print("ok bruyant"); print("bruit", file=sys.stderr)\n', encoding='utf-8')

    def hook(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('MON_STUDIO')}
        env['MON_STUDIO'] = str(self.ms)
        r = subprocess.run([sys.executable, str(HOOK)], input='{"hook_event_name": "Stop"}', capture_output=True,
                           text=True, env=env, timeout=30)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))

    def runs(self, n, attente=10):
        """How many runs of the stand-in, waiting up to `attente` s for the n-th (short when none is expected)."""
        fin = time.time() + attente
        while time.time() < fin and (len(self.ran.read_text()) if self.ran.exists() else 0) < n:
            time.sleep(0.05)
        time.sleep(0.2)
        return len(self.ran.read_text()) if self.ran.exists() else 0

    def age(self, name, seconds):
        t = time.time() - seconds
        os.utime(self.parc / name, (t, t))

    def test_launches_in_the_background_then_is_throttled(self):
        self.hook()
        self.assertEqual(self.runs(1), 1)
        self.hook()                                                  # snapshot and launch both fresh
        self.assertEqual(self.runs(2, 1.5), 1)
        self.age('projets-sources.json', 600)
        self.hook()                                                  # the launch mark is still fresh
        self.assertEqual(self.runs(2, 1.5), 1)
        self.age('projets-sources.lance', 600)
        self.hook()
        self.assertEqual(self.runs(2), 2)

    def test_a_fresh_snapshot_launches_nothing(self):
        (self.parc / 'projets-sources.json').write_text('{}')
        self.hook()
        self.assertEqual(self.runs(1, 1.5), 0)
        self.assertFalse((self.parc / 'projets-sources.lance').exists())

    def test_nothing_without_mon_studio(self):
        (self.parc / 'projets.py').unlink()
        self.hook()
        self.assertEqual(self.runs(1, 1.5), 0)
        self.assertEqual(sorted(p.name for p in self.parc.iterdir()), [])

    def test_declared_on_start_and_stop_guarded_and_silent(self):
        for event in ('SessionStart', 'Stop'):
            (h,) = [h for g in HOOKS[event] for h in g['hooks'] if 'hooks/projets_instantane.py' in h['command']]
            self.assertIn('[ -f "$HOME/Mon Studio/.parc/projets.py" ]', h['command'])
            self.assertIn('>/dev/null 2>&1 || true', h['command'])
            self.assertLessEqual(h['timeout'], 10)
            r = subprocess.run(['/bin/sh', '-c', h['command']], capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, HOME=self.tmp.name, CLAUDE_PLUGIN_ROOT=str(ROOT)))
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))


if __name__ == '__main__':
    unittest.main()
