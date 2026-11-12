# CLAUDE.md

Guidance for Claude Code, and for people, working in this repository. Rename this file to `CLAUDE.md` at the repository root and fill in every `<...>`.

## Project overview

A Google Dataform project that turns raw BigQuery data into a layered warehouse for <organization>.

- Sources: <erp>, <crm>, <...>
- Business units: <sales>, <finance>, <...>
- Machine-to-machine targets: <web app>, <CRM import>, <sync jobs>
- Human audiences: <management dashboard>, <...>
- Target: BigQuery project `<project>`, location `<location>`

## Layer architecture

Raw sources → declarations → L1 → L2 (business units) → L3P (machine to machine) / L3R (people)

| Layer | Schema pattern | Purpose |
| --- | --- | --- |
| Declarations | `declaration_{source}` | Read-only references to raw tables |
| L1 | `l1_{source}` | One model per raw table: casts, surrogate keys, source names kept |
| L2 | `l2_{business_unit}` | Business logic, one schema per business unit, plus shared schemas |
| L3P | `l3p_{target}` | Tables read by a program: one schema per target system |
| L3R | `l3r_{audience}` | Views read by people through BI: one schema per audience |

### L2 schemas

| Schema | Business unit / role | Owner |
| --- | --- | --- |
| `l2_sales` | Sales: invoices, <...> | <owner> |
| `l2_masterdata` | Shared: conformed dimensions (customer, <...>) | <owner> |
| `l2_relationship` | Shared: bridges between units and their systems, e.g. `rel_crm_erp_customer` | <owner> |

### L3 schemas

| Schema | Reader | Target or audience, and owner | Fixed field names (do not rename) |
| --- | --- | --- | --- |
| `l3p_webapp` | Program | Web app backend, <owner> | `id`, `name`, `country`, `entry_date`, `exit_date`, `is_active`, `updated_at` |
| `l3r_sales` | People | Sales dashboard | none |

## Naming conventions

- Table prefixes: `dim_`, `fct_`, `rel_`, `kpi_`.
- Column suffixes from L2 on: `_id` key, `_cd` code, `_ds` description, `_dt` date, `_fl` flag, `_nr` number, `_qt` quantity, `_vl` value, `_pc` percentage.
- English names from L2 on; L1 keeps the source names.

## Keys and sentinels

- Key strategy: `<md5_hex | farm_fingerprint | sha256_hex | natural>`, set in `includes/keys.js`, because <why it fits this system, e.g. "apps store the keys" or "Power BI import models only">. Models call `keys.surrogate`, `keys.composite` and `keys.unknown()`. Changing the strategy changes every key downstream.
- `keys.unknown()` means not assigned; `keys.noData()` means the source key was null.
- Each dimension has one `'Not Assigned'` row keyed `keys.unknown()`. Facts coalesce their foreign keys to it. L3P filters it out; L3R shows it.
- Scoped default members (the source's own catch-all per parent): <list them, e.g. "sector 0 'Default' per customer and year">. They have real keys, and presentation keeps them.

## Key design decisions

- <decision>: <why>. Add one line whenever a reviewer would otherwise "fix" something intentional.

## Source semantics and gotchas

- `<table.field>` means <x>, not <y>. Found <date> while <...>.

## Glossary

`docs/glossary.md` is the glossary of this repository: sources, business terms (source language → English), codes, measures, every L2 and L3 object, and the names that mislead.

- Read it before naming a column, decoding a code or adding a model.
- Update it in the same change as the code, and check it before every commit. If nothing in a commit belongs in it, add the trailer `Glossary: unchanged` to the commit message.

## Commands

```bash
dataform compile
dataform run --dry-run --actions <model>
dataform run --actions <model> --include-deps
dataform run --tags l3p_webapp --include-deps
sqlfluff lint <changed files>
```

Never run `dataform format`; it rewrites every file. Match the surrounding style by hand: lowercase keywords, leading commas, 2-space indent, aligned aliases.

## Do not modify

- `<folder>`: <why>
