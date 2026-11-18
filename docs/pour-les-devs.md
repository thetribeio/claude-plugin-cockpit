# Pour les devs

Constats relevés avant le partage, laissés en l'état. Aucun ne change ce que voit un PM.

## Structure

- Cinq gros fichiers : `skills/mon-studio/scripts/parc.py` (5 200 lignes), `skills/conflits/scripts/conflits.py` (2 800), `skills/mon-studio/scripts/mcp_mon_studio.py` (1 800), `skills/mon-studio/scripts/install.py` (1 800), `skills/mon-studio/assets/page-servie.html` (2 300, le code de la page, servi par le connecteur ; la page publiée n'est qu'une coquille, `page-epinglee.html`).
- Peu de code mort. Trois fonctions définies et jamais appelées : `raise_floor`, `cles_fermables`, `starts_with`.
- Le vocabulaire d'une version retirée (« contremaître », « chantier ») reste dans les noms internes du code et dans le dossier `~/Mon Studio/chantiers`, que `hooks/hooks.json` vérifie. Le renommer demande de migrer ce dossier chez les PM déjà installés.
- `parc.py`, `question.py` et `skills/point/scripts/fais_le_point.py` ont chacun leur copie de la règle qui trouve le dossier des sessions de l'app : `parc.py` et `question.py` tournent depuis leur copie dans `~/Mon Studio/.parc/`. `tests/test_assembly.py` les tient égales.

## Tests

- `python3 -m unittest discover -s tests < /dev/null`.
- `tests/_isolation.py` pointe `HOME` vers un dossier temporaire et audite les ouvertures de fichiers réels (`open`) ; il ne surveille ni `mkdir` ni `rename`.
- La garde de confidentialité (`tests/test_cockpit_confidentiality.py`) découvre les noms de clients dans les Drive partagés du Mac où elle tourne : en CI, aucun Drive n'est monté, seul le motif des tickets Jira tourne. Elle ne regarde ni les noms de personnes ni l'historique git.

## CI

- `.github/workflows/skills.yml` lance `check_skills.py` puis toute la suite sous Ubuntu. Non vérifié que la suite y passe : les tests du réveil des sessions et des chemins de l'app supposent macOS.
