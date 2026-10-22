"""Génère docs/source-feasibility.md à partir de config/sources.yaml et config/employers.yaml.

Le registre YAML est la source de vérité (une seule). Ce script ne contient AUCUNE donnée de test : il met en forme ce qui
a été observé et consigné dans le registre (`decision_reason`, `tos_note`, `checked_on`...).

    backend/.venv/Scripts/python scripts/gen_source_feasibility.py          # (re)génère le fichier
    backend/.venv/Scripts/python scripts/gen_source_feasibility.py --check  # échoue si le fichier est périmé
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "config" / "sources.yaml"
EMPLOYERS = ROOT / "config" / "employers.yaml"
OUTPUT = ROOT / "docs" / "source-feasibility.md"

TYPE_LABELS = {
    "job_board": "Site d'emploi",
    "aggregator": "Agrégateur",
    "employer_career": "Page carrière",
    "api": "API publique",
    "newsletter": "Newsletter",
    "manual": "Saisie manuelle",
}
METHOD_LABELS = {
    "json_endpoint_html": "Endpoint JSON public + HTML",
    "html_list": "HTML (liste)",
    "html_list_jsonld": "HTML (liste) + JSON-LD",
    "html_list_article": "HTML (liste d'articles)",
    "json_api": "API JSON publique",
    "rss": "Flux RSS",
    "manual": "Saisie manuelle",
    "none": "Aucune",
    "unknown": "Non déterminée",
}
DECISIONS = {
    "implemented": "✅ Implémentée",
    "deferred": "⏸️ Reportée",
    "excluded": "⛔ Exclue",
}
VERIFICATION = {
    "verified": "testée en réel",
    "to_verify": "à vérifier",
    "inaccessible": "inaccessible lors du test",
    "excluded": "écartée sur lecture des conditions",
}


def cell(value: object) -> str:
    """Texte sûr pour une cellule de tableau Markdown."""
    if value is None or value == "":
        return "—"
    text = " ".join(str(value).split())
    return text.replace("|", "\\|")


def iso(value: object) -> str:
    return value.isoformat() if isinstance(value, date) else cell(value)


def countries(entry: dict) -> str:
    c = entry.get("countries") or []
    if c == ["*"]:
        return "Télétravail (tous pays)"
    return ", ".join(c) if c else "—"


def verification_label(s: dict) -> str:
    if s.get("type") == "manual":
        return "pseudo-source : aucune requête émise"
    return VERIFICATION.get(s.get("verification_status", ""), cell(s.get("verification_status")))


def sources_table(rows: list[dict]) -> list[str]:
    out = [
        "| Source | URL vérifiée | Pays | Type | Méthode de collecte | Cartographie du 14/10/2026 | Résultat du test (21/10/2026) et motif | Conditions / restrictions | Vérifiée le |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in rows:
        out.append(
            "| {name} | {url} | {pays} | {type} | {method} | {doc} | {reason} | {tos} | {date} |".format(
                name=f"**{cell(s['name'])}**",
                url="—" if s.get("type") == "manual" else cell(s.get("base_url")),
                pays=countries(s),
                type=TYPE_LABELS.get(s.get("type", ""), cell(s.get("type"))),
                method=METHOD_LABELS.get(s.get("collection_method", ""), cell(s.get("collection_method"))),
                doc=cell(s.get("doc_status")),
                reason=f"_{verification_label(s)}_ — {cell(s.get('decision_reason'))}",
                tos=cell(s.get("tos_note")),
                date=iso(s.get("checked_on")),
            )
        )
    return out


def employers_table(rows: list[dict]) -> list[str]:
    out = [
        "| Employeur | Secteur | Pays | Page carrière vérifiée | Collecte | Statut | Observation | Vérifié le |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in rows:
        collect = f"connecteur `{e['source_key']}`" if e.get("source_key") else "aucune (veille LinkedIn / ajout manuel)"
        out.append(
            "| {name} | {sector} | {country} | {url} | {collect} | {status} | {note} | {date} |".format(
                name=f"**{cell(e.get('name'))}**",
                sector=cell(e.get("sector")),
                country=cell(e.get("country")),
                url=cell(e.get("career_url")) if e.get("career_url") else "_aucune URL vérifiée_",
                collect=collect,
                status=cell(e.get("status")),
                note=cell(e.get("verification_note")),
                date=iso(e.get("checked_on")),
            )
        )
    return out


def render() -> str:
    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["sources"]
    employers = yaml.safe_load(EMPLOYERS.read_text(encoding="utf-8")).get("employers", [])
    by_decision: dict[str, list[dict]] = {"implemented": [], "deferred": [], "excluded": []}
    for s in sources:
        by_decision.setdefault(s["implementation"], []).append(s)
    counts = Counter(s["implementation"] for s in sources)
    checked = sorted({iso(s["checked_on"]) for s in sources if s.get("checked_on")})

    lines = [
        "# Faisabilité des sources",
        "",
        "> **Fichier généré** par `scripts/gen_source_feasibility.py` à partir de `config/sources.yaml` et `config/employers.yaml`.",
        "> Ne pas l'éditer à la main : corriger le registre YAML puis relancer le script (`--check` détecte un fichier périmé).",
        "",
        "## Méthode et limites",
        "",
        "- **« Testée en réel »** : requêtes HTTP réelles effectuées le jour indiqué (client poli : `robots.txt` respecté, délai entre requêtes, "
        "liste blanche d'hôtes). Les extraits de pages utilisés par les tests automatisés sont des fixtures tronquées de pages réelles "
        "(`backend/tests/fixtures/`).",
        "- **« Écartée sur lecture des conditions »** : aucune collecte n'a été tentée ; la décision s'appuie sur les CGU et/ou le `robots.txt` cités.",
        "- Les conditions d'utilisation ont été lues dans les pages consultées ; **ce n'est pas un avis juridique**. En cas de doute, une lecture "
        "humaine reste recommandée (voir la colonne « Conditions / restrictions »).",
        "- Le statut de la cartographie du 14/10/2026 est conservé tel quel, comme observation historique ; les écarts constatés le 21/10/2026 "
        "figurent dans la colonne « Résultat du test ».",
        "- La disponibilité d'URLs directes et de dates de publication est précisée source par source dans la colonne « Résultat du test ». "
        "Quand une source ne fournit pas de date, jobArt affiche « Date inconnue » et n'en déduit jamais une.",
        f"- Dernières vérifications consignées : {', '.join(checked) if checked else 'aucune'}.",
        "",
        "## Synthèse",
        "",
        "| Décision | Nombre |",
        "|---|---|",
    ]
    for key, label in DECISIONS.items():
        lines.append(f"| {label} | {counts.get(key, 0)} |")
    lines += ["", f"Total : {len(sources)} sources étudiées, dont {sum(1 for s in sources if s.get('connector'))} avec un connecteur dédié.", ""]

    titles = {
        "implemented": "## Sources intégrées",
        "deferred": "## Sources reportées (à revérifier)",
        "excluded": "## Sources exclues",
    }
    for key in ("implemented", "deferred", "excluded"):
        rows = by_decision.get(key, [])
        if not rows:
            continue
        lines += [titles[key], ""]
        lines += sources_table(rows)
        lines.append("")

    lines += [
        "## Employeurs ciblés",
        "",
        "Registre `config/employers.yaml` : aucune URL n'est supposée ; `career_url` n'est renseignée que si la page a répondu en HTTP 200 lors de la vérification.",
        "",
    ]
    lines += employers_table(employers)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="ne rien écrire ; échouer si docs/source-feasibility.md n'est pas à jour")
    args = ap.parse_args()
    content = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print("docs/source-feasibility.md est périmé : relancer scripts/gen_source_feasibility.py", file=sys.stderr)
            return 1
        print("docs/source-feasibility.md est à jour.")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"écrit : {OUTPUT.relative_to(ROOT)} ({len(content.splitlines())} lignes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
