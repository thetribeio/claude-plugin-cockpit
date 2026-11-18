# Changelog

## 0.3.5 · 2026-11-18

Les textes disent ce que le plugin fait vraiment, relus avant la première publication. Effet pour le PM : il sait ce que le plugin touche sur son Mac et dans ses Studios avant de dire go.

- Le README dit ce que le connecteur fait d'une session endormie quand tu réponds depuis le tableau : il lit la liste des processus et le journal de l'app, arrête le processus qui la tient quand son tour est fini, puis la relance ; en cours de tour, la réponse attend.
- Ce qui écrit dans un Studio est dit exactement : `/cockpit:conflits` après ton go, et la relecture du lundi du point du matin (registre et plan dans `projet/.conflits/`) quand elle tourne.
- L'annonce suit les chiffres du README (environ 7 $ pour une centaine de sujets, 10 $ pour 140) ; le refus d'un lancement sans modèle se dit sans « une fois ».
- Le contrôle du modèle et celui du format des questions se coupent chacun par un interrupteur (`switch controle-modele off`, `switch controle-format off`) et ne s'appliquent plus qu'aux sessions de l'app de bureau.
- Ton nom de PM se pose par `switch pm "Prénom Nom"` ; sans réglage ni git, le nom du compte Mac est utilisé : un PM sans git retrouve ses lignes « À toi ».
- Deux notes internes (publication, brouillon de PR du catalogue) quittent le dépôt ; libellés (« fils rouges », « Plus tard »), liste des hooks et des autorisations remis à jour.
- Le README ouvre sa section des coûts par un résumé : installation, premier relevé des conflits, part fixe et part variable de chaque jour.

## 0.3.4 · 2026-11-18

L'onglet « Conflits » dit vrai après un relevé, et son coût annoncé suit le coût mesuré. Effet pour le PM : il voit les cas dès qu'ils sont écrits, sait ce qu'un relevé va coûter, et n'a plus à demander la suite.

- L'onglet « Conflits » montre les cas dès que le relevé écrit au registre : `conflits.py` recopie le registre dans l'instantané de Mon Studio après chaque écriture, sans modèle ; si la session des conflits a travaillé depuis la dernière copie, l'onglet le dit au lieu de paraître vide.
- Le coût annoncé d'un relevé suit le premier relevé mesuré sur un vrai Studio (97 sujets : 5,2 $ mesurés, 6,1 $ estimés) : socle de 78 000 tokens par sous-agent, session des conflits à 100 000 tokens relus à chaque appel, marge x 1,15. Un Studio d'une centaine de sujets s'annonce vers 0,5 % de la semaine ; les estimations gardées de l'ancien barème ne s'affichent plus.
- Après l'écriture au registre, la session enchaîne tout de suite sur les décisions (évidents d'abord), sans attendre que le PM le demande, y compris après `--decisions-seules`.
- La session des conflits se met d'elle-même au premier niveau, avec son Studio, quand une autre session l'a lancée.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.3.3 · 2026-11-18

Une question tient sur une ligne, avec son titre court, et un clic montre la question précise ; ses boutons disent leurs mots. Effet pour le PM : il lit ce qu'il y a à décider sans relire deux fois la même phrase, répond d'un bouton qui dit son option, et ne voit plus les lignes qui n'attendent rien. Sur 103 lignes réelles, 75 dépliaient leur propre début.

