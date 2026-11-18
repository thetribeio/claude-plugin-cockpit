"""Tests: the plugin prices tokens from one list (2026-11-15, item 1 of the review before sharing): Mon Studio's plan
and the conflicts estimate used to price Haiku ten times apart. python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OnePriceList(unittest.TestCase):
    def test_install_and_conflicts_read_the_same_prices(self):
        registre = load('registre_t', ROOT / 'skills/conflits/scripts/registre.py')
        install = load('install_t', ROOT / 'skills/mon-studio/scripts/install.py')
        conflits = load('conflits_t', ROOT / 'skills/conflits/scripts/conflits.py')
        self.assertEqual(install.PRICES, registre.PRIX)
        self.assertEqual(conflits.PRIX, registre.PRIX)

    def test_haiku_is_priced_at_haiku_5_5(self):
        registre = load('registre_t2', ROOT / 'skills/conflits/scripts/registre.py')
        self.assertEqual(registre.PRIX['haiku'], (0.10, 0.50, 0.01))

    def test_no_other_price_table_in_the_scripts(self):
        table = re.compile(r"'haiku'\s*:\s*\(")
        for path in ROOT.glob('skills/*/scripts/*.py'):
            if path.name == 'registre.py':
                continue
            self.assertIsNone(table.search(path.read_text(encoding='utf-8')), path.name)


if __name__ == '__main__':
    unittest.main()
