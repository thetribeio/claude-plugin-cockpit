# Passation : une session neuve plutôt qu'un énorme contexte

Pourquoi : après un résumé de contexte, ou au-delà de quelques centaines de milliers de tokens, chaque réponse coûte cher et le détail des premiers échanges est déjà perdu.

1. Après un résumé de contexte (la conversation a été compactée), proposer au PM de passer la main à une session neuve : par l'outil natif `hand_off_to_session` s'il existe dans la session, sinon par le prompt complet à coller.
2. Quand le hook de session lourde le signale (300 000 tokens par défaut, puis tous les 100 000), même proposition : une session neuve pour un sujet distinct, sinon à la fin de la tâche en cours.
3. Avant de passer la main, écrire la passation dans les fichiers du projet (décisions, préférences, état) et l'annoncer en une ligne.
4. Une session qui doit vivre au premier niveau de la barre latérale (fil rouge, kit) : après le go du PM, la lancer soi-même avec le brief complet (`start_session` ou `hand_off_to_session`), puis la remonter par `detach_session`. Le prompt à coller ne sert que si l'outil manque ou refuse. La question qui la demandait est close dès que la session tourne.
5. Proposer, jamais imposer : le PM décide.