- Règle 2 du format des réponses : « Qn · <titre court qui synthétise la décision, 60 caractères au plus> : <la question précise>. », options « 1) **<libellé de 4 mots au plus>** : <option entière> », la recommandée en premier, puis « Pourquoi : … Si tu ne fais rien : … », avec un exemple. L'étiquette d'impact ne compte pas dans les 60 caractères. Les règles passent à 9 741 octets (plafond 9 800).
- Nouveau hook de fin de tour (`format_questions.py`) : une question dont le titre dépasse 60 caractères, sans question précise après « : », ou dont les options n'ont pas de libellé court en gras renvoie la session, une fois, reposter seulement son bloc « À trancher » corrigé, mêmes numéros. Chaque message relu ajoute une ligne, sans son texte, à `~/Mon Studio/.parc/format-questions.jsonl`, pour mesurer.
- Au tableau, une question au nouveau format montre son titre seul ; une question plus ancienne, son titre et le début de la question, coupés sur un mot avec « … » : une ligne, jamais deux. Même règle pour les lignes sans numéro et pour une question posée en encadré.
- Toute ligne se déplie. Le dépli d'une question : la question précise (jamais le titre), les options entières, puis Recommandé, Pourquoi, Ce qu'on attend de toi, Si tu ne fais rien, Pièce, seulement celles que la question écrit.
- Un bouton par option : son libellé en gras, sinon l'option coupée sur un mot sous 28 caractères ; la recommandée en premier ; plus de « 1 », « 2 », « 3 » ni de bouton recommandé en double. La réponse envoyée reste le numéro (« Q8 1 »). Un bouton long ne déborde plus.
- Une ligne « Vérifier » qui n'attend rien du PM quitte le tableau et les pages projet ; elle reste dès qu'elle demande quelque chose.
- Un titre garde son étiquette d'impact : elle ne coupe plus le titre. Le cache de Mon Studio est refait au prochain passage (version 25).
- Le contrôle des lignes signale un dépli qui répète son titre, une ligne de plus de 90 caractères et une ligne d'information au tableau.
- La page servie, le calcul et un hook changent ; la page épinglée n'est pas à republier, l'app est à redémarrer.
- Rangement : une session confiée à ranger mais restée ouverte est reproposée six heures plus tard, trois fois au plus.

## 0.3.2 · 2026-11-18

Ce qui change : le README et le plan d'installation disent ce que le cockpit fait vraiment, avant le go du PM. Pourquoi : l'audit final avant partage (Q1, Q3) a trouvé trois promesses que le code ne tient pas et deux comportements non annoncés. Effet pour le PM : rien ne change sur sa page ; un nouveau PM lit des coûts et des limites justes.

- Le registre des conflits est dit tenu par `/cockpit:conflits` seul : aucune version publiée de l'ingestion automatique n'y écrit.
- La relecture du lundi est dite sautée au-delà de 90 000 caractères d'extraits, le cas normal aujourd'hui (350 sujets et plus par semaine sur les Studios mesurés) ; son coût de 0,04 $ par lundi ne vaut que pour une petite semaine. Une ligne de plus dans « Limites connues ».
- Le plan d'installation (`install.py plan`) et « Ce qu'il installe » annoncent le rangement automatique des sessions finies, allumé par défaut, et le refus d'un lancement sans modèle.

## 0.3.1 · 2026-11-17

Ce qui change : une question à laquelle le PM a répondu par son numéro quitte le tableau, même quand la réponse de la session la cite encore. Pourquoi : « Q14 ok » restait au tableau, parce que la session avait répondu « Audit final (Q14) : j'attends… », et cette simple citation était lue comme la question reposée (même cas pour une Q43 sur un autre Studio). Effet pour le PM : sur sa page du 17/11, 2 lignes déjà répondues partent, rien d'autre ne bouge.

- Seule une sortie qui repose la question (« À trancher », « Encore ouvert », un menu) la rouvre après la réponse du PM ; une phrase qui la cite rend compte de la réponse. Même règle pour les questions des tableaux de chantier.
- Les notes que l'app met devant les mots du PM (« Linked sessions now : q18-conflits = … ») ne comptent plus comme une citation de Q18.
- Le cache de Mon Studio est refait au prochain passage (version 24).
- Le README, le skill et la note de la tâche disent Sonnet pour la vérification du point du matin, comme le code depuis la 0.3.0.
- La ligne du point du matin arrêté tient sur sa ligne du tableau (120 signes), et les extraits gardés d'une version précédente montrent le nom d'outil traduit, plus `mcp__…`.

## 0.3.0 · 2026-11-17

