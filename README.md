# Dataform BigQuery Data Warehouse Skill for Claude Code

**A Claude Code skill (Agent Skill and Claude Code plugin) that teaches AI coding agents to design, build and review a layered data warehouse on Google BigQuery with Google Dataform (SQLX).**

It packages one opinionated way to run a Dataform repository, tested in production: the layer architecture, naming conventions, surrogate keys, dimensional modeling patterns, data-quality assertions, verification, and a glossary that stays current. It was distilled from a warehouse of about 600 Dataform models that reads 25+ source systems and serves web apps, a CRM, BI dashboards and reverse-ETL jobs.

| | |
| --- | --- |
| **What** | An Agent Skill (`SKILL.md` plus references, a hook script and templates), packaged as a Claude Code plugin |
| **For** | Analytics engineers and data engineers who use Google Dataform and BigQuery, and the AI agents that help them |
| **Works with** | Claude Code, as a plugin or a plain skill, and any tool that reads the Agent Skills format |
| **Covers** | Layered warehouse architecture, SQLX naming conventions, source `_id` identifiers and hashed `_sk` surrogate keys (MD5, FARM_FINGERPRINT or SHA-256), measures named with `_qty`/`_cnt`/`_amt`/`_pct`/`_num`, sentinel rows, dimensional modeling (dimensions, facts, bridges, KPIs), snapshot history, contracts for apps and reports, assertions, sqlfluff, CI, IAM |
| **License** | MIT |

## The architecture in one picture

```text
raw tables
└─ declaration_<source>      read-only pointers
   └─ l1_<source>            one model per raw table: casts, surrogate keys
      └─ l2_<business_unit>  business logic, one schema per business unit of the company
         ├─ l3p_<target>     machine to machine: apps, APIs, CRM, sync and export jobs
         └─ l3r_<audience>   for people: reports and dashboards
```

In medallion-architecture terms, declarations and L1 are roughly bronze, L2 is silver, and L3 is gold. The gold layer is split by reader: L3P for programs and L3R for people.

## What Claude does with it

- Puts new logic in the right layer and schema, and keeps the dependency graph acyclic. Business logic goes to the schema of the business unit that owns it. A table goes to L3P when a program reads it, and to L3R when people read it.
- Names schemas, tables and columns by a strict convention (`dim_`/`fct_`/`rel_`/`kpi_`, source identifiers `_id`, surrogate keys `_sk`, codes `_cd`, dates `_dt`, and measures `_qty`/`_cnt`/`_amt`/`_pct`).
- Writes every model in the same shape: import CTEs, a grain comment, `final`.
- Chooses a hash strategy that fits the system: MD5 when keys leave BigQuery, FARM_FINGERPRINT (INT64) for BigQuery and BI import models, SHA-256 for strict policies. In L2, source identifiers end in `_id` and hashed warehouse keys end in `_sk`. It applies the strategy through one `includes/keys.js` helper, and keeps facts complete with "not assigned" sentinel rows. It tells the different kinds of sentinel apart: the global `na` row, scoped default members such as a sector `0` "Default", catch-all categories, numeric markers.
- Applies known-good patterns: cross-system bridges that keep their misses, validity windows, change capture of snapshot feeds, reconstructed history, peer-group banding without cycles, weighted allocation.
- Builds machine-to-machine contracts (names and types the target system dictates, its constraints mirrored as assertions, table functions) and reports for people (thin scoped views, refresh heartbeats).
- Asks before guessing. When the repository and the data don't settle a question (which unit owns a model, what a field means, a business rule, a target's field names), Claude asks with a recommendation instead of inventing an answer, and keeps working on everything else in the meantime.
- Keeps the repository glossary (`docs/glossary.md`), Gold-layer data dictionary (`docs/data-dictionary.md`) and warehouse manifest (`docs/manifest.md`) current. Claude reviews all three before every commit and updates the docs in the same change whenever their contents are affected. A commit hook blocks Claude's model-changing commits without the glossary, unless the message says `Glossary: unchanged`.
- Scores a warehouse or a single model against Kimball's dimensional modeling. There are 16 weighted criteria (grain, conformed dimensions, surrogate keys, unknown members, fact types and additivity, SCDs, bridges and more), graded A to D. A read-only scanner computes the mechanical criteria and generates the bus matrix from the code.
- Verifies a change with whole-table reconciliation, not spot checks.
- Reviews models and pull requests against a checklist.
- Bootstraps a new repository from templates that compile out of the box.

