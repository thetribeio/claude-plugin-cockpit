# Annonce pour le canal de l'équipe produit

À poster tel quel, un jour ouvré entre 8h et 20h.

---

**cockpit** : une page épinglée dans l'app Claude qui te dit ce que chaque session attend de toi, projet par projet, avec le bouton qui ouvre la bonne session.
La page ne coûte aucun token. Une fois le point du matin mis en route, son onglet Today a déjà lu tes mails, Slack et ton agenda. Le tout, règles et tâches du matin comprises, coûte environ 0,7 % de la semaine Claude, 2,03 $ par jour ouvré, 1,3 % au plus si chaque question coûte un aller-retour de plus (mesuré sur la place de l'auteur, poste par poste dans le README). La place de l'auteur est une place Team au budget relevé, que tout PM peut demander : à ce niveau, 1 % de la semaine vaut 14,5 $ ; sur une offre plus petite, les mêmes dollars pèsent plus.
`/cockpit:conflits` repère les documents du Studio qui présentent encore une règle qu'un mail ou une réunion a changée. Il te montre un aperçu et son coût, puis écrit dans le Studio, et dans la description des tickets touchés, seulement après ton go : des ajouts datés, jamais une suppression. Un premier rattrapage coûte environ 7 $ pour un Studio d'une centaine de sujets (0,5 % de la semaine), environ 10 $ pour 140 sujets ; une relecture ne coûte ensuite que ce qui a changé.
Installer : dans une session, `/plugin marketplace add thetribeio/claude-plugin-cockpit`, puis `/plugin install cockpit@thetribe-cockpit` (il te faut l'accès au dépôt sur GitHub). Il faut un Mac, l'app Claude de bureau et python3.
Premier geste : dans une session, tape `/cockpit:mon-studio`, réponds « go », puis Cmd+Q et rouvre l'app.
Tout se coupe en une phrase : `/cockpit:mon-studio`, puis « désactive Mon Studio ». Questions et retours dans ce fil.