Première version partagée : elle réunit tout ce qui précède et ajoute deux choses. Effet pour le PM : plus de lignes Slack réglées quittent le tableau, et il peut corriger lui-même l'ordre du tableau s'il allume l'interrupteur.

- La vérification du point du matin passe de Haiku à Sonnet (décision du PM, Q10). Essai sur les mêmes 18 lignes : Haiku en fermait de 4 à 7 selon le passage, Sonnet en ferme 7, avec 2 suites justes. Coût : 0,55 $ par jour ouvré au lieu de 0,03 $ ; point du matin complet 1,04 $ au lieu de 0,53 $ ; ensemble du cockpit 0,7 % de la semaine au lieu de 0,5 % (seuil 2 %). À l'installation, choisir Sonnet comme modèle de la tâche « Point du matin · vérification » dans « Planifiées ».
- Le PM peut corriger le classement du tableau (interrupteur `reclassement`, coupé par défaut : `install.py switch reclassement on|off`). Allumé, un seul bouton par ligne du tableau principal, « Pas si urgent » dans « D'abord », « À faire d'abord » ailleurs, un clic de plus annule ; son classement l'emporte sur le calcul tant que la ligne existe (« classé par toi »), et chaque clic est noté dans `~/Mon Studio/.parc/reclassements.jsonl`, qui ne quitte pas le Mac. Coupé, rien ne change.
- La page servie et le connecteur changent ; la page épinglée n'est pas à republier, l'app est à redémarrer.

## 0.2.30 · 2026-11-17

Ce qui change : tout le reste de la revue d'usage du 17/11, en une version. Pourquoi : des doublons, des boutons qui ne servaient à rien et un détail vide faisaient relire le tableau au lieu d'agir. Effet pour le PM : un bouton par geste, une fiche par question, des vieilles lignes rangées seules, et un Today qui sert de stand-up du matin.

- Un geste fait ailleurs n'a plus qu'un bouton, « C'est fait » : il répond à la session et retire la ligne (10 secondes pour annuler).
- Recommandation propre : « (recommandée) » reconnue, même placée avant son option ; jamais une adresse comme libellé ; plus de « : . » en tête de texte ; plus de « Oui (recommandé) » à côté de « Oui » ; un bouton de 28 caractères au plus.
- Le détail d'une question de session devient une fiche : Pourquoi · Ce qu'on attend de toi · Si tu ne fais rien · Recommandation · Pièce. Une rubrique vide ne s'affiche pas, une ligne qui n'ajoute rien au titre ne se déplie plus. La règle des questions demande « Pourquoi : … » et « Si tu ne fais rien : … » (9 338 octets de règles, sous le plafond).
- « Pas encore » devient « Plus tard » : la ligne est masquée jusqu'à demain, sur le tableau seulement, rien n'est envoyé à la session (une session qui attend dans son hook finit seule son attente, 10 minutes par défaut).
- Une ligne sans mouvement depuis 21 jours passe dans « Peut attendre ». « Peut attendre » et « Anciennes » se rangent par projet, avec « Tout retirer pour ce projet » et « Tout annuler ». Une session arrêtée depuis plus de 48 h propose « Abandonner » : la ligne part et la session est confiée au rangement pour archivage, à ton prochain message dans une session. Le compte des anciennes ne compte plus les lignes déjà retirées.
- Une question relayée (« réponds dans X », « (dans X) », « À répondre dans X ») est cachée quand la session X porte la même question ; dans le doute, elle reste avec « aussi dans X ». Sans modèle.
- Attentes de tiers : bouton « Reçu », et plus de doublon avec une ligne du tableau sur le même sujet.
- Today, le stand-up du matin : plus de renvoi vers les demandes du tableau ; plus d'entrée écrite par toi-même dans « Pour info » ; « Sans réponse » (ce que tu attends des autres depuis plus de 2 jours ouvrés : attentes de tiers des chantiers, et ce que le point du matin relève dans `sans_reponse`) ; à côté de chaque réunion de l'agenda, le nombre de questions ouvertes de son projet ; les réunions sans compte rendu, venues du bloc Projets.
- Petits retraits : « Fermé depuis hier » quitte le bloc Projets ; « Sans action » est replié et ne garde que les projets clients ; un seul style pour « Ouvrir ↗ ».
- La page servie change ; elle vient du connecteur, sans republication. Le connecteur change aussi (`clore` : `plus_tard`, `abandon`, clés « t… ») : `install.py repair`.