If a repository already has conventions of its own, the skill tells Claude to follow them and to use the playbook only to fill gaps.

## Install

### As a Claude Code plugin

In a Claude Code session:

```text
/plugin marketplace add Ans02/dataform-bigquery-data-warehouse-skill
/plugin install dataform-bigquery-warehouse@dataform-bigquery-data-warehouse-skill
```

Or from a shell:

```bash
claude plugin marketplace add Ans02/dataform-bigquery-data-warehouse-skill
```

```bash
claude plugin install dataform-bigquery-warehouse@dataform-bigquery-data-warehouse-skill
```

Claude uses the skill automatically when a task matches it. You can also invoke it directly with `/dataform-bigquery-warehouse:dataform-bigquery-warehouse`.

### As a plain skill

```bash
git clone https://github.com/Ans02/dataform-bigquery-data-warehouse-skill.git
```

```bash
mkdir -p ~/.claude/skills && cp -r dataform-bigquery-data-warehouse-skill/skills/dataform-bigquery-warehouse ~/.claude/skills/
```

To scope it to one project, copy it to `<project>/.claude/skills/dataform-bigquery-warehouse/` instead. The skill is then invoked as `/dataform-bigquery-warehouse`.

A plain-skill install doesn't include the plugin's glossary commit hook. To get it, register the script in `~/.claude/settings.json`, or in a project's `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"$HOME/.claude/skills/dataform-bigquery-warehouse/scripts/glossary-gate.sh\""
          }
        ]
      }
    ]
  }
}
```

The skill folder follows the Agent Skills format, and its frontmatter uses only portable fields (`name`, `description`, `license`, `metadata`), so it can also be uploaded wherever Agent Skills are supported.

## Example prompts

- "Add the payroll system as a new source: three raw tables in `declaration_payroll`."
- "Create a customer KPI table with rolling-12-month and current-year status."
- "We need to expose open invoices to the web app. Build the L3P table."
- "Review `definitions/l2/sales/fct_invoice.sqlx` against the playbook."
- "Map CRM accounts to ERP customers; unmatched ones should stay visible."
- "Why does `uniqueKey` fail on `dim_site` since yesterday's change?"
- "Bootstrap a new Dataform repository for project `acme-dwh`."
- "Score our warehouse against Kimball and tell me the three changes that would raise the grade most."

## Contents

```text
llms.txt                    summary and file index for LLMs and AI crawlers
.claude-plugin/
  marketplace.json          this repo as a one-plugin marketplace
  plugin.json
hooks/
  hooks.json                glossary gate on Claude's git commit (PreToolUse, Bash)
skills/dataform-bigquery-warehouse/
  SKILL.md                  architecture, conventions, workflows, glossary rule, hard-won rules
  scripts/
    glossary-gate.sh        the commit check (bash and git only)
    kimball_scan.py         read-only Kimball scanner and bus-matrix generator (Python 3, standard library)
  references/
    glossary.md             the repository glossary: structure, what to update when, pre-commit check
    kimball-scorecard.md    Kimball scoring: 16 repository and 15 model criteria, weights, grades A–D
    layers.md               what each layer may and may not do
    naming.md               schemas, tables, columns, CTEs, tags
    keys-and-sentinels.md   choosing a key strategy, the keys helper, na/nd, kinds of sentinel
    modeling-patterns.md    17 patterns: dims, facts, bridges, snapshots, history, rankings, ...
    presentation-contracts.md  L3P (machine to machine) and L3R (people)
    quality-and-testing.md  assertions, verification queries, reconciliation
    tooling-and-ops.md      CLI, sqlfluff, CI, IAM, scheduling, docs
    review-checklist.md
  assets/templates/         a small Dataform project that compiles: declaration → L1 → L2 → L3,
                            docs/glossary.md, data-dictionary.md, manifest.md, .sqlfluff,
                            CI workflow, CLAUDE.md skeleton
