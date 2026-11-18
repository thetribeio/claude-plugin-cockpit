# Savoir dans un mois si le cockpit sert

Deux signaux, lisibles par l'équipe sans interroger les PM. Lecture prévue un mois après l'annonce.

Tout ce que le cockpit fait vit sur le poste du PM : le dossier `~/Mon Studio`, les tâches « Point du matin », la page privée. Rien de cela n'est visible à distance, et c'est voulu. Les deux signaux s'appuient donc sur ce qui passe par GitHub et par le canal de l'équipe.

## Signal 1 · Des postes qui récupèrent le plugin

**Ce qu'on lit** : le nombre de personnes distinctes qui ont récupéré le dépôt `thetribeio/claude-plugin-cockpit` (une installation ou une mise à jour depuis le terminal récupère le dépôt).

**Comment le lire** : sur GitHub, dépôt `claude-plugin-cockpit`, onglet Insights, puis Traffic, encadré « Git clones », chiffre « Unique cloners ». Il faut un accès administrateur au dépôt. GitHub ne garde que les 14 derniers jours : relever le chiffre deux fois, à J+15 et à J+30, et le noter dans le canal.

**Le seuil** : au moins 5 clones uniques par quinzaine en dehors du mainteneur, et le chiffre ne baisse pas entre les deux relevés. Un chiffre qui retombe à zéro la seconde quinzaine dit qu'on l'a essayé sans le garder.

**À vérifier avant de compter dessus** : une installation depuis le catalogue de l'app passe peut-être par les serveurs de claude.ai plutôt que par le poste ; dans ce cas ce chiffre ne compte que les installations en terminal et reste un minimum. Si la console d'administration claude.ai de l'organisation affiche les installations par plugin, ce chiffre-là la remplace.

## Signal 2 · Des PM qui en parlent

**Ce qu'on lit** : le nombre de PM distincts, hors mainteneur, qui ont écrit au sujet du cockpit : une issue sur le dépôt, une réponse dans le fil de l'annonce, une question au mainteneur.

**Comment le lire** : la liste des issues du dépôt (ouvertes et fermées), et le fil de l'annonce dans le canal. Compter les personnes, pas les messages.

**Le seuil** : au moins 3 PM distincts en un mois. Un outil qu'on garde produit des demandes (« la ligne de tel projet manque », « peut-on avoir… ») ; un mois de silence complet dit qu'il ne sert pas, même avec des installations.

## Lecture

- Les deux signaux au seuil : ça sert, on continue.
- Installations sans retours : on l'essaie sans le garder. Demander à deux PM ce qui les a arrêtés.
- Retours sans installations : le signal 1 compte mal (voir « À vérifier »), se fier au signal 2.
- Ni l'un ni l'autre : revoir l'annonce et la démonstration avant de toucher au plugin.
