"""Tests: the pinned pages are republished only when the page really changes (PM, Q21, 2026-11-15).

install.py fingerprints the template without its comments and extra whitespace (page_sha). A comment or a space added
asks for no republication; a visible word, a CSS rule or a script line does, for the main page and the project pages.
A fingerprint noted the old way (raw sha) asks for one republication, then the new one is noted.

python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'mon-studio' / 'scripts'
TEMPLATE = ROOT / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'
MAIN = 'https://claude.ai/artifact/MainPage'
ALPHA_PAGE = 'https://claude.ai/artifact/AlphaPage'
ALPHA = '/Users/pm/Drive/Studio - Alpha'


def load_install(env):
    with mock.patch.dict(os.environ, env):
        os.environ.pop('MON_STUDIO', None)
        spec = importlib.util.spec_from_file_location('install_fingerprint_under_test', SCRIPTS / 'install.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def quiet(function, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args)


class Fingerprint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        env = {'HOME': str(self.root / 'home')}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.i = load_install(env)
        self.page = self.root / 'page-servie.html'
        shutil.copyfile(TEMPLATE, self.page)
        self.i.PAGE_SOURCE = self.page   # every change below is made on this copy, never on the template
        self.original = self.page.read_text(encoding='utf-8')
        self.base = self.i.page_sha()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def edited(self, old, new):
        self.assertEqual(self.original.count(old), 1, old)
        self.page.write_text(self.original.replace(old, new), encoding='utf-8')
        return self.i.page_sha()

    def test_comments_and_spaces_keep_the_fingerprint(self):
        for old, new in [
            ('<script>\n(function () {', '<script>\n// a new comment line\n(function () {'),
            ('  var SERVEUR = "host:mon-studio";', '  var SERVEUR = "host:mon-studio";   // trailing comment'),
            ('  var SERVEUR = "host:mon-studio";', '  /* a block\n     comment */\n  var SERVEUR  =  "host:mon-studio";'),
            ('  var SERVEUR = "host:mon-studio";', '\n\n      var SERVEUR = "host:mon-studio";   \n'),
            ('<style>', '<style>\n/* a CSS comment */'),
            ('.journal .quand { font:500 14px', '.journal .quand {   font:500 14px'),
            ('</style>', '</style>\n<!-- an HTML comment -->'),
        ]:
            with self.subTest(new=new):
                self.assertEqual(self.edited(old, new), self.base)

    def test_a_word_a_rule_or_a_script_line_change_it(self):
        for old, new in [
            ('Rien ne t\'attend.") + "</p>"', 'Rien ne t\'attend pas.") + "</p>"'),           # a visible word
            ('var SERVEUR = "host:mon-studio";', 'var SERVEUR = "host:mon studio";'),          # a space in a string
            ('.journal .quand { font:500 14px', '.journal .quand { font:600 14px'),            # a CSS rule
            ('.journal .quand {', '.journal  .quand-x {'),                                      # a selector
            ('  var SERVEUR = "host:mon-studio";', '  var SERVEUR = "host:mon-studio";\n  var x = 1;'),  # a line
            ('<h3>Attentes de tiers</h3>', '<h3>Attentes des tiers</h3>'),                      # HTML text
        ]:
            with self.subTest(new=new):
                self.assertNotEqual(self.edited(old, new), self.base)

    def test_only_comment_lines_lose_their_end(self):
        # A mark at the end of every line of the real template: it disappears only on a line that holds a comment, or
        # inside a block comment, so no code line is ever swallowed by a comment read in the wrong place.
        lines = self.original.split('\n')
        essence = self.i.page_essence('\n'.join(f'{l};QZQ{k}QZQ;' for k, l in enumerate(lines)))
        lost = {k for k in range(len(lines)) if f'QZQ{k}QZQ' not in essence}
        allowed, inside = set(), None
        for k, l in enumerate(lines):
            if inside or '//' in l or '/*' in l or '<!--' in l:
                allowed.add(k)
            for opening, closing in (('/*', '*/'), ('<!--', '-->')):
                if inside is None and opening in l and closing not in l[l.index(opening):]:
                    inside = closing
                elif inside == closing and closing in l:
                    inside = None
        self.assertTrue(lost)
        self.assertEqual([lines[k] for k in sorted(lost - allowed)], [])

    @unittest.skipUnless(shutil.which('node'), 'node absent')
    def test_the_stripped_scripts_still_parse(self):
        # The served code holds the page's one script; the shell (the fingerprinted page) its PROJET_FIXE and loader.
        shell = (TEMPLATE.parent / 'page-epinglee.html').read_text(encoding='utf-8')
        served = re.findall(r'<script>(.*?)</script>', self.i.page_essence(self.original), re.S)
        blocks = re.findall(r'<script>(.*?)</script>', self.i.page_essence(shell), re.S)
        self.assertEqual((len(served), len(blocks)), (1, 2))
        blocks += served
        for k, body in enumerate(blocks):
            f = self.root / f's{k}.js'
            f.write_text(body, encoding='utf-8')
            r = subprocess.run(['node', '--check', str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_regular_expressions_strings_and_templates_are_kept(self):
        e = self.i.page_essence
        js = lambda s: e('<script>' + s + '</script>')
        self.assertIn("x.replace(/'/g,\"&#39;\")", js("x.replace(/'/g, \"&#39;\");   // c"))
        self.assertIn('/^https:\\/\\//.test(u)', js('if (/^https:\\/\\//.test(u)) {} // c'))
        self.assertIn("a=b/c/d", js('a = b / c / d'))
        self.assertIn('"a // not a comment"', js('var s = "a // not a comment";'))
        self.assertIn('`x ${y ? `z` : ""} // kept`', js('var t = `x ${y ? `z` : ""} // kept`;'))
        self.assertNotEqual(js('a\n++b'), js('a++\nb'))
        self.assertEqual(js('return x // c'), js('return   x'))

    def test_doubtful_cases_count_as_changes(self):
        # Independent review of 2026-11-15: in doubt, the text is kept as it is, so a real change is never missed.
        e = self.i.page_essence
        js = lambda s: e('<script>' + s + '</script>')
        css = lambda s: e('<style>' + s + '</style>')
        self.assertNotEqual(js('if (a) /\\/\\//.test(x); y=1'), js('if (a) /\\/\\//.test(x); y=2'))
        self.assertNotEqual(js('x = a / b; s = "u // v"'), js('x = a / b; s = "u // w"'))
        self.assertNotEqual(js('return /*\n*/ x'), js('return x'))
        self.assertNotEqual(js('1 .toString()'), js('1.toString()'))
        self.assertNotEqual(css('.a/**/.b{color:red}'), css('.a .b{color:red}'))
        self.assertNotEqual(e('<p>x > y</p>'), e('<p>x> y</p>'))
        self.assertNotEqual(e('<input value="a  b">'), e('<input value="a b">'))
        self.assertNotEqual(e('<p title="a\nb">'), e('<p title="a b">'))
        self.assertNotEqual(e('<p>foo <style>p{}</style>bar'), e('<p>foo<style>p{}</style>bar'))
        self.assertNotEqual(e('<pre>a  b</pre>'), e('<pre>a b</pre>'))
        # And what does not change the page still does not change it.
        self.assertEqual(e('<p  class="x" >a\n   b</p>'), e('<p class="x">a b</p>'))
        self.assertEqual(e('<p>a <!-- c --> b</p>'), e('<p>a b</p>'))
        self.assertEqual(css('.a { color : red }'), css('.a{color : red}'))

    def test_an_old_fingerprint_asks_once_then_the_new_one_is_noted(self):
        self.i.APP_SESSIONS.mkdir(parents=True)
        self.i.INTERNAL.mkdir(parents=True)
        raw = hashlib.sha256(self.page.read_bytes()).hexdigest()
        self.i.record_state(version=self.i.plugin_version(), page=MAIN, pageSha=raw, pageTools=self.i.PAGE_TOOLS,
                            pages_projet={ALPHA: ALPHA_PAGE},
                            pages_projet_etat={ALPHA: {'sha': raw, 'tools': self.i.PAGE_TOOLS}})
        s = self.i.status()
        self.assertFalse(s['pageCurrent'])
        self.assertIn('republish_page', s['todo'])
        self.assertIn('republish_project_pages', s['todo'])
        self.assertEqual(quiet(self.i.record_page, MAIN), 0)
        self.assertEqual(quiet(self.i.record_project_page, ALPHA, ALPHA_PAGE), 0)
        state = json.loads(self.i.STATE.read_text(encoding='utf-8'))
        self.assertTrue(state['pageSha'].startswith('v2:'))
        s = self.i.status()
        self.assertTrue(s['pageCurrent'])
        self.assertNotIn('republish_page', s['todo'])
        self.assertNotIn('republish_project_pages', s['todo'])
        # A comment added afterwards: still nothing to republish; a visible word: both again.
        self.edited('<style>', '<style>\n/* later */')
        s = self.i.status()
        self.assertNotIn('republish_page', s['todo'])
        self.assertNotIn('republish_project_pages', s['todo'])
        self.edited('<h3>Attentes de tiers</h3>', '<h3>Attentes des tiers</h3>')
        s = self.i.status()
        self.assertIn('republish_page', s['todo'])
        self.assertIn('republish_project_pages', s['todo'])


if __name__ == '__main__':
    unittest.main()
