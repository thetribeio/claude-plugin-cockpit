# cockpit

Le cockpit du PM qui mène plusieurs projets et plusieurs sessions Claude en même temps.

- **Avant** : tu passes de session en session pour retrouver qui t'a posé une question, et le matin tu refais le tour des mails, de Slack et de l'agenda, projet par projet.
- **Après** : une page épinglée dans l'app Claude te dit ce que chaque session attend de toi, projet par projet, avec le bouton qui ouvre la bonne session. Le matin, l'onglet Today a déjà fait le tour.
- **Ce qui ne change pas** : tes gestes. Le cockpit lit ce que tu produis déjà (tes sessions, ton Studio, tes mails) et n'écrit rien chez les autres.

## Ce qu'il installe sur ton poste

Installer le plugin n'active rien. Tout reste muet tant que tu n'as pas lancé `/cockpit:mon-studio`. Seuls `/cockpit:point` et `/cockpit:conflits` marchent sans lui.

`/cockpit:mon-studio` te dit ce qu'il va poser et attend un seul go. Il ne pose que le socle :

- **le dossier `~/Mon Studio`** sur ton ordinateur : les fichiers du calcul et les journaux. Il mélange tous tes projets : il ne va jamais sur le Drive ;
- **le connecteur `mon-studio`** (un petit programme local que la page interroge), déclaré dans la configuration de l'app Claude. Il tourne sans Claude, donc sans token (unité de consommation de Claude). Il sert aussi le code des pages, qui le chargent à chaque ouverture : une mise à jour du plugin n'oblige pas à les republier. Ses outils `decider`, `repondre` et `clore` sont faits pour la page : une session reçoit la consigne de ne pas les appeler, sans que le connecteur puisse l'en empêcher ;
- **la page « Mon Studio »**, privée et épinglée dans la barre latérale, et une page épinglée par projet suivi. Tu désépingles celles que tu ne suis plus ;
- **des règles de travail dans toutes tes sessions**, données au démarrage : format des réponses, livrables, modèle et effort, sessions, passation. Plus une ligne de rappel à chaque message : finir par les questions numérotées, ou par « Rien à faire de ton côté ». La règle des heures de publication est en option : demande-la à `/cockpit:mon-studio`.
- **le rangement des sessions finies**, allumé par défaut : une session lancée pour une seule action, finie et inactive depuis 24 h, apparaît sous le tableau avec un bouton « Ranger » ; rien n'est archivé sans ton message (voir « Le rangement des sessions finies » ; « coupe le rangement » l'arrête) ;
- **le contrôle du modèle au lancement** : un lancement de session ou de sous-agent sans modèle choisi est refusé, avec le barème, jusqu'à ce que Claude le relance avec un modèle. Pour le couper, dis « coupe le contrôle du modèle » dans `/cockpit:mon-studio`. Il ne joue que dans les sessions de l'app de bureau, jamais dans le Terminal.
- **le contrôle du format des questions** : à la fin d'un tour, un bloc « À trancher » mal formé renvoie une fois la session le reposter. Pour le couper, dis « coupe le contrôle du format » dans `/cockpit:mon-studio`. Il ne joue que dans les sessions de l'app de bureau, jamais dans le Terminal.
- **le réglage d'ouverture** : au premier message d'une session, Claude règle lui-même son modèle et son effort selon le barème, et l'annonce en une ligne ; pour Fable ou Opus high, il le propose et attend ton oui. Pour le couper : « coupe le réglage d'ouverture » dans `/cockpit:mon-studio`.
- **le contrôle du barème** : un sous-agent en Opus ou Fable sans raison donnée (« [modèle justifié] » dans son brief) est refusé, comme une session lancée sans modèle ou en Fable sans ta demande (« [fable demandé] »). Pour le couper : « coupe le contrôle du barème ». Si tu as déjà ta propre copie de l'un de ces deux hooks dans `~/.claude/hooks/` (`reglage_ouverture.py`, `bareme_modele.py`), celui du plugin se tait : tu peux retirer ta copie quand tu veux.
- **deux contrôles dans tes sessions** : au-delà de 300 000 tokens de contexte, la consigne de proposer une session neuve ; chaque brouillon Gmail ou Slack qu'une session pose est noté dans `~/Mon Studio`, pour que le point du matin vérifie qu'il est parti. À l'installation, les transcripts de tes 30 derniers jours sont relus, sur ton Mac, pour noter les brouillons déjà posés.

Le reste attend dans le bloc « Mise en route », en tête du tableau dès le premier jour : une ligne par étape, avec son coût et son bouton, jusqu'à ce que tu la fasses ou cliques « Pas pour moi ». Le bouton copie une commande à coller dans une nouvelle session, qui te dit ce qu'elle pose et attend ton go :

