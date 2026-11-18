# Modèle et effort : le plus petit réglage qui fait le travail

Pourquoi : chaque session relit toute sa conversation à chaque échange ; un modèle trop fort ou un contexte trop lourd use le quota sans meilleur travail.

1. Choisir le modèle et l'effort tâche par tâche :
   - Haiku, effort low : lire, chercher, lister, extraire, recopier, reformater, compter, vérifier un état.
   - Sonnet, effort medium : rédaction courante (compte rendu, mail, message), synthèse de documents, mise à jour de fichiers, petit script.
   - Opus, effort medium : livrable lu par un client ou la direction, cadrage, arbitrage, chiffrage, analyse croisée de plusieurs sources.
   - Opus, effort high : seulement un problème vraiment difficile, ou après un échec au niveau du dessous.
   - Ultra Code ou effort max : jamais de soi-même ; le proposer au PM pour une grosse tâche bien définie.
   - Une tâche planifiée prend le plus petit modèle qui fait le travail.
   - Une session que Claude lance reçoit son modèle dès sa création, selon ce barème (le plugin refuse un lancement sans modèle).
2. La session garde le dialogue avec le PM et les gestes de quelques secondes. Le travail de lecture ou de rédaction part dans un sous-agent réglé selon ce barème, avec un brief complet : fichiers, attendu, règles qui s'appliquent.
3. Le sous-agent rend une conclusion courte, jamais le contenu des fichiers ; la session la relit avant de la présenter. Deux ou trois sous-agents au plus en même temps, une opération lourde (suite de tests complète, grosse lecture) à la fois ; un sous-agent ne laisse aucun processus en route.
4. Monter d'un cran seulement après un échec constaté, jamais par précaution.
5. Le contexte coûte aussi : chercher dans un fichier plutôt que le lire en entier, envoyer les sorties longues dans un fichier, ne pas recharger ce qui est déjà dans la conversation.
