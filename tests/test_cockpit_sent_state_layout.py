"""Tests: the sent state of a line (« Envoi de « Qn … » à la session… », « copié : colle-le… ») has its own row.

It used to be one unbreakable run in the « Agir » column, which overflowed leftwards over the question title.
Now it takes a full row under the answer buttons, wraps inside its column, and is never positioned out of the flow.
python3 -m unittest discover -s tests"""
import _isolation  # noqa: F401 (HOME and env point to a temp folder)
import pathlib
import re
import unittest

PAGE = pathlib.Path(__file__).resolve().parents[1] / 'skills' / 'mon-studio' / 'assets' / 'page-servie.html'


def rules(selector):
    css = ''.join(re.findall(r'<style>(.*?)</style>', PAGE.read_text(encoding='utf-8'), re.S))
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [b for sel, b in re.findall(r'([^{}]+)\{([^{}]*)\}', css) if selector in [x.strip() for x in sel.split(',')]]


class SentState(unittest.TestCase):
    def test_the_sent_text_has_a_full_row_and_wraps(self):
        for sel in ('.reponses .envoye', '.reponses .copie'):
            body = ' '.join(rules(sel))
            self.assertIn('flex:1 1 100%', body, sel)
            self.assertIn('white-space:normal', body, sel)
            self.assertIn('overflow-wrap:anywhere', body, sel)
            self.assertIn('min-width:0', body, sel)

    def test_nothing_of_the_sent_state_is_out_of_the_flow(self):
        for sel in ('.envoye', '.reponses .envoye', '.reponses .copie', '.reponses'):
            body = ' '.join(rules(sel))
            self.assertNotIn('position:absolute', body, sel)
            self.assertNotIn('position:fixed', body, sel)

    def test_the_sent_text_is_in_the_answers_block_under_the_buttons(self):
        html = PAGE.read_text(encoding='utf-8')
        self.assertIn('<div class="reponses"><span class="envoye">', html)
        self.assertIn('"Envoi de « "', html)


if __name__ == '__main__':
    unittest.main()
