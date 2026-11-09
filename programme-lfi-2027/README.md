# Programme LFI — présidentielle 2027 (extraction de melenchon2027.fr)

Extraction **non officielle** et reproductible du programme publié sur <https://melenchon2027.fr>, en un jeu de données unique, consultable et interrogeable. Seul le site fait foi.

## Fichiers

| Fichier | Usage |
|---|---|
| `programme_lfi_2027.html` | **Le document à ouvrir** : fichier unique, hors-ligne, avec recherche, filtres, sommaire, export CSV des résultats. Double-clic suffit. |
| `programme_lfi_2027.md` | Même contenu en Markdown continu (lecture, `grep`, ou à déposer dans une conversation avec une IA pour l'interroger). |
| `programme_lfi_2027.json` | Données structurées : documents → unités → sections → blocs (`kind`, `id`, `text`). Contient les chiffres de contrôle (`meta.stats`). |
| `mesures.csv` | Une ligne par proposition (séparateur `;`, UTF-8 avec BOM : s'ouvre directement dans Excel/LibreOffice). |
| `build.py` + `viewer_template.html` | Le code qui régénère tout. |

## Périmètre

**Inclus** (programme 2027 officiel) :
- *L'Avenir en commun* (6e édition) : introduction, 6 parties, 22 chapitres ;
- 3 plans thématiques : santé, enseignement supérieur & recherche, ruralités ;
- 2 plans d'investissement productif : BTP & logement, automobile ;
- 2 PDF « Autour du programme » : pôle public bancaire, comptes publics (en annexe).

**Exclus volontairement** : synthèse des contributions citoyennes et auditions (matière de construction, pas des propositions), actualités 2022-2025 des groupes thématiques, « comparateurs » d'autres partis (Place Publique, Les Écologistes), programmes historiques (NUPES 2022, NFP 2024, livrets 2022). Ils sont servis par le même site ; les ajouter est possible.

## Identifiants

`P3C1-M002` = partie 3, chapitre 1, mesure 2. Suffixes : `M` mesure, `S` sous-mesure (puce imbriquée sous une mesure), `K` mesure clé, `L` élément de liste d'un plan.

## Contrôles de qualité effectués

- **Comptage** : 881 mesures + 81 sous-mesures + 107 mesures clés = **1 069**, exactement le chiffre annoncé par le site.
- **Exhaustivité** : les 1 211 blocs de texte du livre ont été retrouvés dans le HTML source ; pour chaque chapitre, nombre de `<li>` de la source = mesures + sous-mesures + enveloppes vides (balisage WordPress sans texte).
- Le parseur signale tout texte de la page non repris dans le résultat ; aucun n'est signalé.

## Limites à connaître

- **Plans thématiques / d'investissement** : le site n'y distingue pas les mesures du reste. Les éléments de liste (`L`) sont des *propositions probables* mais incluent aussi de simples énumérations ; l'analyse/diagnostic figure en texte. Ne pas en tirer un décompte de mesures.
- **PDF** : le texte courant est correct ; les graphiques et tableaux chiffrés sortent en vrac. Se reporter au PDF pour les chiffres.
- Le chapitre P6C1 n'a **aucune mesure clé** dans la source (fait du site, pas de l'extraction).
- Le site évolue pendant la campagne : relancer avec `--refresh`. Chaque document porte un `content_sha256` pour détecter une modification.

## Régénérer

```bash
pip install beautifulsoup4 lxml     # + poppler-utils (pdftotext) pour les PDF
python3 build.py --out . --cache ./.cache            # utilise le cache s'il existe
python3 build.py --out . --cache ./.cache --refresh   # retélécharge tout
```

~35 requêtes au total, espacées de 0,4 s. Le livre est lu depuis les pages HTML (balisage sémantique `li.mesure`, `div.mesure-cle`) ; les plans via l'API REST WordPress du site (`/wp-json/wp/v2/pages`).