À faire ensuite, à ne pas oublier (décision Q1 du PM, 17/11) :
1. Après la publication : la pièce dans le détail des relectures (« C'est bon » / « Corrections »).
2. Puis mesurer sur une semaine les lignes sans réponse fermée ; au-delà d'une ligne sur cinq, une réponse en une phrase derrière un bouton « Autre ».
3. La tâche du point du matin peut écrire `sans_reponse` (mails du PM restés sans réponse) : sa consigne reste à compléter.

## 0.2.29 · 2026-11-17

Le détail d'une ligne ne répète plus son titre. Effet pour le PM : sur une question numérotée, le détail commence par le texte utile (propositions, contexte), puis la date d'apparition.

- Quand l'énoncé du détail est le titre de la ligne tel qu'affiché (à l'espace ou la ponctuation finale près), il n'est pas redit ; un titre coupé ou raccourci garde son énoncé complet.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.28 · 2026-11-17

Une page projet ne montre plus que son projet, et ses fils rouges redeviennent une vraie liste, réservée aux sessions où tu reviens discuter. Effet pour le PM : plus de sessions d'autres projets sur la page d'un projet ; sur un projet réel, 9 fils rouges au lieu de 23.

- Page projet (épinglée seule ou ouverte depuis le tableau) : plus de « Rangées aujourd'hui », de barre des Studios ni d'onglets Today et Conflits du tableau. Le compteur « N à faire d'abord » ne compte que les lignes du projet. Le tableau Mon Studio garde tout.
- « Fils rouges » : une ligne par session (point non lu, titre, dernière activité, « Ouvrir ↗ »), la plus récemment active en tête, dépliée par défaut, juste sous les questions. Plus de pastilles collées.
- Un fil rouge est une session de premier niveau (pas lancée par une autre session, ou remontée au premier niveau ensuite) où tu as écrit au moins 3 messages toi-même. La session d'ancrage du chantier, les piliers déclarés et ta liste `fils-rouges.json` restent ajoutés. Tes messages se comptent une fois par transcript, puis seulement sur ce qui s'ajoute.
- La page servie change ; elle vient du connecteur, sans republication.
- `/cockpit:point` : le coût de la semaine compte aussi les sessions archivées.
- README : les autorisations du point du matin sont six, avec les deux outils qui ferment les lignes Slack.

## 0.2.27 · 2026-11-17

Une ligne Slack n'a plus de bouton « Ouvrir ↗ » (décision du PM, Q11). Effet pour le PM : il ouvrait la session 📬 du Studio à son début et ne servait à rien ; restent « Slack ↗ » et « Fait / Retirer du tableau ».

- Une question qui écrit sa proposition (« Je propose : … ») se tranche depuis le tableau : le bouton « … (recommandé) » l'envoie à la session, et le détail montre la phrase envoyée.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.26 · 2026-11-17

Les sessions lancées par Claude prennent le bon modèle, et une session dit où parler. Effet pour le PM : moins de tokens dépensés en Opus par défaut et en relais entre sessions.

- Une session ou un sous-agent lancé sans modèle est refusé ; Claude relance avec le modèle du barème. Mesuré sur une semaine réelle : 47 lancements de session sur 73 partaient sans modèle. Se coupe par `"controle_modele": false` dans `cockpit.json`.
- Une action unique (un envoi, une vérification, un essai) se fait sur place ou en sous-agent, plus dans une session à part. Seule une tâche qui vit sa vie part dans une session, celle que l'app propose.
- Un message sur le sujet d'une autre session reçoit le lien de la bonne session, sans relais, sauf si le PM demande de transmettre.
- Un test plafonne ce que le plugin ajoute à chaque session (règles, descriptions des skills, ligne de rappel) : 9 400 octets de règles, dont la règle des questions à fort enjeu arrivée en 0.2.23.

Une ligne Slack tranchée par d'autres quitte aussi le tableau (décision du PM, Q9). Effet pour le PM : une décision prise dans le fil par les personnes concernées (« on part sur l'option B », « c'est en service ») ferme la ligne, même sans message de sa part, si plus rien ne lui est demandé.

- La vérification du point du matin ferme une ligne Slack quand le fil ou le canal montre la décision ou le geste pris après la demande, avec le lien de ce message pour preuve. Dans le doute, la ligne reste.


## 0.2.25 · 2026-11-17

Une tâche planifiée arrêtée en route se voit en tête du tableau, en mots simples. Effet pour le PM : un point du matin qui n'a pas écrit son fichier, ou un passage arrêté sur une autorisation, ne passe plus inaperçu parce que l'app le marque « réussi ».

- Le point du matin pas écrit à son heure fait une ligne en tête de « D'abord », qui dit pourquoi et ouvre le passage : « Point du matin pas passé aujourd'hui (dernier : 16/11) : arrêté à 8 h 26 sur une autorisation (recherche Slack), à relancer ». Sans arrêt lu : « son passage de 7 h 36 a fini sans écrire le point », ou « est encore en cours ».
- Tout passage d'une tâche planifiée arrêté (autorisation, erreur, tour coupé) passe en tête de « D'abord », avant les réponses courtes.
- Les noms d'outils sont traduits partout où le tableau les montre : « recherche Slack », « lecture d'un fil Slack », « lecture de l'agenda », « commande du terminal ». Un outil inconnu montre ses mots (« Boond : browser click »), jamais `mcp__…`. Le journal des autorisations garde le nom exact.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.24 · 2026-11-17

Les lignes Slack auxquelles tu as répondu dans le fil quittent le tableau d'elles-mêmes, et chaque ligne Slack tient en une phrase. Effet pour le PM : plus de question déjà tranchée qui reste des jours au tableau, et plus de message Slack à relire dans le tableau.

- La vérification du point du matin (11 h, 14 h, 17 h) lit le fil de chaque ligne Slack ouverte, puis cherche tes messages dans son canal, en lecture seule. Tu as répondu après la demande, dans le fil ou dans le canal : la ligne se ferme, avec ta réponse pour preuve, même si quelqu'un la conteste ensuite. Ta réponse annonce un geste de ta part (« je vais poser la question au client ») : ce geste devient une ligne, en une phrase. Sans réponse de ta part, la ligne reste. Elle passe même les jours sans point du matin.
- Le cockpit le fait lui-même, sans attendre le passage de l'ingestion : deux outils du connecteur, `slack_ouvertes` (lecture) et `slack_juger` (n'écrit que l'état des lignes du tableau), autorisés pour les tâches planifiées avec le go de l'installation.
- Chaque ligne Slack lue par la vérification prend un résumé court : ce qui est attendu de toi, et qui l'a écrit. Une ligne tirée de ton propre message le dit : « Tu t'es engagé le 12/11 à porter à Léo 5 questions client ».
- Le détail d'une ligne Slack ne recopie plus le message : qui l'a écrit, où, quand il a été relevé, et le lien « Ouvrir le message ↗ ». La page servie change ; elle vient du connecteur, sans republication.
- La tâche « Point du matin · vérification » est à reposer (nouvelle consigne) et ses deux nouvelles autorisations à ajouter : l'installation les propose, rien ne change sans ton go.

## 0.2.23 · 2026-11-17

Le tableau se trie par impact et par effort. Effet pour le PM : ce qui presse et se règle vite est en haut, avec sa raison ; le rangement est replié en bas.

- Trois bandes : « D'abord » (impact fort, toutes origines confondues, les réponses courtes en premier), « Ensuite » (le reste, dans l'ordre d'avant, les lignes hors Studio en dernier), « Peut attendre » (repliée sous le tableau). Aucune ligne n'est supprimée.
- Une ligne de « D'abord » dit pourquoi en quelques mots : « en retard », « sécurité », « bloqué », « Ana attend », « client attend ».
- Sans modèle. Celui qui écrit la ligne peut la qualifier dans son texte : « (impact fort : client attend) », « (impact faible) », « (effort court) », pour une demande de l'ingestion comme pour une question de session. « Fort » exige une raison de la liste (client attend, échéance, bloque l'équipe, argent ou contrat, sécurité). Sans étiquette, des règles simples : échéance proche ou dépassée, session qui attend ou arrêtée, « bloqué », « en clair », « sans délai », une personne qui demande ; « archiver cette session » est du rangement.
- Une demande en retard, ou qualifiée « fort » par sa source, ne part plus dans « Anciennes ».
- Le compteur du haut donne le nombre de lignes de « D'abord » (« 17 à faire d'abord », ou « Rien ne presse ») : un seul chiffre pour savoir par où commencer.
- La page servie change ; elle vient du connecteur, sans republication.

