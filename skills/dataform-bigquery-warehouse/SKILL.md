---
name: dataform-bigquery-warehouse
description: Design, build, extend and review a layered BigQuery warehouse in Google Dataform (SQLX) - declarations, L1 source models, L2 schemas per business unit of the company, L3P presentation tables for machine-to-machine targets (apps, APIs, CRM, reverse ETL) and L3R reporting views for people (BI dashboards). Covers schema, table and column naming, MD5 surrogate keys, "not assigned" sentinel rows, bridge (rel_) and KPI tables, snapshot history, target contracts, assertions, verification, sqlfluff and CI. Keeps the repository glossary (docs/glossary.md) current on every change and commit. Use when writing or reviewing Dataform/SQLX models, adding a source system or business unit, choosing view vs table vs incremental, exposing data to an application or a dashboard, debugging fan-out, duplicate keys or cyclic references, or bootstrapping a new Dataform repository.
license: MIT
metadata:
  version: "1.0.0"
---

# Dataform BigQuery data warehouse

This skill is a playbook for BigQuery warehouses built with Google Dataform (SQLX). It comes from a production warehouse of about 600 models that reads 25+ source systems and serves web apps, a CRM, BI dashboards and reverse-ETL jobs. It says where logic belongs, how things are named and keyed, and how to prove a change is correct.

**The repository's own conventions come first.** Before writing anything, read the repo's CLAUDE.md or README and two or three neighbouring models in the target folder, then match them. Use this playbook to fill gaps, to review, and to bootstrap new repos. Never use it as a reason to restyle working code.

## Ask before guessing

In a warehouse, a plausible guess becomes a wrong number that nobody notices for months. When the repository (CLAUDE.md, neighbouring models, `docs/`) or the data can't settle something, ask the user before you write it. Never invent it.

Ask about:

- **Ownership:** which business unit owns the process behind a new model, and so which `l2_` schema it belongs to.
- **Reader:** whether a program or a person reads a new L3 table. For L3P, ask for the target's exact field names, types and constraints, and its owner.
- **Grain and keys:** what one row is, and which columns form the business key.
- **Meaning of a field**, when the data doesn't settle it: departure or cancellation date, gross or net, cents or euros, whose id.
- **Business rules:** classification priorities, status thresholds ("lost after how long?"), time windows, which date a report uses, how credit notes count, what "active" means.
- **Placeholders and exclusions:** whether a missing value is unknown (`na`) or a deliberate bucket (a default member, `'Other'`); whether unmatched rows are kept or dropped; which records to exclude, and why.
- **Changes that are hard to undo or that affect others:** renaming, removing or retyping an L3P column; changing a key formula, which changes ids downstream; dropping a model; running `--full-refresh` on an incremental model whose source no longer holds the history.

How to ask:

1. Look first. Search the repository and, if you have data access, query the data. Ask only what is still open, and say what you found.
2. Ask a specific question with the options and your recommendation. For example: "Is `status_dt` the posting date or the payment date? It's never before `document_dt` and is NULL for open invoices, so I think it's the payment date. Which one should the report use?"
3. Group related questions into one message instead of asking them one at a time.
4. Keep working on the parts that don't depend on the answer. Where you need a value in order to continue, put in an explicit placeholder (`<owning_unit>`, `-- TODO: confirm the threshold with finance`), never an invented value, and list the open points at the end.
5. Write the answer where the next person will find it: CLAUDE.md, the model's header comment, or `docs/`.

Don't ask about what the conventions already decide (naming, key formula, model shape), or about what the data shows unambiguously.

## Keep the glossary current

Every repository keeps one glossary at `docs/glossary.md`. It covers the layers, the sources, business terms (source language → English), codes, measures, every L2 and L3 object, and the names that mislead, and it describes what the SQL does now.

- **Read it before you work.** Take column names from its business terms, code meanings from its code lists, and existing models from its catalogues. When the glossary and the SQL disagree, the SQL is the truth: fix the glossary.
- **Update it in every change.** A change to `definitions/` or `includes/` isn't done until the glossary matches it. That covers new, renamed or removed models, columns, business terms, codes, measures, sources, business units, targets and cut-offs, plus any misleading name you find. Update it in the same change, not in a later clean-up.
- **Check it before every commit.** Walk the staged diff through the update table in [references/glossary.md](references/glossary.md), update and stage `docs/glossary.md`, and name the changed sections in the commit message. If nothing in the change belongs in the glossary, add the trailer `Glossary: unchanged` to the message.
- **No glossary yet?** Offer to create one from [assets/templates/docs/glossary.md](assets/templates/docs/glossary.md), filled in from the existing models.

The plugin ships a commit hook (`hooks/hooks.json`, script `scripts/glossary-gate.sh`) that enforces the commit check. It blocks Claude's `git commit` when files under `definitions/` or `includes/` change without `docs/glossary.md`, until the glossary is staged or the message carries `Glossary: unchanged`.