- **le point du matin** : deux tâches planifiées, « Point du matin » (du lundi au vendredi à 7h30, lit mails, Slack et agenda pour l'onglet Today ; le lundi, tente de relire les conflits nouveaux de tes Studios, ce qu'elle saute aujourd'hui sur les Studios mesurés, voir « Limites connues ») et « Point du matin · vérification » (11h, 14h et 17h, range ce qui a eu sa réponse). Après ton go, six autorisations s'ajoutent à `~/.claude/settings.json`, pour que les tâches lancent leurs scripts sans attendre un clic (une copie datée du fichier est faite avant, rien d'autre n'y change). Les tâches planifiées ne tournent que si l'app Claude est ouverte sur ton Mac à leur heure ;
- **le premier relevé des conflits** de chaque Studio dont tu es PM, une fois ;
- **la connexion du Claude du Terminal** : dans le Terminal, `claude`, puis `/login`, la connexion dans le navigateur, puis `/exit`. Il faut la commande `claude` de l'installateur officiel, dans `~/.local/bin` : installée ailleurs, le cockpit ne la voit pas. Avec elle, un bouton de réponse fait reprendre la session sans que tu l'ouvres : le connecteur la relance en arrière-plan (`claude --resume`). Pour savoir si l'app la garde encore au repos, il lit la liste des processus de ton Mac, avec leurs variables d'environnement, et le journal de l'app. Si c'est le cas et que son tour est fini, il arrête ce processus de l'app, comme l'app le fait elle-même quand la mémoire manque, puis relance la session avec ta réponse. Jamais pendant un tour : si la session est en cours de tour, la réponse est mise en file et part quand il est fini. Sans cette connexion, rien de tout cela n'est fait et la réponse est copiée pour que tu la colles.

Il te faut un Mac, l'app Claude de bureau (le terminal seul ne suffit pas) et python3. Sur un Mac neuf, macOS propose d'installer les « outils de développement d'Apple » : accepte.

Le cockpit te reconnaît à ton nom, qui doit être celui de la ligne « PM » de la fiche projet de tes Studios : il le prend dans ton réglage, sinon dans git (`git config --global user.name`), sinon dans le nom de ton compte Mac. S'il se trompe, tes demandes « À toi de jouer » n'arrivent pas au tableau ; dis « mon nom est Prénom Nom » dans `/cockpit:mon-studio` pour le corriger.

Mon Studio s'installe sur Mac seulement : sous Windows ou Linux, `/cockpit:mon-studio` le dit et ne pose rien.

Les pages projet se remplissent à partir de ton Studio au format du plugin `studio` et de l'ingestion automatique (plugin `product-kits`). Sans eux, elles restent presque vides.

## Quand lancer quoi

| Situation | Commande |
|---|---|
| Première fois, ou nouveau Mac | `/cockpit:mon-studio` |
| Une ligne manque ou est fausse, la page est vide | `/cockpit:mon-studio` (il vérifie et répare) |
| Suivre un projet de plus dans sa propre page | `/cockpit:mon-studio`, puis « épingle-moi le projet X » |
| Savoir ce qui t'attend dans les sessions d'un Studio | `/cockpit:point`, ou « fais le point » |
| Le coût de tes sessions de la semaine | `/cockpit:point`, ou « combien ont coûté mes sessions cette semaine » |
| Plusieurs sujets avancent en même temps sur un Studio | La vue projet de Mon Studio (bouton « Vue projet ») |
| Un document du Studio présente encore une règle qu'une source plus récente a changée | `/cockpit:conflits`, dans la session « <Projet> · Conflits Studio » du Studio |
| Voir les conflits ouverts d'un projet | L'onglet « Conflits » de sa vue projet, ou `/cockpit:conflits` |
| Arrêter Mon Studio | `/cockpit:mon-studio`, puis « désactive Mon Studio » |

Au quotidien, aucune commande : la page épinglée se relit seule, toutes les 15 secondes environ, tant qu'elle est ouverte.

## Le premier geste

0. Installer le plugin. Tant qu'il n'est pas au catalogue thetribe, il s'installe depuis ce dépôt (il te faut l'accès au dépôt sur GitHub) : dans une session, `/plugin marketplace add thetribeio/claude-plugin-cockpit` (si l'ajout échoue sur une erreur d'authentification : dans le Terminal, `gh auth login`, puis recommence), puis `/plugin install cockpit@thetribe-cockpit`. Pour une nouvelle version : `/plugin marketplace update thetribe-cockpit`, puis `/plugin update cockpit@thetribe-cockpit`. Une fois au catalogue : depuis le catalogue de plugins de l'app, ou `/plugin install cockpit@thetribe` (après `/plugin marketplace add thetribeio/claude-marketplace-thetribe`).
1. Dans une session de l'app : `/cockpit:mon-studio`. Lis ce qu'il va poser, réponds « go ».
2. Quitte l'app (Cmd+Q) et rouvre-la : elle ne lance le connecteur qu'au démarrage.