## 0.2.22 · 2026-11-17

L'onglet Conflits ne dit plus « à jour » sans relecture derrière. Effet pour le PM : il voit la date du dernier passage complet et ce qu'est devenue la relecture depuis, avec sa raison.

- « Studio à jour depuis le JJ/MM » devient « Dernier passage complet le JJ/MM », suivi de l'état réel : pas relu depuis, relecture du lundi sautée (ingestion automatique active), pas faite (trop de sujets pour un point du matin), en échec, ou relu sans rien de nouveau. « Studio à jour » ne s'écrit qu'après une relecture qui n'a rien trouvé ou dont tout est jugé.
- Le point du matin du lundi note ce qu'il a fait de chaque Studio déjà vérifié (`~/Mon Studio/.parc/conflits-semaine.json`). Avant ce premier lundi, l'onglet donne la raison qu'il peut lire : l'ingestion automatique active.
- Rien d'autre ne change : ni la relecture elle-même, ni ses seuils, ni le tableau. La page servie change ; elle vient du connecteur, sans republication.

## 0.2.21 · 2026-11-17

Le tableau se lit plus vite et chaque bouton dit ce qu'il fait ; une ligne se retire à la main. Effet pour le PM : moins de texte par ligne, plus de clic qui part dans le mauvais sens, et plus de ligne qu'il ne peut pas faire partir.

