# Mes marqueurs pour Mon Studio

Une expression par puce. Mon Studio les lit en plus de ce qu'il reconnaît seul (une question, « ton go »,
« à toi de… », une case à cocher, un bloc à coller). Ton fichier est `~/.claude/cockpit/marqueurs.md` ; il survit
aux mises à jour du plugin. Pour ajouter une expression, dis à Claude « ajoute ce marqueur » ou lance
`parc.py --marqueur demande|rien|trancher "<expression>"`.

Exemple : les marques d'un PM qui fait finir chaque réponse par ses questions numérotées. Mon Studio les connaît
déjà, elles montrent la forme.

## Demande

Une phrase qui contient l'expression attend une réponse ou un geste de toi.

- (Recommandé)
- j'attends ton feu vert

## Rien à faire

Une phrase qui finit par l'expression dit que le message n'attend rien de toi.

- Rien à faire de ton côté
- Rien d'autre à faire de ton côté

## À trancher

Un intitulé de section dont les éléments sont des questions pour toi.

- À trancher
- To decide
