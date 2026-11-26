"""Tests: the three band headers of the main board look the same (PM, 2026-11-19).

« D'abord » and « Ensuite » (rows of the table) were set in 15 px body text, « Peut attendre » (a section title) in the
22 px display style of every h2. All three now take the h2 style. Studios and texts are made up."""
import pathlib
import re
import unittest

PAGE = pathlib.Path(__file__).resolve().parents[1] / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'


def regle(css, selecteur):
    m = re.search(r'(?m)^' + re.escape(selecteur) + r'\s*\{([^}]*)\}', css)
    assert m, selecteur
    return m.group(1)


def propriete(corps, nom):
    m = re.search(r'(?<![\w-])' + nom + r'\s*:\s*([^;]+?)\s*(?:;|$)', corps)
    return m.group(1) if m else None


class BandHeaders(unittest.TestCase):
    def setUp(self):
        self.css = PAGE.read_text(encoding='utf-8').split('</style>')[0]
        self.h2 = regle(self.css, 'h2')
        self.bande = regle(self.css, 'tr.bande-titre td')

    def test_same_size_as_peut_attendre(self):
        self.assertEqual(propriete(self.bande, 'font-size'), propriete(self.h2, 'font-size'))
        self.assertEqual(propriete(self.bande, 'font-size'), '22px')

    def test_same_family_and_weight(self):
        titres = regle(self.css, 'h1, h2')
        self.assertEqual(propriete(self.bande, 'font-family'), propriete(titres, 'font-family'))
        self.assertEqual(propriete(self.bande, 'font-weight'), propriete(titres, 'font-weight'))

    def test_peut_attendre_is_an_h2_without_its_own_size(self):
        html = PAGE.read_text(encoding='utf-8')
        self.assertRegex(html, r'<h2><button[^>]*id="attendre-bascule"')
        self.assertNotIn('font-size', regle(self.css, 'button.replier'))


if __name__ == '__main__':
    unittest.main()