- Le texte des lignes est nettoyé : plus de « une autre Qn vient de… » ni de « à traiter dans la session… », le numéro de la question une seule fois. Une demande de l'ingestion montre dans la colonne Session qui la fait et le canal (« Ana · #projet-client ») au lieu de « Message Slack ».
- Le bouton qui ouvre une session s'appelle « Ouvrir ↗ » partout. « Recommandé » dit son choix : « Automatique (recommandé) ».
- « En un clic » ne garde que ce qu'un clic règle, rien de plus de 48 h. Un geste à faire ailleurs a « C'est fait » (et « Y aller ↗ » quand son lien est connu), au tableau.
- « Fait / Retirer du tableau » sur toutes les lignes, questions des sessions comprises, avec 10 secondes pour annuler. La session concernée en est avertie à son tour suivant ; si elle repose la question plus tard, la ligne revient.
- Une question à laquelle tu as répondu en tapant dans la session part du tableau : l'app met ses propres notes devant tes messages, et Mon Studio ne les reconnaissait plus comme les tiens.
- Retirés : les fils rouges du tableau principal (repliés sur la page projet, à la place de « Sujets »), l'onglet Conflits quand il est vide, les boutons d'une question dont on peut garder plusieurs options (ils n'envoyaient qu'une option). Le compteur devient « N à trancher aujourd'hui » ; dans Today, « Pour info » a « Vu » au lieu de « Fait ».
- Mise à jour sans republier les pages ; le premier calcul relit tous les transcripts (quelques secondes).

## 0.2.20 · 2026-11-17

