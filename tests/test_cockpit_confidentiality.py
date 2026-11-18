"""Confidentiality guard of the cockpit plugin, before it goes to every PM: python3 -m unittest discover -s tests

No file of the plugin (its three skills, the rules, the hooks, the docs, the tests, README and CHANGELOG) may name a
client or a real Jira ticket. Names are discovered at each run on the PM's Mac (the client folders of the shared drives, their first word
when it is distinctive, and the Jira keys of their project sheets); in CI, where no drive is mounted, the ticket
pattern still runs. Examples use PRJ and « Studio A », « projet pilote ». The PM's own boards and pinned page
(the artifact ids of ~/Mon Studio) are personal too: they are discovered on the Mac and refused as well."""
import _isolation  # HOME and env point to a temp folder; REAL_HOME is only read here, for discovery
import json
import pathlib
import re
import subprocess
import unicodedata
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES = {'PRJ', 'PRJB'}
STANDARDS = {'ISO', 'SHA', 'RFC', 'CVE', 'UTF', 'TLS', 'HTTP', 'WCAG', 'IA', 'QO'}
COMMON = {'interne', 'clients', 'client', 'archives', 'projet', 'projets', 'studio', 'thetribe', 'claude', 'exemple',
          'pilote', 'transport', 'budget', 'temps', 'suivi', 'agence', 'commerce', 'production', 'gestion', 'marketing',
          'design', 'paris', 'lyon', 'nantes', 'france', 'groupe', 'modeles', 'templates', 'test', 'cote', 'reseau'}
TICKET = re.compile(r'(?<![\w-])([A-Z][A-Z0-9]{1,9})-(\d+)(?![\w-])')


def norm(s):
    s = unicodedata.normalize('NFKD', str(s))
    return ''.join(c for c in s if not unicodedata.combining(c)).lower().strip()


def files():
    """Every file of the repository, tracked or about to be (untracked but not ignored)."""
    listed = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard'],
                            capture_output=True, text=True).stdout.splitlines()
    return [ROOT / f for f in listed if (ROOT / f).is_file()]


def own_artifact_ids():
    """The artifact ids of this PM's boards (~/Mon Studio/chantiers/*.json, `tableau`) and pinned page (cockpit.json)."""
    ids, home = set(), pathlib.Path.home() / 'Mon Studio'
    files = list(home.glob('chantiers/*.json')) + [home / '.parc' / 'cockpit.json']
    for f in files:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for v in (d.values() if isinstance(d, dict) else []):
            m = isinstance(v, str) and re.search(r'claude\.ai/artifact/([A-Za-z0-9_-]{8,})', v)
            if m:
                ids.add(m.group(1))
    return ids


# Jira keys of a project sheet, read as the studio-facts skill of product-kits reads them (studio.jira_keys): from
# URLs, in back ticks, then bare, on the sheet's Jira lines. This plugin does not carry studio-facts.
KEY_IN_URL = re.compile(r'/(?:projects|browse)/([A-Z][A-Z0-9]{1,9})(?:[-/?#]|\b)')
KEY_IN_TICKS = re.compile(r'`([A-Z][A-Z0-9]{1,9})`')
KEY_BARE = re.compile(r'(?<![\w/.-])([A-Z][A-Z0-9]{1,9})(?![\w/.-])')
NOT_KEYS = {'JIRA', 'JSM', 'TMA', 'BUILD', 'RUN', 'URL', 'API', 'MCP', 'PM', 'PO', 'UX', 'UI', 'NA', 'N', 'A',
            'V1', 'V2', 'V3', 'MVP', 'POC', 'SAV', 'IT', 'RH', 'CRM', 'ERP', 'SI', 'QA', 'OK', 'KO', 'TBD', 'TODO'}


def sheet_jira_keys(path):
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return set()
    keys = set()
    for line in text.splitlines():
        if 'jira' not in line.lower():
            continue
        keys.update(KEY_IN_URL.findall(line))
        keys.update(KEY_IN_TICKS.findall(line))
        keys.update(k for k in KEY_BARE.findall(re.sub(r'https?://\S+', ' ', line)) if not k.isdigit())
    return keys - NOT_KEYS


def studio_folders():
    """The client folders of the shared drives of the author's real home (read-only, never the temporary HOME)."""
    real = pathlib.Path(_isolation.REAL_HOME)
    return [d / '3. Clients' for d in real.glob('Library/CloudStorage/*/Drive partag*') if (d / '3. Clients').is_dir()]


def discover():
    """Client names (full, and their distinctive first word) and Jira keys, from the shared drives of this Mac."""
    names, keys = set(), set()
    for folder in studio_folders():
        for c in folder.iterdir():
            if not c.is_dir() or c.name.startswith(('_', '.')):
                continue
            names.add(c.name)
            first = c.name.split()[0]
            if len(first) >= 5:
                names.add(first)
            for sheet in list(c.glob('*/projet/fiche-projet.md')) + list(c.glob('projet/fiche-projet.md')):
                keys.update(sheet_jira_keys(sheet))
    names = {n for n in names if len(n) >= 4 and norm(n) not in COMMON}
    return names, keys - EXAMPLES


class Confidentiality(unittest.TestCase):
    def test_discovery_finds_the_clients_of_the_author(self):
        if not studio_folders():
            self.skipTest('no shared drive with Studios on this machine (CI)')
        names, _ = discover()
        self.assertTrue(names, 'Studios exist on this machine but no client was discovered: the discovery is broken, '
                               'the confidentiality guard below would pass empty')

    def test_no_client_name_nor_real_ticket(self):
        names, keys = discover()
        patterns = [(n, re.compile(r'(?<![a-z0-9])' + re.escape(norm(n)) + r'(?![a-z0-9])')) for n in sorted(names)]
        ids = own_artifact_ids()
        findings = []
        for path in files():
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            rel = path.relative_to(ROOT)
            for i, line in enumerate(text.splitlines(), 1):
                low = norm(line)
                findings += [f'{rel}:{i} client « {n} »' for n, rx in patterns if rx.search(low)]
                findings += [f'{rel}:{i} artifact personnel {a[:4]}…' for a in ids if a in line]
                for m in TICKET.finditer(line):
                    if m.group(1) in keys or m.group(1) not in EXAMPLES | STANDARDS:
                        findings.append(f'{rel}:{i} ticket {m.group(0)}')
        self.assertEqual(findings, [], 'À retirer avant toute diffusion :\n' + '\n'.join(findings[:40]))

    def test_the_guard_reads_the_whole_plugin(self):
        rel = [str(f.relative_to(ROOT)) for f in files()]
        for part, least in (('skills/mon-studio/', 6), ('skills/point/', 2), ('regles/', 5),
                            ('hooks/', 3), ('docs/', 2), ('tests/', 10)):
            self.assertGreaterEqual(len([f for f in rel if f.startswith(part)]), least, part)
        self.assertIn('README.md', rel)
        self.assertIn('CHANGELOG.md', rel)


if __name__ == '__main__':
    unittest.main()
