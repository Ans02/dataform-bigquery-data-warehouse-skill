# Layers

## Repository layout

```text
definitions/
  declarations/<source>/<raw_table>.sqlx
  l1/<source>/<raw_table>.sqlx
  l2/<business_unit>/<model>.sqlx      plus l2/masterdata, l2/relationship, l2/monitoring
  l3p/<target>/<model>.sqlx            machine-to-machine targets
  l3r/<audience>/<model>.sqlx          human audiences
includes/                 shared JS (constants, helpers), exposed as globals named after the file
docs/glossary.md          the repository glossary, updated with every change (glossary.md)
docs/<business_unit>/     calculation references, source-system manuals, mapping specs
workflow_settings.yaml    default project, location, dataset, assertion dataset
package.json              @dataform/core, pinned to an exact version
.sqlfluff  .editorconfig  CLAUDE.md
```

The folder is the schema suffix and the file name is the model name. Every dataset carries its layer as a prefix (`declaration_`, `l1_`, `l2_`, `l3p_`, `l3r_`). That gives you three things:

- The BigQuery explorer groups the datasets by layer.
- IAM conditions can grant access by prefix ("dataset name starts with `l2_`"); see tooling-and-ops.md.
- A reviewer can spot a layer violation from the `ref` alone.

## Declarations

```sqlx
config {
  type: "declaration",
  schema: "declaration_erp",
  name: "customer_pq"
}
```

- A declaration sets only `type`, `schema` and `name`. The name is the physical table name, which often carries the loader's format suffix (`_pq`, `_csv`); the file can have a friendlier name.
- Raw tables belong to the ELT jobs, and Dataform never writes them. Give the Dataform service account read-only access to `declaration_*`.
- Declare every raw table you read, even one that a single model uses, so the lineage is complete.

## L1: source-aligned

L1 makes each raw table safe and cheap to use, and adds nothing business-specific. A good L1 model is boring: a reviewer can check it against the source schema in a minute.

Allowed:

- choosing columns (keep everything plausibly useful, drop loader noise);
- casting types: `cast(x as timestamp)`, `parse_date('%Y%m%d', file_date)`;
- keying the primary key and every foreign key into `_id` columns, once, with the repository's key strategy, so that every L2 model agrees on them (keys-and-sentinels.md);
- source-local cleanup: lowercasing emails, `nullif(x, '.')` for placeholder values, unnesting the source's own repeated fields;
- load metadata: `_FILE_NAME` of external tables, import timestamps;
- documented cut-offs: `where fiscal_year > 2022 -- earlier extracts are unreliable`;
- change capture of snapshot feeds (`_src` → `_updates` → view; see modeling-patterns.md).

Not allowed:

- joins to another source. The one exception worth allowing is a manually maintained override table for the same source, documented in the header.
- business rules, classifications, KPIs.
- renaming columns to English. The rename happens once, in L2, so L1 stays a transparent mirror of the source.

Materialization: use a `table` when the raw table is external, because reading Parquet or CSV from GCS is slow and billed on every query. Use a `view` for small native tables, and `incremental` for history built from snapshots.

Multi-entity sources: when the same ERP schema exists once per legal entity (separate databases with overlapping ids), keep one L1 model per entity (`invoice_entity_a`, `invoice_entity_b`). Union them in L2 with namespaced keys (modeling-patterns.md).

## L2: one schema per business unit

L2 mirrors the organization, not the source systems: each business unit of the company gets one schema. Examples are `l2_sales`, `l2_finance`, `l2_hr`, `l2_marketing` and `l2_customer_service`. In a services company that means one schema per service line (`l2_tax_advisory`, `l2_payroll_services`), plus the internal units (`l2_administration`). A business unit usually reads several sources, and a source usually feeds several units.

Why business units:

- **Ownership.** Every unit has people who know what its numbers mean. A model is owned, reviewed and explained by the unit that owns the process behind it.
- **Access.** BigQuery grants access per dataset, so a unit's analysts can get their own schema without seeing everybody else's.
- **Questions.** People ask "what did sales do last month", not "what does the ERP say", so they find the data where they expect it.

Rules:

- **The owning unit holds the model.** It lives in the schema of the business unit that owns the process behind it (invoicing → finance, payroll → hr), even when other units read it. Other units `ref` it; they never copy it.
- **Shared schemas** hold what belongs to no single unit:
  - `l2_masterdata` is the conformed hub every unit shares: company, site or branch, customer, address, geography, calendar, users and groups, value sets. Units join to it, and references point from the units toward masterdata, never back.
  - `l2_relationship` holds bridges between units or between their systems (`rel_sector_cost_center` linking finance sectors with hr cost centers). If only one model needs a mapping, a CTE inside that model is fine; name it like the model it would become (`l2_rel_pms_site`). Promote it once a second model needs it, because copies drift apart.
  - `l2_monitoring` holds pipeline runs, job durations and the last load per source as ordinary facts (`fct_job_run`), so apps and dashboards can show how fresh the data is.
- **Reorganizations happen.** Name a schema after what the unit does, not after its current department label, so the name survives a renamed department. When units merge or split, move models deliberately and update the map in CLAUDE.md. Never keep two copies of a model.
- **L2 → L2 references are fine** across units, as long as the graph stays acyclic. A cycle means a value sits on the wrong model: move the derived value downstream (see "Rankings and peer groups" in modeling-patterns.md).
- **Materialize a model as a `table`** when it runs heavy window functions or wide joins, when many models read it, or when a stack of nested views gets too complex for BigQuery to plan. Materializing one model in the middle of the stack usually fixes that last case.

## L3: who reads it decides the layer

| | L3P: machine to machine | L3R: for people |
| --- | --- | --- |
| Reader | A program: an app backend, an API, a CRM or ERP import, a reverse-ETL or export job, another team's pipeline | A person, through a dashboard, a BI report, a connected spreadsheet or an ad-hoc analysis |
| Schema | `l3p_<target>`, one per target system | `l3r_<audience>`, one per audience (management, a business unit's team, a regulator) |
| Contract | Strict: the target dictates names, types and constraints. Changes are coordinated like an API change | Loose: the report owns the shape and changes along with the report |
| Typical model | `table`, current state, tagged for the target's sync | Thin `view` over L2, scoped to the report |
| Sentinels | `na` rows filtered out | `na` rows shown as "Not Assigned" |

Edge cases:

- An app that shows charts or tables to its users belongs in L3P. Its backend reads the table, and the app decides what people see.
- A scheduled file export to a partner or an authority belongs in L3P: the receiving system parses it.
- A BI semantic model (a Power BI dataset, a Looker model) belongs in L3R. The BI tool is software, but everything it builds is for people and changes with the report.
- When a person and a program read the same data, give each its own model: one in L3P, one in L3R. Their contracts change for different reasons.

Details on both: presentation-contracts.md.

## Keep a map

CLAUDE.md should list every L2 schema with the business unit that owns it, every L3P schema with its target system and owner, and every L3R schema with its audience: one line each. It is the first thing a new engineer or an agent reads. It is also where you note that a mapping lives somewhere unexpected.