- Les sessions finies qui n'ont servi qu'à une action sont archivées sans toi : lancées par une autre session (ou marquées « [jetable] »), ton dernier message déjà traité, rien à trancher, 24 h sans activité. Une session que tu as ouverte toi-même ne l'est jamais.
- Le calcul se fait sans modèle ; l'archivage lui-même se fait dans ta prochaine session où tu écris, car l'app refuse d'archiver depuis une tâche planifiée. La page montre « Rangées aujourd'hui ».
- « Coupe le rangement » dans `/cockpit:mon-studio` l'arrête ; désactiver Mon Studio aussi.

## 0.2.19 · 2026-11-16

- Les pages Mon Studio (la page principale et les pages projet) chargent leur code depuis le connecteur à chaque ouverture : une mise à jour du plugin ne demande plus de les republier, et ne coûte plus de tokens pour elles.
- Une republication n'arrive plus que si la coquille de la page ou ses outils changent, ce qui est rare ; elle relit une page d'environ 4 Ko.
- Si le connecteur ne répond pas, la page le dit en une phrase et dit quoi faire.
- Cette version demande, une seule fois : quitter et rouvrir l'app, puis republier chaque page avec sa nouvelle coquille et l'outil `gabarit`.

## 0.2.18 · 2026-11-16

- Une session ouverte pour une seule action s'archive dès que son résultat est rendu, sans attendre l'accord du PM : la barre latérale ne garde plus les petites sessions finies.
- Une session de dialogue (fil rouge, sujet qui dure) ne s'archive toujours qu'avec l'accord du PM.
- Cette règle change pour toutes les sessions dès la mise à jour, sans go.

## 0.2.17 · 2026-11-16

- Une question du tableau se déplie sur elle-même : l'énoncé entier, les options, celle que la session recommande et les fichiers cités, qui se lisent dans la page. Plus besoin d'ouvrir la session pour décider ; « Ouvrir ↗ » dit qu'elle s'ouvre à son début.
- Une demande de l'ingestion a un titre court qui se lit en entier ; elle ne se déplie que si le détail apporte quelque chose (texte complet, commande à taper, fichier lié, lu dans la page), et sa colonne Session dit d'où elle vient sans rien ouvrir.
- Chaque demande ne s'affiche qu'une fois (plus de doublon dans le bloc Projets ni dans Today, dont la pastille ne compte plus deux fois), se ferme quand le point du matin la dit réglée au même lien, et au-delà de trois Studios les relevés de conflits tiennent en une ligne de « Mise en route ».

## 0.2.16 · 2026-11-16

- La page parle en mots simples : plus de termes techniques dans les messages d'erreur et les boutons.
- L'infobulle d'un bouton de réponse dit quand la session reçoit la réponse, et quand elle est copiée à la place.
- Le README dit ce qui est écrit dans `~/.claude/settings.json`, comment connecter le Claude du Terminal, et les limites connues.

## 0.2.15 · 2026-11-16

- `/cockpit:mon-studio` ne pose plus que le socle (dossier, connecteur, pages, règles) : une installation, un go, un redémarrage.
- Le point du matin, le premier relevé des conflits et la connexion du Terminal deviennent un bloc « Mise en route » en tête du tableau : une ligne par étape, son coût, son bouton, jusqu'à « fait » ou « Pas pour moi ».

## 0.2.14 · 2026-11-15

- Plus de tâche planifiée pour les conflits : le lundi, le point du matin relit ce qui est nouveau dans chaque Studio dont tu es PM.
- Chaque question « À trancher » arrive avec une proposition, même pour une date ou un chiffre à confirmer.

## 0.2.13 · 2026-11-15

- Une réponse donnée au tableau part tout de suite si le tour de la session est fini, sinon dès la fin du tour. La ligne dit « Envoyée » seulement quand la session a la réponse.

## 0.2.12 · 2026-11-15

- Mon Studio te reconnaît PM sur plus de fiches projet (remplacement noté, « (PM) » dans la ligne « Responsable »).

