"""Tests: a morning point that did not run is visible (2026-11-10): python3 -m unittest discover -s tests

On a working day after the task's hour and its margin, when ~/Mon Studio/matin.json is not today's, the page (Today
tab) and mon-studio.md say « Point du matin pas passé aujourd'hui (dernier : JJ/MM) », never another day's content;
only when the task exists. `install.py status` asks for `morning_blocked` when the task's latest run started today or
on the last working day, more than 30 minutes ago, and matin.json was not written since. Temporary HOME only."""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import datetime as dt
import importlib.util
import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
PAGE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'


def local(y, mo, d, h, mi=0):
    return time.mktime(dt.datetime(y, mo, d, h, mi).timetuple())


TUESDAY_9 = local(2026, 11, 10, 9)
TUESDAY_7 = local(2026, 11, 10, 7, 45)
SATURDAY_9 = local(2026, 11, 14, 9)


def load(name, path, home, studio):
    with mock.patch.dict(os.environ, {'HOME': str(home), 'MON_STUDIO': str(studio)}):
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.studio = self.home / 'Mon Studio'
        self.studio.mkdir()
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home), 'MON_STUDIO': str(self.studio)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def task(self):
        t = self.home / '.claude' / 'scheduled-tasks' / 'point-du-matin' / 'SKILL.md'
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text('consigne', encoding='utf-8')

    def point(self, genere_le, mtime=None):
        f = self.studio / 'matin.json'
        f.write_text(json.dumps({'genere_le': genere_le, 'a_traiter': []}), encoding='utf-8')
        if mtime:
            os.utime(f, (mtime, mtime))


class Missed(Base):
    def setUp(self):
        super().setUp()
        self.m = load('matin_missed', SCRIPTS / 'matin.py', self.home, self.studio)

    def test_a_working_day_after_the_hour_says_the_last_day(self):
        self.task()
        self.point('2026-11-06T07:31:00')
        self.assertEqual(self.m.retard(TUESDAY_9), "Point du matin pas passé aujourd'hui (dernier : 06/11)")
        self.assertEqual(self.m.pour_la_page(TUESDAY_9), {'etat': 'pas_passe'}, 'old content never shown')

    def test_no_file_at_all(self):
        self.task()
        self.assertEqual(self.m.retard(TUESDAY_9), "Point du matin pas passé aujourd'hui")

    def test_silent_before_the_hour_on_weekends_without_task_or_when_written(self):
        self.point('2026-11-06T07:31:00')
        self.assertIsNone(self.m.retard(TUESDAY_9), 'no task: nothing promised')
        self.task()
        self.assertIsNone(self.m.retard(TUESDAY_7), 'the task may still be running')
        self.assertIsNone(self.m.retard(SATURDAY_9))
        self.point('2026-11-10T07:32:00')
        self.assertIsNone(self.m.retard(TUESDAY_9))

    def test_the_page_shows_the_sentence(self):
        page = PAGE.read_text(encoding='utf-8')
        self.assertIn('esc(m.retard || "Point du matin pas encore passé")', page)

    def test_projets_and_mon_studio_md_carry_it(self):
        self.task()
        self.point('2026-11-06T07:31:00')
        projets = load('projets_missed', SCRIPTS / 'projets.py', self.home, self.studio)
        m = projets.matin_pour_la_page(TUESDAY_9, [], {'projets': []})
        self.assertEqual(m['retard'], "Point du matin pas passé aujourd'hui (dernier : 06/11)")
        parc = load('parc_missed', SCRIPTS / 'parc.py', self.home, self.studio)
        self.assertEqual(parc.retard_du_matin(TUESDAY_9), m['retard'])
        md = parc.rendre_md({'genere': TUESDAY_9, 'tableau': [], 'pastilles_lues': True, 'matin_retard': m['retard'],
                             'lecture_app': {'etat': 'ok', 'raison': ''}})
        self.assertIn("**Point du matin pas passé aujourd'hui (dernier : 06/11).**", md)


class Blocked(Base):
    def setUp(self):
        super().setUp()
        self.i = load('install_missed', SCRIPTS / 'install.py', self.home, self.studio)

    def run_at(self, t):
        return {'scheduledTaskId': 'point-du-matin', 'createdAt': int(t * 1000), 'model': 'claude-sonnet-5-5'}

    def test_a_run_today_that_wrote_nothing_is_blocked(self):
        start = local(2026, 11, 10, 7, 30)
        self.point('2026-11-06T07:31:00', mtime=local(2026, 11, 6, 7, 31))
        self.assertTrue(self.i.morning_blocked(self.run_at(start), TUESDAY_9))
        os.remove(self.studio / 'matin.json')
        self.assertTrue(self.i.morning_blocked(self.run_at(start), TUESDAY_9))

    def test_not_blocked_when_written_still_running_old_or_replayed(self):
        start = local(2026, 11, 10, 7, 30)
        self.point('2026-11-10T07:40:00', mtime=local(2026, 11, 10, 7, 40))
        self.assertFalse(self.i.morning_blocked(self.run_at(start), TUESDAY_9))
        self.assertFalse(self.i.morning_blocked(self.run_at(local(2026, 11, 10, 8, 50)), TUESDAY_9),
                         'started 10 minutes ago: still running')
        self.assertFalse(self.i.morning_blocked(self.run_at(local(2026, 11, 5, 7, 30)), TUESDAY_9), 'an old run')
        replay = local(2026, 11, 10, 8, 0)
        self.assertFalse(self.i.morning_blocked(self.run_at(replay), TUESDAY_9), "today's point already there")
        self.assertFalse(self.i.morning_blocked(None, TUESDAY_9))

    def test_monday_looks_at_friday(self):
        friday = local(2026, 11, 6, 7, 30)
        self.point('2026-11-05T07:31:00', mtime=local(2026, 11, 5, 7, 31))
        self.assertTrue(self.i.morning_blocked(self.run_at(friday), local(2026, 11, 9, 7, 0)))

    def test_status_asks_for_morning_blocked(self):
        task = self.i.MORNING_TASK
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text('x', encoding='utf-8')
        folder = self.i.APP_SESSIONS / 'a' / 'b'
        folder.mkdir(parents=True)
        (folder / 'local_r.json').write_text(json.dumps(self.run_at(TUESDAY_9 - 3600)), encoding='utf-8')
        with mock.patch.object(self.i.sys, 'platform', 'darwin'), mock.patch.object(self.i.time, 'time', lambda: TUESDAY_9):
            s = self.i.status()
        self.assertTrue(s['morningBlocked'])
        self.assertIn('morning_blocked', s['todo'])
        skill = (ROOT / 'skills' / 'mon-studio' / 'SKILL.md').read_text(encoding='utf-8')
        entry = next(l for l in skill.splitlines() if l.strip().startswith('- `morning_blocked`'))
        self.assertIn('Toujours autoriser', entry)
        self.assertIn('Exécuter maintenant', entry)


if __name__ == '__main__':
    unittest.main()