## Architecture

```text
raw tables (written by ELT jobs: Parquet/CSV on GCS, database extracts, API dumps)
└─ declaration_<source>      type "declaration": read-only pointers, no SQL
   └─ l1_<source>            one model per raw table: casts, hashed keys, source-local cleanup
      └─ l2_<business_unit>  business logic, one schema per business unit of the company
         │                   (+ shared schemas: l2_masterdata, l2_relationship, l2_monitoring)
         ├─ l3p_<target>     machine to machine: one schema per target system (app, API, CRM, sync job)
         └─ l3r_<audience>   for people: reports and dashboards, one schema per audience
```

| Layer | Schema | Contains | Usual materialization |
| --- | --- | --- | --- |
| Declarations | `declaration_<source>` | Pointers to raw tables owned by the loaders | none |
| L1 | `l1_<source>` | Source-aligned copies that keep the source column names | `table` for external sources, `view` for light ones, `incremental` for snapshot history |
| L2 | `l2_<business_unit>` | One schema per business unit of the company (sales, finance, hr, a service line, …), plus shared schemas for master data, cross-unit bridges and monitoring | `view`; `table` when expensive or widely read |
| L3P | `l3p_<target>` | Machine to machine: exactly what one target system reads (app backend, API, CRM import, sync or export job). The target dictates names and types | `table` |
| L3R | `l3r_<audience>` | For people: report-scoped views for one audience (management, a business unit's team, a regulator) | `view` |

### L3P or L3R?

Ask who reads the columns:

- **A program** (an app backend, an API, a CRM import, a reverse-ETL or export job, another team's pipeline) → **L3P**. A program needs a stable contract: fixed names and types, its constraints enforced, and breaking changes agreed with the target's owner.
- **A person**, through a dashboard, a BI report, a connected spreadsheet or an ad-hoc analysis → **L3R**. People need readable, report-scoped data that can change together with the report.
- An app that shows charts to its users is still L3P, because the app's backend is what reads the table.

### Dependency rules

1. A model reads only from the layer directly below. L2 may also read other L2 models. L3 never reads declarations, and it reads L1 only as a documented exception.
2. An L1 model reads exactly one raw table. Joins across sources start in L2.
3. Every reference is `${ref({schema: '...', name: '...'})}`. Never hardcode `project.dataset.table`.
4. No cycles. If a dimension needs a value computed from a fact that already depends on that dimension, compute the value in a downstream `rel_` or `kpi_` model.
5. A model lives in the schema of the business unit that owns the process behind it (invoicing → finance, payroll → hr), even when other units read it.
6. `l2_masterdata` is the conformed hub that every business unit shares: company, site, customer, address, geography, calendar and users. Business-unit schemas join to it and never re-derive those entities.
7. A mapping that more than one business unit uses becomes its own `rel_` model in `l2_relationship`. Don't copy it into each unit.

For each layer in detail, see [references/layers.md](references/layers.md).

## Conventions at a glance

- Table prefixes in L2 and L3R: `dim_` dimension, `fct_` fact, `rel_` bridge or mapping, `kpi_` pre-aggregated KPIs. L3P tables use the target's entity names (`customers`, `bookings`).
- Column suffixes, required from L2 on: `_id` hashed key, `_cd` code, `_ds` description, `_dt` date or timestamp, `_fl` flag, `_nr` ordinal or sequence number, `_qt` quantity or count, `_vl` amount or value, `_pc` percentage.
- Column names are English from L2 on. L1 keeps the source names. Names that a target system imposes in L3P are exempt; list them in CLAUDE.md.
- Surrogate keys are hex MD5 strings, hashed once in L1:

  ```sql
  coalesce(to_hex(md5(cast(source_id as string))), to_hex(md5('nd'))) as customer_id
  ```

- `to_hex(md5('na'))` means "not assigned": the lookup failed, or this is the sentinel row. `to_hex(md5('nd'))` means "no data": the source key was null.
- Every dimension has one sentinel row keyed `md5('na')` with `'Not Assigned'` labels. Every foreign key in a fact is `coalesce(dim.x_id, to_hex(md5('na')))`, so a failed lookup never drops a fact. L3P filters out the sentinels before a target system sees them.
- Not every placeholder is that `na` row. A source system's own catch-all inside a parent, such as sector `0` "Default" of each company and year, is a **scoped default member**: it has a real parent-scoped key, it holds real amounts, facts fall back to it before `na`, and presentation keeps it. Catch-all categories (`'Other'`), scope sentinels in L3R, numeric markers (`0` = not banded) and neutral weights are other kinds again. Before adding any placeholder, look up its kind in the comparison table.

Details: [references/naming.md](references/naming.md) and [references/keys-and-sentinels.md](references/keys-and-sentinels.md), which includes the comparison of sentinel kinds.

## Model shape

Every SQLX model has the same shape, so any model reads top to bottom:

```sqlx
config {
  type: "view",
  schema: "l2_sales",
  name: "fct_invoice",
  assertions: {
    uniqueKey: ["invoice_id"]
  }
}

-- Grain: one row per invoice document; credit notes included (credit_note_fl).

with
l1_erp_invoice as (
  select *
  from ${ref({schema: 'l1_erp', name: 'invoice'})}
)

, l2_masterdata_dim_customer as (
  select *
  from ${ref({schema: 'l2_masterdata', name: 'dim_customer'})}
)

, final as (
  select
    invoice.invoice_id
    , coalesce(dim_customer.customer_id, to_hex(md5('na'))) as customer_id
    , invoice.gross_amount                                   as gross_amount_vl
  from l1_erp_invoice as invoice
  left outer join l2_masterdata_dim_customer as dim_customer
    on invoice.customer_id = dim_customer.customer_id
)

select *
from final
```

- One import CTE per `ref`, named `<schema>_<model>`. A filter that belongs to the import goes in that CTE, with a comment.
- A grain comment above the SQL. Every non-obvious filter, exclusion or join condition gets a comment that explains why.
- Logic CTEs come next, then `final`, then `select * from final`.
- The file name equals the config `name`. The folder is `definitions/<layer>/<source | business_unit | target | audience>/`.
- Style: lowercase keywords, leading commas, 2-space indent, explicit `as`, aligned aliases, `left outer join`.

## Workflows

### Add a source system

1. Add one declaration per raw table in `definitions/declarations/<source>/`.
2. Add one L1 model per declaration in `definitions/l1/<source>/`. Select the useful columns, cast types, hash the primary key and every foreign key into `_id` columns, and keep the source names. Put intentional cut-offs here with a comment, for example `where fiscal_year > 2022 -- earlier extracts are unreliable`. Add only cut-offs that someone has confirmed; never invent one.
3. Choose the materialization. A snapshot feed (a full or windowed export every day) gets the change-capture stack from [references/modeling-patterns.md](references/modeling-patterns.md).
4. Run `dataform compile`. The source reaches L2 only when a business unit's model needs it.
5. Add the source to the glossary (§2 source systems), and any release cut-off to §6.

### Add or change an L2 model

1. Pick the schema. A model goes to the business unit that owns the process behind the data. Entities shared by every unit (customer, site, calendar) go to `l2_masterdata`, and mappings between units go to `l2_relationship`. If CLAUDE.md doesn't say which unit owns the process, ask. Then pick the model type (`dim_`, `fct_`, `rel_` or `kpi_`) and write the grain comment before the SQL.
2. Write the import CTEs, then the logic CTEs, then `final`.
3. Keys: reuse the L1 hashes, coalesce every foreign key to `md5('na')`, and namespace keys when two sources share an id space.
4. Dimensions: append the sentinel row with `union all strict corresponding`.
5. Declare `assertions: { uniqueKey: [...] }` on the grain.
6. Verify the change before calling it done. Compile it. Compare the row count and the distinct key count with the driving source. Check every join for fan-out. Reconcile the totals against the source. Follow one known entity end to end. The queries are in [references/quality-and-testing.md](references/quality-and-testing.md).
7. Update the glossary: the model in §8, new business terms in §4, codes in §5, measures in §7, and anything misleading in §10.

### Serve a machine-to-machine target (L3P)

1. Use one schema per target system, `l3p_<target>`. Tag every model `tags: ["l3p_<target>"]` so its sync can run `dataform run --tags l3p_<target> --include-deps`.
2. Emit exactly the target's column names and types, taken from the target's schema, its API documentation or its owner. If none of these is available, ask; never invent field names. Record them in CLAUDE.md as do-not-rename.
3. Filter out sentinel rows and cast to the target's types. Copy the target database's NOT NULL and CHECK constraints into `nonNull` and `rowConditions`, so a bad row fails in Dataform rather than in the sync.
4. Treat the schema as an API. Adding a column is safe. Renaming or removing a column, or changing its type, needs the target owner's agreement and a coordinated release.
5. Add the model to the glossary (§9), with the target system and its fixed field names.
6. For table functions, delta feeds, demo rows and reverse ETL, see [references/presentation-contracts.md](references/presentation-contracts.md).

### Add reporting for people (L3R)

Create `l3r_<audience>` (management, a business unit's team, a regulator) with thin views over L2. Re-expose the dimensions the report needs, so the BI model connects to a single dataset. Apply the report's scope here (`latest_fl = 1`, the last N years). Add a `fct_last_refresh` heartbeat, and add the models to the glossary (§9). See [references/presentation-contracts.md](references/presentation-contracts.md).

### Review a model or a pull request

Work through [references/review-checklist.md](references/review-checklist.md). Report each finding with its severity, `file:line`, a concrete failure scenario and the fix.

### Bootstrap a new repository

1. Copy [assets/templates/](assets/templates/) into the new repo, including the dotfiles. It contains a compiling example from declaration to L3, plus `.sqlfluff`, CI and a CLAUDE.md skeleton.
2. Rename `CLAUDE.template.md` to `CLAUDE.md`.
3. Replace the placeholders: `your-gcp-project-id`, the `erp` and `crm` sources, the `sales` business unit, the `webapp` target and the `sales` audience.
4. Run `npm install --save-exact @dataform/core`, which pins the current core version in `package.json`.
5. Run `dataform compile`.
6. Fill in `docs/glossary.md` for the new project, and replace the example rows.

For tooling and operations, see [references/tooling-and-ops.md](references/tooling-and-ops.md).

## Choosing a materialization

| Situation | Choice |
| --- | --- |
| L1 over an external table (GCS Parquet/CSV, BigLake) that several models read | `table` |
| L1 over a small native table, or a light cast-only model | `view` |
| A source that ships only the current state, when you need history | `incremental`, append-only (no `uniqueKey`) |
| Current state upserted from a feed | `incremental` with a top-level `uniqueKey` (merge) |
| L2 model that is cheap and has few readers | `view` |
| L2 model with heavy window functions or wide joins, with many readers, or one BigQuery can't plan as a view | `table` |
| L3P model (a program reads it) | `table`, partitioned and clustered on the target's filters |
| L3R model (people read it through BI) | `view` |
| Parameterized access, where the target program passes filters | `type: "operations"`, `hasOutput: true`, `create or replace table function ${self()}(...)` |

## Hard-won rules

- Prove a join with a whole-table reconciliation, not one example. A fix that looks right for one entity can be wrong for most of the table.
- `concat()` returns NULL if any argument is NULL. Coalesce every part of a composite key before hashing, or the key turns NULL and the row vanishes from joins.
- Keys and sentinel values must be deterministic. Never use `current_date()` or `current_timestamp()` as the fallback inside a hash, or as a sentinel value.
- Watch for attributes repeated at a lower grain. When a company-level value repeats on every branch row, comment it and deduplicate before you `sum` or `count`.
- Learn what a source field means from the data, not from its name. A column that looks like a departure date can be a cancellation date, and two feeds of one system can be a day apart. If the data doesn't settle it, ask. Write each finding into CLAUDE.md or the glossary.
- A `full outer join` followed by a `where` on one side's columns, or by an inner join, quietly becomes a left or inner join. Filter in the import CTEs instead.
- An "as of" join against event dates for cumulative figures needs `event_dt <= snapshot_dt`, not `=`.
- Relative calendar flags (`cy_fl`, `ytd_fl`, `mr12_fl`) in a `table` freeze at build time. Rebuild the table daily, or compute the flags in a view.
- Don't run a repository-wide formatter such as `dataform format` on a codebase with a different house style: it rewrites every file. Match the neighbouring files by hand, and lint the changed files with sqlfluff.
- Keep hardcoded ids (test customers, excluded companies) in `includes/constants.js` with a comment, not as literals scattered across models.
- The newest periods of accounting data can be preliminary until the books close. A mismatch confined to the latest one or two periods is often not a bug.

## Reference files

| File | Read it when |
| --- | --- |
| [references/layers.md](references/layers.md) | Deciding where logic belongs; adding a source, business unit, target or audience |
| [references/naming.md](references/naming.md) | Naming a schema, table, column, CTE or tag |
| [references/keys-and-sentinels.md](references/keys-and-sentinels.md) | Building keys, joining dimensions, adding any placeholder (`na` row, default member, catch-all, numeric marker) |
| [references/modeling-patterns.md](references/modeling-patterns.md) | Dimensions, facts, bridges, KPIs, snapshot history, validity windows, rankings, hierarchies, JS-generated SQL |
| [references/presentation-contracts.md](references/presentation-contracts.md) | Anything in L3P (machine to machine) or L3R (people) |
| [references/quality-and-testing.md](references/quality-and-testing.md) | Assertions, verification queries, reconciliation, refactor safety |
| [references/tooling-and-ops.md](references/tooling-and-ops.md) | CLI, sqlfluff, CI, service accounts and IAM, scheduling, documentation |
| [references/review-checklist.md](references/review-checklist.md) | Reviewing a model or a pull request |
| [references/glossary.md](references/glossary.md) | Reading or updating `docs/glossary.md`: its structure, which change updates which section, the pre-commit check |
| [assets/templates/](assets/templates/) | Bootstrapping a repo, or starting a new model |