## 0.2.11 · 2026-11-15

- L'onglet « Conflits » tient le journal de ce qui a été tranché, avec la date du dernier passage complet ; un onglet vide dit pourquoi.
- `/cockpit:conflits` reprend les décisions déjà tranchées à la main, après ton go.
- Une ligne par Studio jamais vérifié dans « Ce qui t'attend », avec questions, temps et coût estimés.

## 0.2.10 · 2026-11-15

- Tes pages Mon Studio ne sont plus republiées quand une version ne change que des commentaires ou des espaces.

## 0.2.9 · 2026-11-14

- Vue projet plus rapide à lire : une pastille compte les lignes apparues depuis ta dernière visite, les plus urgentes anciennes remontent, « Sujets » et « Journal » sont repliés.

## 0.2.8 · 2026-11-12

- Quand tu tranches un conflit en « remplaçant » une valeur, `/cockpit:conflits` prépare en brouillon la correction des tickets Jira ou Linear qui la portent encore (description seulement, jamais de commentaire).
- Tous les brouillons se valident dans un seul formulaire ; rien ne part sans ton go ni hors des heures ouvrées.

## 0.2.7 · 2026-11-10

- Les conflits sont mieux trouvés et il y a moins de faux conflits : les archives ne sont plus relues, l'état du projet (questions, décisions, phase) est vérifié.
- Le rattrapage d'un Studio coûte deux fois moins.

## 0.2.6 · 2026-11-10

- Les conflits se traitent en trois niveaux : marquages sûrs en un go, cas évidents pré-répondus validés dans un formulaire, vraies décisions posées une par une.
- Un onglet « Conflits » dans la vue globale relance les Studios qui ont des conflits en attente.

## 0.2.5 · 2026-11-10

- Une session citée porte toujours un lien cliquable vers elle.
- Un bouton « Recommandé » apparaît sur les questions qui recommandent une réponse.
- Le point du matin ne vérifie que les brouillons à vérifier.

## 0.2.4 · 2026-11-10

- Nouveau `/cockpit:conflits` : il remet un Studio d'équerre quand une source plus récente change une règle ou une décision qu'un document présente encore comme valable.
- Une décision par encadré, en mots simples, sans aucun code ; rien n'est supprimé, seul un marquage est ajouté à côté de l'ancien texte.
- Le coût est dit avant chaque go.

## 0.2.3 · 2026-11-10

- Les tâches planifiées arrêtées sur une autorisation, une erreur ou une question apparaissent au tableau.
- Tes réglages Claude ne changent qu'avec ton go.
- « c fait » ferme la bonne question.

## 0.2.2 · 2026-11-09

- Les tâches du matin ne restent plus bloquées sur une autorisation ; un point du matin qui n'est pas passé se voit sur la page.
- Le coût est dit avant le go ; rien ne se pose sans l'accord du PM.
- Un registre de questions par Studio, sans rien installer ; deux « Q12 » ne se confondent plus.
- Mon Studio s'installe sur Mac seulement ; « Désactive Mon Studio » coupe tout.

## 0.2.1 · 2026-11-07

- Today : un bouton « Fait » sur chaque élément qui demande un geste.
- Un bouton de réponse répond à la session, même endormie (Claude doit être connecté dans le Terminal).
- Les brouillons Gmail ou Slack jamais envoyés apparaissent en bas de Today.

## 0.2.0 · 2026-11-06

- Une page « Mon Studio » épinglée dans l'app : ce que chaque session attend de toi, projet par projet, avec le bouton qui ouvre la bonne session.
- Une page par projet suivi, et un onglet Today rempli chaque jour ouvré à 7h30 (mails, Slack, agenda).
- `/cockpit:point` : le point sur les sessions d'un Studio en dix lignes.
- Des règles de travail dans toutes tes sessions, sans toucher à ton `CLAUDE.md`.

## 0.1.0 · 2026-10-29

- Premier plugin `cockpit` : Mon Studio, `/cockpit:point` et les règles de travail du PM, dans `~/Mon Studio`.
