#!/usr/bin/env python3
"""Kimball scan for a Dataform repository.

Collects static evidence for the Kimball scorecard (references/kimball-scorecard.md):
grain declarations, grain assertions, unknown-member rows, conformed dimensions, the bus
matrix, calendars, aggregates, naming, assertions and glossary coverage. It reads
definitions/**/*.sqlx and docs/glossary.md, never connects to BigQuery, and needs only the
Python standard library.

The checks are regex heuristics: treat the output as evidence to confirm, not as a verdict.

Usage:
  python3 kimball_scan.py [REPO] [--all] [--model NAME] [--json] [--fail-under PCT]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SUFFIXES = ("_id", "_cd", "_ds", "_dt", "_fl", "_nr", "_qt", "_vl", "_pc")
KINDS = ("dim", "fct", "rel", "kpi")
SQL_TYPES = {
    "string", "int64", "int", "integer", "smallint", "bigint", "tinyint", "byteint", "numeric",
    "bignumeric", "decimal", "bigdecimal", "float64", "float", "bool", "boolean", "bytes", "date",
    "datetime", "time", "timestamp", "json", "geography", "interval", "array", "struct", "range",
}
# The unknown-member key in every key strategy: the keys helper, an inline md5/sha256/farm_fingerprint
# of 'na' (optionally wrapped in to_hex), the INT64 convention -1, or the natural-key literal 'na'.
UNKNOWN_KEY_EXPR = (
    r"(?:\$\{\s*keys\.unknown\(\)\s*\}"
    r"|(?:to_hex\(\s*)?(?:md5|sha256|farm_fingerprint)\(\s*(?:cast\(\s*)?['\"]na['\"](?:\s+as\s+string\s*\))?\s*\)\s*\)?"
    r"|-1|'na')"
)
SENTINEL_RE = re.compile(r"\bunion\b[\s\S]*?" + UNKNOWN_KEY_EXPR + r"\s+as\s+\w*_id\b", re.I)
TYPED_SENTINEL_RE = re.compile(r"\bjoin\s+\w+(?:\s+as\s+\w+)?\s+on\s+false\b", re.I)
GRAIN_RE = re.compile(r"(--|//|/\*|description\s*:)[^\n]*\bgrain\b", re.I)
REF_OBJ_RE = re.compile(r"ref\(\s*\{(.*?)\}\s*\)", re.S)
REF_STR_RE = re.compile(r"ref\(\s*['\"]([\w-]+)['\"]\s*(?:,\s*['\"]([\w-]+)['\"]\s*)?\)")
ALIAS_RE = re.compile(r"\bas\s+([A-Za-z_]\w*)\b(?!\s*\()", re.I)
TABLE_ALIAS_CONTEXT_RE = re.compile(r"(?:\bfrom|\bjoin)\s+[\w.`\-]+\s*$", re.I)

# Repository criteria: id -> (name, weight, critical, automatic)
CRITERIA = {
    "R1": ("Grain declared", 3, True, True),
    "R2": ("Grain enforced (uniqueKey)", 3, True, True),
    "R3": ("Conformed dimensions", 3, True, True),
    "R4": ("Unknown-member rows in dimensions", 2, False, True),
    "R5": ("Fact foreign keys never null", 3, True, False),
    "R6": ("Surrogate keys and natural keys", 2, False, False),
    "R7": ("One conformed date dimension", 2, False, True),
    "R8": ("Fact table types and additivity", 2, False, False),
    "R9": ("Aggregates built on atomic facts", 2, False, True),
    "R10": ("Star schemas, not snowflakes", 1, False, False),
    "R11": ("Slowly changing dimension policy", 2, False, False),
    "R12": ("Bridges for many-to-many", 1, False, False),
    "R13": ("Naming conventions", 1, False, True),
    "R14": ("Presentation area for people (L3R)", 1, False, True),
    "R15": ("Data-quality screens (assertions)", 2, False, True),
    "R16": ("Documentation (glossary coverage)", 2, False, True),
}


def coverage_score(pct: float | None) -> int | None:
    if pct is None:
        return None
    return 2 if pct >= 90 else 1 if pct >= 50 else 0


def balanced_block(text: str, brace_pos: int) -> tuple[str, int]:
    """Text inside the {...} block whose opening brace is at brace_pos, and the end index."""
    depth = 0
    for j in range(brace_pos, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_pos + 1:j], j + 1
    return text[brace_pos + 1:], len(text)


def strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?<![:\"'])//[^\n]*", " ", text)


def parse_model(path: Path, root: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    config_text, body = "", raw
    m = re.search(r"\bconfig\s*\{", raw)
    if m:
        config_text, end = balanced_block(raw, raw.index("{", m.start()))
        body = raw[:m.start()] + raw[end:]
    # drop js / pre_operations / post_operations blocks from the SQL body
    while True:
        jm = re.search(r"\b(js|pre_operations|post_operations)\s*\{", body)
        if not jm:
            break
        _, jend = balanced_block(body, body.index("{", jm.start()))
        body = body[:jm.start()] + body[jend:]
    config = strip_js_comments(config_text)

    def cfg(key: str) -> str | None:
        km = re.search(rf"\b{key}\s*:\s*['\"]([^'\"]+)['\"]", config)
        return km.group(1) if km else None

    name = cfg("name") or path.stem
    schema = cfg("schema") or "dataform"
    mtype = cfg("type") or "view"
    assertions_text = ""
    am = re.search(r"\bassertions\s*:\s*\{", config)
    if am:
        assertions_text, _ = balanced_block(config, config.index("{", am.start()))

    refs = []
    for om in REF_OBJ_RE.finditer(body):
        inner = om.group(1)
        s = re.search(r"schema\s*:\s*['\"](\w+)['\"]", inner)
        n = re.search(r"name\s*:\s*['\"](\w+)['\"]", inner)
        if n:
            refs.append((s.group(1) if s else None, n.group(1)))
    for sm in REF_STR_RE.finditer(body):
        refs.append((sm.group(1), sm.group(2)) if sm.group(2) else (None, sm.group(1)))

    sql = re.sub(r"--[^\n]*", " ", body)
    aliases = []
    for alm in ALIAS_RE.finditer(sql):
        alias = alm.group(1)
        before = sql[max(0, alm.start() - 200):alm.start()].rstrip()
        if alias.lower() in SQL_TYPES or before.endswith("}") or TABLE_ALIAS_CONTEXT_RE.search(before):
            continue
        aliases.append(alias)

    if schema.startswith("declaration_") or mtype == "declaration":
        layer = "declaration"
    elif mtype == "assertion":
        layer = "assertion"
    else:
        layer = next((p for p in ("l1", "l2", "l3p", "l3r") if schema.startswith(p + "_")), "other")
    prefix = name.split("_", 1)[0]
    return {
        "name": name,
        "schema": schema,
        "type": mtype,
        "layer": layer,
        "kind": prefix if prefix in KINDS else "other",
        "file": str(path.relative_to(root)),
        "grain_declared": bool(GRAIN_RE.search(raw)),
        "unique_key": bool(re.search(r"\buniqueKeys?\s*:", assertions_text)),
        "any_assertion": bool(re.search(r"\b(uniqueKeys?|nonNull|rowConditions)\s*:", assertions_text)),
        "unknown_row": bool(SENTINEL_RE.search(sql) or TYPED_SENTINEL_RE.search(sql)),
        "generates_dates": "generate_date_array" in sql.lower(),
        "refs": sorted(set(refs)),
        "aliases": aliases,
        "bad_aliases": sorted({a for a in aliases if not a.lower().endswith(SUFFIXES)}),
        "measures": sorted({a for a in aliases if a.lower().endswith(("_vl", "_qt", "_pc"))}),
    }


def pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def scan(root: Path) -> dict:
    files = sorted((root / "definitions").rglob("*.sqlx"))
    models = [parse_model(f, root) for f in files]
    by_name = defaultdict(list)
    for mo in models:
        by_name[mo["name"]].append(mo)
    for mo in models:  # resolve schema-less refs when the name is unique
        mo["refs"] = sorted({(s or (by_name[n][0]["schema"] if len(by_name.get(n, [])) == 1 else "?"), n)
                             for s, n in mo["refs"]})

    l2 = [m for m in models if m["layer"] == "l2" and m["type"] != "operations"]
    l2_typed = [m for m in l2 if m["kind"] in KINDS]
    dims = [m for m in l2 if m["kind"] == "dim"]
    facts = [m for m in l2 if m["kind"] == "fct"]
    kpis = [m for m in l2 if m["kind"] == "kpi"]
    l3r = [m for m in models if m["layer"] == "l3r"]
    scored = l2 + l3r

    # R3 conformed dimensions: same dimension name in several L2 schemas
    dim_groups = defaultdict(list)
    for d in dims:
        dim_groups[d["name"]].append(d)
    conformance = []
    for dname, group in sorted(dim_groups.items()):
        if len(group) < 2:
            continue
        hub = [g for g in group if g["schema"] == "l2_masterdata"]
        copies = []
        for g in group:
            if g in hub:
                continue
            derived = any(s == "l2_masterdata" and n == dname for s, n in g["refs"])
            copies.append({"schema": g["schema"], "derived": derived})
        independent = [c for c in copies if not c["derived"]] if hub else copies
        conformance.append({"dimension": dname, "schemas": [g["schema"] for g in group],
                            "hub": bool(hub), "independent_copies": [c["schema"] for c in independent]})
    independent_groups = [c for c in conformance if c["independent_copies"]]

    # R7 calendars
    calendars = [m for m in l2 if "calendar" in m["name"]]
    base_calendars = [c for c in calendars if c["generates_dates"]]

    # R9 aggregates on atomic facts
    kpi_ok = [k for k in kpis if any(n.startswith("fct_") for _, n in k["refs"])]

    # R14 presentation area: L3R reads only L2/L3R
    l3r_ok = [m for m in l3r if all((s or "").startswith(("l2_", "l3r_")) for s, _ in m["refs"])]

    # R13 naming
    all_aliases = [a for m in scored for a in m["aliases"]]
    bad_aliases = [a for a in all_aliases if not a.lower().endswith(SUFFIXES)]
    alias_pct = pct(len(all_aliases) - len(bad_aliases), len(all_aliases))
    prefix_pct = pct(len(l2_typed), len(l2))

    # R15 assertions
    custom_assertions = [m for m in models if m["type"] == "assertion"]
    assert_pct = pct(sum(m["any_assertion"] for m in l2_typed), len(l2_typed))

    # R16 glossary
    glossary_path = root / "docs" / "glossary.md"
    glossary_pct = None
    missing_in_glossary = []
    if glossary_path.exists():
        gtext = glossary_path.read_text(encoding="utf-8", errors="replace")
        catalogued = [m for m in models if m["layer"] in ("l2", "l3p", "l3r") and m["type"] != "assertion"]
        missing_in_glossary = [f'{m["schema"]}.{m["name"]}' for m in catalogued
                               if not re.search(rf"(?<![\w]){re.escape(m['name'])}(?![\w])", gtext)]
        glossary_pct = pct(len(catalogued) - len(missing_in_glossary), len(catalogued))

    grain_pct = pct(sum(m["grain_declared"] for m in l2_typed), len(l2_typed))
    unique_pct = pct(sum(m["unique_key"] for m in l2_typed), len(l2_typed))
    unknown_pct = pct(sum(m["unknown_row"] for m in dims), len(dims))

    r3 = 2 if not independent_groups else 1 if len(independent_groups) <= 2 else 0
    r7 = None if not calendars else 2 if len(base_calendars) == 1 else 1 if len(base_calendars) > 1 else 0
    r15 = coverage_score(assert_pct)
    if r15 == 2 and not custom_assertions:
        r15 = 1
    naming_pct = min(p for p in (alias_pct, prefix_pct) if p is not None) if (alias_pct or prefix_pct) else None

    results = {
        "R1": (coverage_score(grain_pct), f"{grain_pct}% of {len(l2_typed)} L2 dim/fct/rel/kpi models have a grain comment"),
        "R2": (coverage_score(unique_pct), f"{unique_pct}% of {len(l2_typed)} L2 dim/fct/rel/kpi models assert uniqueKey"),
        "R3": (r3, f"{len(independent_groups)} dimension name(s) built independently in several L2 schemas (proposed score: confirm whether they are different entities)"),
        "R4": (coverage_score(unknown_pct), f"{unknown_pct}% of {len(dims)} L2 dimensions have an unknown-member row"),
        "R7": (r7, f"{len(base_calendars)} generated calendar(s) among {len(calendars)} L2 calendar model(s)"),
        "R9": (coverage_score(pct(len(kpi_ok), len(kpis))) if kpis else None, f"{len(kpi_ok)} of {len(kpis)} kpi_ models read a fct_ model"),
        "R13": (coverage_score(naming_pct), f"{alias_pct}% of {len(all_aliases)} column aliases in L2/L3R have a valid suffix; {prefix_pct}% of {len(l2)} L2 models have a dim_/fct_/rel_/kpi_ prefix"),
        "R14": (coverage_score(pct(len(l3r_ok), len(l3r))) if l3r else None, f"{len(l3r_ok)} of {len(l3r)} L3R models read only L2/L3R"),
        "R15": (r15, f"{assert_pct}% of L2 dim/fct/rel/kpi models have assertions; {len(custom_assertions)} custom assertion model(s)"),
        "R16": (coverage_score(glossary_pct) if glossary_path.exists() else 0,
                f"{glossary_pct}% of L2/L3 models named in docs/glossary.md" if glossary_path.exists() else "no docs/glossary.md"),
    }
    earned = sum(results[c][0] * CRITERIA[c][1] for c in results if results[c][0] is not None)
    possible = sum(2 * CRITERIA[c][1] for c in results if results[c][0] is not None)

    # bus matrix: L2 facts x dimensions they reference
    dim_use = defaultdict(int)
    for f in facts:
        for _, n in f["refs"]:
            if n.startswith("dim_"):
                dim_use[n] += 1
    matrix_dims = sorted(dim_use, key=lambda d: (-dim_use[d], d))
    bus = []
    for f in sorted(facts, key=lambda x: (x["schema"], x["name"])):
        cells = {}
        for s, n in f["refs"]:
            if n.startswith("dim_"):
                cells[n] = (s or "?").replace("l2_", "")
        bus.append({"fact": f'{f["schema"]}.{f["name"]}', "dims": cells})

    return {
        "repo": str(root),
        "counts": {
            "models": len(models), "l2": len(l2), "dim": len(dims), "fct": len(facts),
            "rel": sum(m["kind"] == "rel" for m in l2), "kpi": len(kpis),
            "l2_other": len(l2) - len(l2_typed), "l3r": len(l3r),
            "l3p_not_scored": sum(m["layer"] == "l3p" for m in models),
        },
        "criteria": {c: {"name": CRITERIA[c][0], "weight": CRITERIA[c][1], "critical": CRITERIA[c][2],
                         "automatic": CRITERIA[c][3],
                         "score": results.get(c, (None, ""))[0], "evidence": results.get(c, (None, "needs review"))[1]}
                     for c in CRITERIA},
        "automatic_subtotal_pct": round(100.0 * earned / possible, 1) if possible else None,
        "conformance": conformance,
        "calendars": [{"model": f'{c["schema"]}.{c["name"]}', "generated": c["generates_dates"]} for c in calendars],
        "kpi_without_fact": [f'{k["schema"]}.{k["name"]}' for k in kpis if k not in kpi_ok],
        "l3r_reading_below_l2": [f'{m["schema"]}.{m["name"]}' for m in l3r if m not in l3r_ok],
        "missing_in_glossary": missing_in_glossary,
        "bus_matrix": {"dimensions": matrix_dims, "rows": bus},
        "models": models,
    }


def md_models(models: list[dict], show_all: bool) -> list[str]:
    rows = []
    for m in sorted(models, key=lambda x: (x["schema"], x["name"])):
        issues = []
        # grain, uniqueKey and unknown rows are checked in L2; L3R views inherit them from L2
        if m["layer"] == "l2" and m["kind"] in KINDS and not m["grain_declared"]:
            issues.append("no grain comment")
        if m["layer"] == "l2" and m["kind"] in KINDS and not m["unique_key"]:
            issues.append("no uniqueKey")
        if m["layer"] == "l2" and m["kind"] == "dim" and not m["unknown_row"]:
            issues.append("no unknown-member row")
        if m["layer"] == "l3r" and any(not (s or "").startswith(("l2_", "l3r_")) for s, _ in m["refs"]):
            issues.append("reads below L2")
        if m["kind"] == "other" and m["layer"] == "l2":
            issues.append("no dim_/fct_/rel_/kpi_ prefix")
        if m["bad_aliases"]:
            issues.append(f'{len(m["bad_aliases"])} alias(es) without suffix: ' + ", ".join(m["bad_aliases"][:4])
                          + (" …" if len(m["bad_aliases"]) > 4 else ""))
        if issues or show_all:
            rows.append(f'| `{m["schema"]}.{m["name"]}` | {m["kind"]} | {"; ".join(issues) or "ok"} |')
    return rows


def render_markdown(r: dict, show_all: bool) -> str:
    c = r["counts"]
    out = [f"# Kimball scan: `{r['repo']}`", "",
           f"Scanned {c['models']} models: L2 {c['l2']} (dim {c['dim']}, fct {c['fct']}, rel {c['rel']}, kpi {c['kpi']}, "
           f"other {c['l2_other']}), L3R {c['l3r']}. L3P ({c['l3p_not_scored']}) is a machine-to-machine contract and isn't scored.",
           "", "## Repository criteria", "",
           "| ID | Criterion | Weight | Score (0-2) | Evidence |", "| --- | --- | --- | --- | --- |"]
    for cid, cr in r["criteria"].items():
        score = "review" if not cr["automatic"] else ("n/a" if cr["score"] is None else str(cr["score"]))
        crit = " (critical)" if cr["critical"] else ""
        out.append(f"| {cid} | {cr['name']}{crit} | {cr['weight']} | {score} | {cr['evidence']} |")
    out += ["", f"**Automatic subtotal: {r['automatic_subtotal_pct']}%** over the automatic criteria only. "
                "The final score also needs the review criteria (R5, R6, R8, R10, R11, R12); see references/kimball-scorecard.md.", ""]
    if r["conformance"]:
        out += ["## Dimensions built in several L2 schemas", "", "| Dimension | Schemas | Independent copies |", "| --- | --- | --- |"]
        for g in r["conformance"]:
            out.append(f"| `{g['dimension']}` | {', '.join(g['schemas'])} | {', '.join(g['independent_copies']) or 'none (derived from l2_masterdata)'} |")
        out.append("")
    if r["calendars"]:
        out += ["## Calendars", ""] + [f"- `{x['model']}`: {'generates dates' if x['generated'] else 'derived'}" for x in r["calendars"]] + [""]
    for key, title in (("kpi_without_fact", "kpi_ models that don't read a fct_ model"),
                       ("l3r_reading_below_l2", "L3R models that read below L2"),
                       ("missing_in_glossary", "Models missing from docs/glossary.md")):
        if r[key]:
            out += [f"## {title}", ""] + [f"- `{x}`" for x in r[key][:40]] + (["- …"] if len(r[key]) > 40 else []) + [""]
    dims = r["bus_matrix"]["dimensions"]
    if dims:
        shown = dims[:20]
        out += ["## Bus matrix (L2 facts × the dimensions they reference)", "",
                "Cells name the schema the dimension comes from; `masterdata` means conformed.", "",
                "| Fact | " + " | ".join(f"`{d}`" for d in shown) + " |", "| --- |" + " --- |" * len(shown)]
        for row in r["bus_matrix"]["rows"]:
            out.append(f"| `{row['fact']}` | " + " | ".join(row["dims"].get(d, "") for d in shown) + " |")
        if len(dims) > 20:
            out.append(f"\n{len(dims) - 20} more dimension column(s) in `--json`.")
        out.append("")
    rows = md_models([m for m in r["models"] if m["layer"] in ("l2", "l3r") and m["type"] not in ("operations", "assertion")], show_all)
    if rows:
        out += ["## Models with findings" if not show_all else "## Models", "", "| Model | Kind | Findings |", "| --- | --- | --- |"] + rows + [""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Static Kimball evidence for a Dataform repository.")
    ap.add_argument("repo", nargs="?", default=".", help="repository root (contains definitions/)")
    ap.add_argument("--all", action="store_true", help="list every model, not only those with findings")
    ap.add_argument("--model", help="print the checks for one model name")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--fail-under", type=float, help="exit 1 if the automatic subtotal is below this percentage")
    args = ap.parse_args()
    root = Path(args.repo).resolve()
    if not (root / "definitions").is_dir():
        print(f"no definitions/ folder in {root}", file=sys.stderr)
        return 2
    result = scan(root)
    if args.model:
        hits = [m for m in result["models"] if m["name"] == args.model]
        print(json.dumps(hits, indent=2) if hits else f"model {args.model} not found")
        return 0 if hits else 2
    if args.json:
        print(json.dumps(result, indent=2, default=list))
    else:
        print(render_markdown(result, args.all))
    if args.fail_under is not None and (result["automatic_subtotal_pct"] or 0) < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