```

## Adapting it

The conventions are opinions. Fork the repository and edit `references/naming.md` and the "Conventions at a glance" section of `SKILL.md` to match your house style. Keep the reasoning, which is the part that transfers.

Validate after editing:

```bash
claude plugin validate .
```

## FAQ

### What is a Claude Code skill?

A folder with a `SKILL.md` file of instructions, plus optional reference files, scripts and templates. Claude Code loads a skill automatically when a task matches its description, and reads the reference files only when it needs them. This repository is also a Claude Code plugin and a one-plugin marketplace, so it installs with two commands.

### Does it work with an existing Dataform repository?

Yes. The skill tells Claude to read the repository's own conventions (CLAUDE.md, neighbouring models) first and to follow them. The playbook fills gaps, guides reviews, and bootstraps new repositories.

### Does it work with dbt?

Not directly. The commands, configs and templates are specific to Google Dataform (SQLX, `ref()`, built-in assertions, incremental tables). The modeling ideas carry over to dbt and other SQL-based tools: the layers, the keys, the sentinel rows, the bridges and the verification queries.

### Do I have to use MD5 surrogate keys?

No. Every warehouse surrogate key ends in `_sk` and uses a hash strategy chosen for the system, recorded once in `includes/keys.js`:

- `md5_hex` when keys leave BigQuery (apps, reverse ETL, other databases), because every language can compute MD5.
- `farm_fingerprint` (INT64) when keys stay in BigQuery and its BI tool, because it gives the smallest, fastest joins and compresses best in Power BI.
- `sha256_hex` when a policy bans MD5.

In L2, natural and source identifiers use `_id` (for example `customer_id`); generated warehouse surrogate keys use `_sk` (for example `customer_sk`).

Models call `keys.surrogate(...)` and `keys.unknown()`, so no model hardcodes a hash function. A repository already using hashed keys keeps its strategy, because changing it changes every key downstream.

### Which BigQuery features does it use?

Standard GoogleSQL: `union all strict corresponding`, `qualify`, `md5` / `sha256` / `farm_fingerprint`, `generate_date_array`, `except distinct`, table-valued functions, and partitioning and clustering.

### What does the glossary commit hook do?

Every warehouse repository keeps a glossary at `docs/glossary.md`: business terms, codes, measures and every model. When Claude runs `git commit` and the commit changes files under `definitions/` or `includes/` without the glossary, the hook blocks the commit and tells Claude to update the glossary first. A commit that genuinely doesn't affect the glossary goes through with the trailer `Glossary: unchanged`. The hook needs only bash and git, and it does nothing in repositories without a glossary.

The skill also maintains `docs/data-dictionary.md` for Gold-layer outputs and `docs/manifest.md` for the model inventory and direct lineage. Claude checks both before every commit and updates them in the same change when the staged changes affect their contents. The hook currently enforces the glossary check only.

### How does the Kimball score work?

Each criterion scores 0, 1 or 2 and has a weight: 3 for critical, 2 for important, 1 for good practice. The score is the weighted percentage of the maximum, graded A (90 or more), B (75–89), C (60–74) or D (below 60). A critical criterion at 0 (an undeclared grain, unenforced grain, non-conformed dimensions, or null foreign keys) caps the grade at C. The script `kimball_scan.py` computes the mechanical criteria and the bus matrix, and Claude scores the rest by sampling models and citing file and line. The result lists the improvements ranked by the points they would add. Run the scanner on its own with:

```bash
python3 skills/dataform-bigquery-warehouse/scripts/kimball_scan.py path/to/your/dataform/repo
```

### Does it contain company data?

No. Every example uses generic names (`erp`, `crm`, `webapp`, `sales`).

## License

[MIT](LICENSE)