La page « Mon Studio » est dans la barre latérale. Le bloc « Mise en route », en tête, dit ce qui reste à faire si tu le veux. Pour le point du matin, la session te demande aussi un geste par tâche dans « Planifiées » : le crayon (« Modifier »), menu « Par défaut » en bas à droite des instructions, Sonnet pour « Point du matin », Haiku pour sa vérification (Sonnet reste possible, mais bien plus cher : voir « Ce que ça coûte »), puis « Exécuter maintenant » et « Toujours autoriser » à chaque demande de ton agenda, de Gmail et de Slack (une demande sur `matin.py` ou sur un fichier de `~/Mon Studio` veut dire que les autorisations manquent : relance `/cockpit:mon-studio` plutôt que de l'accepter). Sans ce geste, les exécutions du matin attendent une réponse que personne ne donne et n'écrivent rien. L'effort reste celui de l'app : une tâche planifiée ne le choisit pas.

## Ce que ça coûte

En bref, avant le détail :

- **À l'installation** : presque rien. La page et le connecteur sont des scripts locaux, sans Claude ; `/cockpit:mon-studio` charge environ 11 000 tokens, et chaque page publiée quelques milliers.
- **Le premier relevé des conflits, une fois par Studio** : le seul gros poste. Environ 7 $ pour un Studio d'une centaine de sujets, décisions comprises (mesuré : 5,2 $ pour le relevé seul d'un Studio de 97 sujets). Chaque Studio affiche son estimation avant ton go.
- **Chaque jour ouvré, la part fixe** : environ 0,9 $ pour les deux tâches du matin (0,45 $ pour « Point du matin », estimation à remesurer, et 0,44 dollars pour sa vérification sur Haiku, mesurée le 2026-11-18), si tu les mets en route. La vérification coûte selon le nombre de lignes Slack ouvertes.
- **La vérification sur Sonnet, si tu la choisis** : environ 2,4 à 2,7 dollars par passage, 7,7 dollars par jour pour trois passages, soit 2,7 % de ta semaine chaque semaine, au-dessus à elle seule du seuil de 2 % du mainteneur (estimation, non mesurée : aucun passage réel sur Sonnet).
- **Chaque jour ouvré, la part qui suit ton usage** : les règles à chaque session ouverte, la ligne de rappel à chaque message, le registre à chaque question. Chez l'auteur, qui ouvre 8 sessions et écrit 87 messages par jour, cela fait environ 1 $ de plus : 1,92 $ en tout.
- Ces montants sont au prix catalogue de l'API : ils disent ce que le plugin consomme de ton abonnement, ce ne sont pas des factures. Les pourcentages de la semaine valent pour la place de l'auteur ; sur une offre plus petite, les mêmes dollars pèsent plus.

Environ 0,7 % de ta semaine Claude, 1,92 $ par jour ouvré, dont 0,94 $ pour le point du matin, si tu le mets en route. Mesuré le 2026-11-09 sur la place de l'auteur, du 26/10 au 09/11, chiffres revus le 2026-11-15 (règles, registre des questions, passe des conflits du lundi) ; « Point du matin » reste une estimation à remesurer, sa vérification est mesurée le 2026-11-18 (deux passages réels sur Haiku) ; les sessions de l'auteur sont longues (87 messages et 8 sessions par jour), donc les règles, la ligne de rappel et le registre des questions te coûteront moins. Barème : prix catalogue de l'API par million de tokens, entrée / sortie / relu en cache, Opus 4 / 20 / 0,20 dollars, Sonnet 2 / 10 / 0,10 dollars, Haiku 0,10 / 0,50 / 0,01 dollars ; un token écrit en cache coûte le prix d'entrée x 1,25 ; 1 % de la semaine = 14,5 dollars, semaine de 5 jours. La place de l'auteur est une place Team au budget relevé, que tout PM peut demander : à ce niveau, 1 % de la semaine vaut 14,5 dollars ; sur une offre plus petite, les mêmes dollars pèsent plus.

Les tokens d'un poste sont comptés en trois parts : écrits (une fois), en sortie, et relus en cache à chaque appel suivant de la session. Un texte ajouté à une session coûte surtout par ces relectures. Les textes ajoutés aux sessions sont comptés au prix d'Opus, les tâches du matin au prix du modèle choisi pour elles.

