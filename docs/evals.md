# Evals : Claude suit-il encore le plugin ?

Les tests unitaires vérifient les scripts. Les evals vérifient le modèle : avec cockpit installé, Claude répond-il comme les règles et les skills le disent ? Pour le mainteneur seulement, avant chaque publication.

## Ce qui est vérifié

Cinq cas, dans `evals/`, chacun sur une promesse du plugin :

| Cas | Promesse | Modèle |
|---|---|---|
| `deux-decisions` | Deux décisions attendues du PM finissent le message sous « À trancher », en « Qn · titre », la recommandée en premier, aucune question ailleurs. | Sonnet |
| `rien-a-faire` | Rien n'est attendu du PM : le message finit par « Rien à faire de ton côté. », sans question. | Sonnet |
| `cadrage-propose` | Pour cadrer plusieurs points, une réponse proposée par point, à valider ou corriger, plutôt que des questions ouvertes. | Sonnet |
| `question-faite` | Le PM dit « Q3 c fait » : le message suivant ne liste plus Q3 et garde Q4 ouverte. | Haiku |
| `installation-plan` | Premier `/cockpit:mon-studio` : le plan donne chaque coût en tokens et en part de la semaine, demande un seul go, et rien n'est posé avant. | Sonnet |

Chaque cas tourne dans un bac à sable : un HOME temporaire, jamais le vrai `~/Mon Studio` ni `~/.claude`. Le petit script `scaffold.sh` de chaque cas y pose ce qu'il faut : `Mon Studio/.parc/cockpit.json` pour allumer les hooks du plugin (règles au démarrage, rappel à chaque message), ou le dossier des sessions de l'app pour l'installation. Les entrées sont fictives (projet « Atlas »).

Chaque cas tourne aussi sans le plugin (colonne Δ du rapport) : l'écart montre ce que le plugin apporte. `question-faite` part d'une conversation déjà commencée (`historique.jsonl`) et tourne avec le plugin seulement.

## La commande

Depuis la racine du dépôt :

```
claude plugin eval . --scaffold --trust-plugin --no-publish --allow-tools "Bash(python3:*)" --max-cost-usd 1.5 -j 3
```

- `--scaffold` lance les `scaffold.sh` du dépôt, dans le bac à sable.
- `--no-publish` garde le rapport en local : rien n'est publié sur claude.ai.
- `--allow-tools "Bash(python3:*)"` laisse `installation-plan` lancer `install.py status` et `plan`, rien d'autre.
- `--max-cost-usd 1.5` arrête la série au-delà de 1,5 $ (0,1 % de la semaine).
- Un seul cas : ajouter `--case installation-plan`.

Les résultats vont dans `evals/results/`, hors du dépôt git.

## Ce que coûte une série

Environ 0,65 $, soit 0,045 % de la semaine (1 % de la semaine = 14,5 $), mesuré le 2026-11-10 : environ 250 000 tokens écrits en cache, 130 000 relus et 15 000 en sortie, juges Haiku compris. Une minute environ avec `-j 3`.

## Lire le résultat

- Chaque cas a un score de 0 à 100 %, la somme pondérée de ses correcteurs. La commande sort en erreur si un cas est sous 100 %.
- Les correcteurs `regex` et `tool_used` sont exacts : un texte présent ou absent, un outil appelé ou pas.
- Les correcteurs `llm` sont trois votes d'un juge Haiku. Un vote partagé (« FAIL PASS FAIL ») dit un cas limite : lire la réponse dans le rapport avant de conclure.
- Le rapport HTML, dans le dossier de résultats, montre pour chaque cas la réponse de Claude, les votes et l'écart avec la série sans plugin.
- Un échec avec le plugin et un Δ nul : la règle ne passe plus. Un échec isolé sur un juge partagé : relancer ce cas seul avant de corriger.
