"""Ce que chaque session d'un Studio montre elle-même comme attente, sans tenir compte des miroirs de chantier.
Sert à repérer une question posée hors du registre (dans un fil rouge, par exemple) et pas encore au tableau.
Usage : python3 -I ~/Mon\ Studio/.parc/lignes-brutes.py "<nom du Studio, tel que Mon Studio l'affiche>"
"""
import importlib.util, pathlib, sys, tempfile, time

parc_py = pathlib.Path.home() / 'Mon Studio/.parc/parc.py'
spec = importlib.util.spec_from_file_location('parc', parc_py)
parc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parc)
parc.CHANTIERS = pathlib.Path(tempfile.mkdtemp())  # aucun miroir : les lignes brutes de chaque session
if len(sys.argv) != 2:
    sys.exit(__doc__.strip())
studio = sys.argv[1]
e = parc.construire(7, 7, time.time(), parc.charger_cache())
for l in parc.pour_la_page(e)['lignes']:
    if l['studio'] == studio:
        print('-', l['session'], '|', l['ouvrir'], '|', l['verbe'], '|', (l['complet'] or '').replace('\n', ' ')[:200])