| Poste | Base | Tokens écrits par jour | En sortie | Relus en cache | $ par jour | % de la semaine par jour | % par semaine |
|---|---|---|---|---|---|---|---|
| La page Mon Studio et le connecteur | scripts locaux, sans Claude | 0 | 0 | 0 | 0 | 0 | 0 |
| Les règles, au démarrage de chaque session | 2 400 tokens x 8,4 sessions (moins si ton `CLAUDE.md` les importe déjà) | 20 200 | 0 | 2,65 M | 0,63 | 0,044 | 0,22 |
| La ligne de rappel, à chaque message | 60 tokens x 87 messages | 5 200 | 0 | 455 000 | 0,12 | 0,008 | 0,04 |
| « Point du matin » (Sonnet, effort par défaut de l'app (élevé)) | estimation, à remesurer : 1 exécution de 7 à 13 appels | 100 000 | 9 000 | 1,1 M | 0,45 | 0,031 | 0,16 |
| « Point du matin · vérification » (Haiku, effort par défaut de l'app (élevé)) | mesuré le 2026-11-18, deux passages réels : 34 à 37 appels et 3,5 à 4 M tokens relus par passage pour 16 à 18 lignes Slack ouvertes ; le coût suit le nombre de lignes Slack ouvertes ; 3 passages au plus par jour | 1 140 000 | 375 000 | 11,2 M | 0,44 | 0,030 | 0,15 |
| La passe des conflits du lundi, dans « Point du matin » (Sonnet) | estimation pour une petite semaine, 20 sujets nouveaux dans les Studios dont tu es PM sans ingestion automatique ; au-delà de 90 000 caractères d'extraits, la passe est sautée et ne coûte rien : c'est le cas aujourd'hui sur les Studios mesurés (350 sujets et plus par semaine) ; un jour sur cinq | 6 000 | 2 400 | 48 000 | 0,04 | 0,003 | 0,02 |
| `/cockpit:point` | chargement du skill 1 600 tokens, sortie du script 250 à 1 250, réponse 500 ; une fois par jour | 2 850 | 500 | 285 000 | 0,04 | 0,003 | 0,01 |
| Registre des questions, au démarrage | 700 tokens x 4,8 sessions d'un Studio | 3 400 | 0 | 240 000 | 0,07 | 0,004 | 0,02 |
| Registre des questions, par question | 1 100 tokens x 13 questions (numéro pris, puis soldé) | 14 300 | 0 | 320 000 | 0,14 | 0,009 | 0,05 |
| **Total** | | **1 292 000** | **386 900** | **16,3 M** | **1,92** | **0,13** | **0,7** |

- Les seuils du mainteneur : un lancement à 0,5 % de la semaine au plus (le plus cher chaque jour, une exécution du point du matin : 0,03 % ; une fois par Studio, le premier relevé des conflits, étape de mise en route : mesuré 0,36 % pour 97 sujets, environ 0,5 % avec les décisions, chaque Studio a son estimation sur sa ligne) ; l'usage normal à 2 % par semaine au plus (0,7 %). Au plus haut, si chaque question coûte à sa session un aller-retour de plus (son contexte de 335 000 tokens relu deux fois), le registre monte à 1,88 $ par jour et le total à 1,3 % par semaine.
- Le modèle des tâches du matin compte le plus : la vérification coûte environ 17 fois plus sur Sonnet que sur Haiku, pour les mêmes volumes (2,4 à 2,7 dollars par passage, 7,7 dollars par jour pour trois passages, 2,7 % de la semaine par semaine, au-dessus à elle seule du seuil de 2 % : estimation, non mesurée). Sans modèle choisi, les tâches tournent sur le modèle par défaut de l'app, bien plus cher : non mesuré. Elles tournent à l'effort par défaut de l'app, élevé. Le chiffre de « Point du matin » est une estimation, à remesurer après la première exécution réelle qui n'attend pas d'autorisation ; celui de la vérification est mesuré, mais il suit le nombre de lignes Slack ouvertes.
- Non mesurés, hors du total : le chargement d'un skill du cockpit, à chaque appel (environ 11 000 tokens pour `/cockpit:mon-studio`, autant pour `/cockpit:conflits`, relus à chaque appel suivant de la session) ; la reprise d'une session par un bouton de réponse (un tour de la session, `claude --resume -p`, avec la relecture de son contexte : le même tour que si tu répondais dans la session) ; la lecture des brouillons par « Point du matin » (un appel Gmail par brouillon noté, 10 au plus) ; la vérification de la connexion du Claude du Terminal (un `claude -p` court sur Haiku après l'installation, gardé 6 h) ; la publication des pages, à l'installation puis seulement quand une version du plugin change leur coquille ou leurs outils, ce qui est rare : le code de la page vient du connecteur à chaque ouverture, une mise à jour ordinaire ne republie rien. La session qui publie relit chaque page, environ 63 000 tokens par page sur Sonnet, soit environ 0,04 % de la semaine pour la page Mon Studio et trois pages projet.
- `install.py plan` te montre ces mêmes lignes avant ton go.

Deux options restent coupées tant que tu ne les demandes pas à `/cockpit:mon-studio` : répondre aux autorisations depuis la page, et garder une session quelques minutes en attente de ta réponse après sa question. Sans elles, les boutons de réponse aux questions marchent quand même : la session reçoit la réponse tout de suite, ou dès qu'elle a fini son tour (24 h au plus) ; si elle dort et que le Claude du Terminal n'est pas connecté, la réponse est copiée pour que tu la colles.

## Ce qu'il n'écrit jamais

- `/cockpit:point` n'écrit rien dans tes Studios ni sur le Drive. Mon Studio non plus, sauf la relecture des conflits du lundi quand elle tourne : elle inscrit ses décisions au registre `projet/conflits.md` du Studio et y laisse son plan, dans `projet/.conflits/`. `/cockpit:conflits` y écrit après ton go, et seulement des ajouts (voir plus bas).
- Rien dans ton `~/.claude/CLAUDE.md`. Dans `~/.claude/settings.json`, seulement les six autorisations du point du matin, si tu le mets en route ; « désactive Mon Studio » les retire.
- Aucun message ni mail envoyé. Une réponse donnée depuis la page va à tes sessions, à personne d'autre. Un ticket ne change que par `/cockpit:conflits`, sur ton go et en heures ouvrées : sa description seulement, jamais un commentaire (voir plus bas).

## Le rangement des sessions finies

- Une session que Claude a lancée pour une seule action (un envoi, une vérification, un essai) est proposée au rangement quand elle a fini : elle a été lancée par une autre session ou son brief commence par « [jetable] », tu n'y as jamais écrit (ou, pour une session lancée par une autre, Claude a répondu à ton dernier message), son dernier message ne demande rien et ne dit pas qu'il reste du travail, elle n'a pas de ligne au tableau, rien n'a bougé depuis 24 h, son dossier de travail n'a rien de non enregistré et aucune session qu'elle a lancée n'est en route. Au moindre doute, elle reste.
- Jamais archivées : une session que tu as ouverte toi-même (même marquée « [jetable] » dès que tu y as écrit), une session dont ton dernier message attend encore Claude, une session épinglée, remontée au premier niveau ou dont le titre commence par « 📬 ».
- Le calcul se fait sans modèle, en arrière-plan, une heure au plus souvent. La page montre « N sessions finies à ranger » sous le tableau, avec leurs titres et un bouton « Ranger ».
- « Ranger » copie la demande d'archivage de ces sessions ; colle-la dans une nouvelle session (Cmd+N) : c'est ton message qui vaut accord, et Claude les archive. L'app refuse d'archiver sur un ordre venu d'un hook ou d'une tâche planifiée : depuis la 0.3.10, plus aucune liste n'est confiée à une autre de tes sessions.
- « Abandonner », sur la ligne d'une session arrêtée depuis plus de 48 h, la retire du tableau et la met dans la même liste à ranger.
- La page montre ensuite « Rangées aujourd'hui » ; chaque session se rouvre depuis la liste Archivées de l'app.
- Pour le couper : `/cockpit:mon-studio`, puis « coupe le rangement » (« rallume le rangement » le remet). Le délai se règle : « range après 48 h ». Désactiver Mon Studio l'arrête aussi.
- Pour voir ce qu'il ferait, sans rien changer : `python3 "<dossier du plugin>/hooks/rangement.py" lister`.

## Le retirer

- **Désactiver** : `/cockpit:mon-studio`, puis « désactive Mon Studio », un go. Il retire le connecteur de l'app, supprime les deux tâches du matin, coupe les règles et la ligne de rappel dans tes sessions, et désépingle les pages sans les supprimer. Puis Cmd+Q et rouvre l'app. Relancer `/cockpit:mon-studio` le remet.
- **Tout retirer** : désactive, puis désinstalle le plugin dans l'app, puis supprime toi-même le dossier `~/Mon Studio`, les copies `~/.claude/settings.json.avant-mon-studio-…` et, si tu en as ajouté, `~/.claude/cockpit/marqueurs.md`. Les pages restent dans tes artifacts, désépinglées : supprime-les depuis l'app si tu n'en veux plus. Ce que `/cockpit:conflits` a écrit dans tes Studios y reste.

## Ses voisins

Le cockpit marche seul. Un voisin présent l'enrichit, un voisin absent ne casse rien.

- **`productivity`** (`daily-meetings`) range les réunions du jour dans le Studio ; le cockpit en montre le résultat.
- **L'ingestion automatique** (`product-kits:ingestion-auto`) range mails, réunions et Slack dans le Studio ; le cockpit lit ce qu'elle a rangé et ses « À toi de jouer ».
- **`/studio:brief`** prépare, sur demande, le briefing d'un Studio pour une audience donnée ; `/cockpit:point` dit seulement ce qui t'attend dans les sessions.
- **`/morning`** (skill d'Anthropic) fait un brief du matin général ; l'onglet Today fait le point du matin projet par projet, avec ce que les sessions attendent de toi. Garde l'un ou l'autre pour le matin.

## Le point et la vue projet

- `/cockpit:point` dans une session du Studio : ce qui t'attend, avec le nom exact de la session où répondre. Dès que deux sujets avancent dans la semaine, il renvoie à la vue projet.
- La vue projet de Mon Studio (bouton « Vue projet ») suit un projet : ses questions, ses fils rouges (les sessions où tu reviens discuter, dépliés), ses attentes de tiers et son journal (replié, ouvert d'un clic). Une pastille sur l'onglet « Projet » compte les lignes apparues depuis ta dernière visite. Une question au PM y arrive en un seul appel de la session qui la pose. Tu réponds dans la session qui pose la question.
- Dans tout Studio que Mon Studio connaît, chaque question qu'une session te pose porte un numéro (« Q3 · … »), le même dans la session, sur Mon Studio et dans la vue projet, et tes réponses depuis la page reviennent à cette session.
- Une question tient sur une ligne : son titre court, qui dit quoi décider (« Q3 · Envoyer le mail demain matin ? »). Un clic montre la question précise, ses options entières et pourquoi ; un bouton par option, avec ses mots, la recommandée en premier. Une session dont les questions ne suivent pas ce format reçoit une fois la consigne de les reposter.
- Les numéros sont propres à chaque Studio ; rien à installer : le registre du Studio se crée à sa première question.
- La vue projet demande Mon Studio, donc un Mac.

## Les conflits du Studio : `/cockpit:conflits`

Mon Studio a lu le mail ou la réunion qui changeait une règle, mais un document du Studio présente encore l'ancienne comme valable. `/cockpit:conflits` remet le Studio d'équerre, dans une seule session ouverte dans le dossier du Studio, titrée « <Projet> · Conflits Studio » (lancé d'ailleurs, il propose de l'ouvrir) :

- **rattrapage** d'un Studio, une fois : un aperçu en tableau (marquages sûrs, décisions pour toi, ajouts, fichiers touchés, parti chez le client ou non, coût), sans rien écrire ; puis un seul go pour tous les marquages sûrs ;
- **tes décisions**, une par encadré, chaque conflit dit par son titre et en mots simples (qui a dit quoi, et quand), sans aucun numéro ni code, la réponse recommandée en premier, « Discuter d'abord » en dernier ; tu peux aussi répondre à la voix, par le titre du conflit (« le comité de pilotage, remplacer », « rouvre le comité de pilotage ») ;
- **les cas ouverts**, gardés dans `projet/conflits.md`, le registre, écrit par `/cockpit:conflits` et par la relecture du lundi quand elle tourne (aucune version publiée de l'ingestion automatique n'y inscrit rien) ; l'onglet « Conflits » de la vue projet les montre, avec le bouton de la session ;
- **la relecture** : seulement ce qui a changé depuis le dernier passage. Le lundi, le point du matin la tente pour chaque Studio dont tu es PM, déjà vérifié et sans ingestion automatique, tant que ses sujets nouveaux tiennent en 90 000 caractères d'extraits pour tous les Studios ; au-delà, elle est sautée, et l'onglet « Conflits » le dit. Quand elle tourne, il inscrit les décisions au registre, sans question, et prépare les marquages sûrs pour ton go ; aucune tâche planifiée par Studio. Ailleurs, à ta demande ;
- **l'aperçu préparé**, à la demande : le bouton « Préparer l'aperçu » de l'onglet « Conflits » lance le relevé et le jugement d'un premier rattrapage, sur go du coût, et tu valides plus tard ;
- **les tickets touchés** par un conflit tranché « remplacer » (Jira ou Linear, selon la fiche projet) : leur correction en brouillon, la description seulement, jamais un commentaire. Tu les vois groupés dans la session, chaque ticket par son titre, avant et après, puis tu valides d'un seul formulaire ; en texte libre, tu peux en écarter un ou changer son texte. Par défaut, la correction est un ajout daté en tête et le texte d'origine reste ; seul un ticket dans un statut interne listé sur la fiche (« Statuts internes : À rédiger, Brouillon ») peut être réécrit. Un ticket terminé n'est jamais corrigé, seulement nommé.

Ce qu'il écrit, et seulement après ton go : une ligne de marquage à côté de l'ancien texte (« ⚠️ Remplacé le … par …, source … — rattrapage du … »), jamais deux fois, sans changer un octet ni rien supprimer ; l'ancienne règle dans « Règles remplacées » quand tu choisis de remplacer ; une ligne au registre et au journal du Studio. Un document parti chez le client (tout `0-commerce/`, devis, offre, cahier des charges) est seulement marqué. Rien n'est envoyé à personne, rien dans Figma ni la story map.

Dans le ticketing, seulement la description des tickets touchés, après ton go explicite, et seulement en heures ouvrées (lundi à vendredi, 8 h à 20 h, heure de Paris, jours fériés exclus, lue avec `date`) ; hors de ces heures, ton go vaut préparation et le push t'est reproposé au passage suivant. Juste avant chaque push, le ticket est relu : s'il a changé depuis le brouillon, il ne part pas et tu es prévenu. Lecture et écriture par acli ou le connecteur Atlassian pour Jira, par le connecteur Linear ; sans eux, rien ne part et il le dit. Aucun autre plugin n'est nécessaire.

Ce que ça coûte, annoncé avant chaque go par `conflits.py estimer` (même barème que plus haut) :

| Poste | Base | Coût |
|---|---|---|
| Les marquages, le registre, l'onglet « Conflits » | scripts, sans modèle | 0 |
| Le jugement des sujets | sous-agents Sonnet, effort medium, lots de 10 sujets et moins de 45 Ko lus en une fois, extraits de quelques lignes seulement ; chaque sous-agent porte environ 78 000 tokens avant son lot (consigne système, outils, règles) | environ 3,7 $ pour 140 sujets (mesuré : 2,18 $ pour 97 sujets en 11 lots) |
| La session des conflits | Opus, environ 100 000 tokens de contexte relus à chaque appel : lancer et recevoir les lots (trois appels par lot), l'aperçu, puis une décision par encadré (environ un sujet sur cinq) | environ 6,8 $ pour 140 sujets (mesuré : 3,05 $ pour lancer et recevoir les 11 lots de 97 sujets) |
| La passe du lundi, dans le point du matin | Sonnet, sujets nouveaux depuis le dernier passage, 90 000 caractères d'extraits au plus pour tous les Studios | environ 0,2 $ pour 20 sujets nouveaux ; rien une semaine sans rien de nouveau, ni quand elle est sautée (au-delà de 90 000 caractères, le cas aujourd'hui sur les Studios mesurés) ; compté dans le coût du point du matin |
| Retrouver les tickets touchés | 8 tickets ouverts lus au plus par conflit tranché, descriptions coupées à 1 000 caractères, un sous-agent Sonnet par lot ; les terminés, titre seul | environ 0,1 % de la semaine pour 10 conflits, redit avant la recherche |
| **Un premier relevé d'un Studio de 97 sujets** | estimation arrondie vers le haut (x 1,15) | **environ 7,2 dollars, 0,50 % de la semaine**, dont 6,1 $ pour le relevé lui-même (mesuré : 5,2 dollars, 0,36 %) et 1,1 $ pour une vingtaine de décisions |
| Un rattrapage d'un Studio de 140 sujets | au-dessus de 0,5 % : un dossier à la fois | environ 0,7 % en un lancement, 0,15 à 0,4 % par dossier |

- Seuils : un lancement à 0,5 % de la semaine au plus ; au-delà, il propose de traiter un dossier à la fois. Usage normal (une relecture par semaine et par Studio suivi, seulement ce qui a changé) : bien sous 2 % par semaine.
- Mesuré le 2026-11-18 sur le premier relevé d'un vrai Studio (97 sujets, 11 sous-agents), dans les transcriptions : sous-agents 638 000 tokens écrits en cache, 2,58 millions relus, 33 000 en sortie, 2,18 dollars ; session des conflits 181 000 écrits, 6,85 millions relus, 39 000 en sortie, 3,05 dollars. Soit 5,2 dollars, 0,36 % de la semaine, pour 0,33 % annoncés, mais avec deux erreurs qui se compensaient (sous-agents +48 %, session -49 %) et « 92 000 tokens d'extraits » pour 3,3 millions de tokens traités. L'estimation rejouée sur ces chiffres donne 6,1 $ (+16 %).
- Rejoué le 2026-11-10 sur deux Studios réels, marquages du rattrapage à la main retirés : le relevé retrouve 85 % et 82 % de leurs cas, et ne repropose aucun passage déjà marqué.

## Limites connues

À corriger après le partage :

- Le point du matin s'écrit même quand Gmail ou Slack n'est pas connecté, ou quand l'exécution n'a pas pu charger un de leurs outils : la source manque sans que l'onglet Today le dise, et il peut afficher « rien à traiter ».
- Les hooks échouent sans trace : si `python3` ne marche plus, tes sessions démarrent sans les règles, sans aucun signe.
- Une règle ajoutée par une nouvelle version du plugin arrive dans toutes tes sessions sans ton go ; le `CHANGELOG.md` dit ce que chaque version change.
- `projets.py --essai`, annoncé sans écriture, écrit un fichier d'estimations dans `~/Mon Studio`.
- Une échéance dépassée reste en tête du tableau, en rouge, sans fin.
- La relecture des conflits du lundi ne relit rien aujourd'hui : elle saute un Studio dont l'ingestion automatique est active (en supposant, à tort, que l'ingestion inscrit ses conflits) et tout lundi où les sujets nouveaux dépassent 90 000 caractères d'extraits, ce qui est le cas normal (350 sujets et plus par semaine sur les Studios mesurés). L'onglet « Conflits » le dit ; relance la relecture à la main dans la session des conflits d'un Studio.
- Une demande « À toi de jouer » de plus de 14 jours n'est jamais reproposée en « encore d'actualité ? » : elle reste dans « Anciennes » jusqu'à ce que tu la fermes.
- Le tableau est trié par impact et par effort, sans modèle : « D'abord » ce qui presse (échéance proche ou dépassée, quelqu'un ou une session qui attend, « bloqué », sécurité), les réponses courtes en premier et la raison sur la ligne ; « Ensuite » le reste ; « Peut attendre », repliée, le rangement. Une session ou l'ingestion peut qualifier sa ligne dans son texte : « (impact fort : client attend) », « (impact faible) », « (effort court) ».
- La vérification de 11 h, 14 h et 17 h ferme les lignes Slack auxquelles tu as répondu ; c'est un jugement du modèle. Premier relevé réel (2026-11-18, deux passages sur Haiku) : 8 lignes fermées, 4 à raison, 1 discutable, 3 à tort (une attente prise pour une action faite, une preuve sur un autre sujet, une suite fermée avec le message qui l'avait créée). Depuis la 0.3.9, le connecteur refuse une preuve qui est la demande, son message parent ou un message plus ancien, et la consigne dit qu'une promesse ou une attente n'est pas une action faite ; une ligne peut encore être fermée à tort.
- Le refus d'un lancement sans modèle n'a pas encore été vu en session réelle : s'il bloque un lancement, dis « coupe le contrôle du modèle » dans `/cockpit:mon-studio` (voir « Ce qu'il installe »).
- Quelques textes de lignes sont abîmés : un morceau manque après « : », un numéro de question est répété, une suite est vide.
- Les lignes « Archiver cette session ? » restent des questions à ouvrir, pas des lignes « en un clic ».
- Relèvent du plugin d'ingestion, pas du cockpit : voir qu'un rappel est fait (invitation envoyée, mail parti), écrire l'échéance d'une demande datée, écrire des rappels plus courts (« titre : détail »), ne pas relever deux fois la même demande.
- Mac seulement. Sous Windows, `python3` peut ouvrir le Microsoft Store : le message « Mac seulement » ne s'affiche alors pas.

## Contact

Mainteneur : Eric Brandenburg.

## Pour qui maintient le plugin

- Un skill par dossier `skills/<nom>/`. Mon Studio est décrit dans `skills/mon-studio/SKILL.md` et en tête de chacun de ses scripts : à lire avant de le modifier. Ce qu'un développeur doit savoir avant d'y toucher : `docs/pour-les-devs.md`.
- `mon-studio` et `conflits` ne se lancent que quand le PM les tape (`disable-model-invocation: true`). `point` peut se lancer seul ; sa raison est dans `.github/auto-invocable-skills`. Contrôle des en-têtes : `python3 .github/scripts/check_skills.py`.
- Les tests : `python3 -m unittest discover -s tests < /dev/null`. Ils comprennent une garde de confidentialité (aucun nom de client, ticket réel ni adresse de tableau personnel dans le dépôt) et les tests d'assemblage (`tests/test_assembly.py`).
- Les evals, avant chaque publication : Claude suit-il encore les règles et les skills ? Cinq cas dans `evals/`, environ 0,65 $ la série : `docs/evals.md`.
- Les outils posés dans `~/Mon Studio/.parc/` gardent leurs noms : les sessions et les hooks les appellent là.
- Les interrupteurs (autorisations, réponses en direct, seuil de session lourde, règle optionnelle, contrôle du modèle, contrôle du format, réglage d'ouverture, contrôle du barème, nom du PM) se posent par `/cockpit:mon-studio`, jamais en éditant `cockpit.json` à la main.
- Code, commentaires et commits en anglais ; skills, README et docs en français.
