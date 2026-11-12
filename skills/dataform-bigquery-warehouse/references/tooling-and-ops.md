# Tooling and operations

## Project files

`workflow_settings.yaml`:

```yaml
defaultProject: your-gcp-project-id
defaultLocation: EU
defaultDataset: dataform
defaultAssertionDataset: dataform_assertions
```

Pin `@dataform/core` in `package.json` to an exact version, not a range: `npm install --save-exact @dataform/core` does that for whatever version is current. Upgrade on purpose and compile before merging. Assertion packages (for example `dataform-assertions`) are optional; the built-in assertions plus custom assertion models cover most needs.

## CLI

```bash
dataform compile                                     # validates SQLX, JS and the dependency graph; no credentials needed
dataform compile --json > compiled.json              # compiled SQL of every action, for diffs
dataform run --dry-run --actions fct_invoice         # BigQuery validates the SQL, nothing is written
dataform run --actions fct_invoice --include-deps    # one model plus everything upstream
dataform run --actions dim_customer --include-dependents
dataform run --tags l3p_webapp --include-deps        # everything one target system needs
dataform run --full-refresh --actions daily_snapshot_updates
dataform run --schema-suffix dev                     # writes to <schema>_dev for side-by-side comparison
```

When two schemas contain a model with the same name, pass the qualified name (`schema.name`) to `--actions`.

## Style and linting

The house style: lowercase keywords and functions, leading commas, 2-space indent, explicit `as` for tables and columns, aligned column aliases, `left outer join`, and no blank lines inside a statement except between CTEs.

sqlfluff with the placeholder templater lints SQLX directly. Its regex removes the `config {}` and `js {}` blocks and replaces each `${...}` expression with a placeholder:

```ini
[sqlfluff]
templater = placeholder
dialect = bigquery

[sqlfluff:templater:placeholder]
param_regex = (?s)\${\s*(?P<param_name>[\w_]+)(?P<rec>(?:[^{}]+|{(?&rec)})*+)}|(?P<param_name>config|js|pre_operations|post_operations)\s*{(?&rec)}
ref = ref_table_placeholder
self = self_table_placeholder
when =
config =
js =
pre_operations =
```

The full file, with the house-style rules, is in `assets/templates/.sqlfluff`. It excludes LT01 (spacing): sqlfluff checks alias alignment on the templated SQL, where every `${...}` call becomes one short placeholder, so select lists that call the keys helper can never pass. Align aliases by hand. If an identifier inside `${...}` must expand to valid SQL (a JS-generated column list, for example), add a placeholder value for it: `cumulativeSum = 0 as placeholder_col`.

- Lint the changed files in CI, and fix legacy files when you touch them.
- Don't run `dataform format`, or any formatter, across a repository whose style differs from the formatter's. It rewrites every file (keyword case, indentation) and buries the real change in a huge diff. It has also reformatted the whole project when given a single file.
- `.editorconfig`: 2 spaces, LF line endings, UTF-8, final newline.

## CI

The cheapest useful check is compiling on every pull request, which needs no credentials. See `assets/templates/.github/workflows/dataform-compile.yml`, which also lints the changed SQLX files.

On GCP, the Dataform API can also compile a commit (`projects.locations.repositories.compilationResults.create`). Three traps, all seen in production:

- The request body needs a source, e.g. `{"gitCommitish": "$COMMIT_SHA"}`. An empty body `{}` is rejected with HTTP 400 "missing field".
- A rejected request returns an `error` object and no `compilationErrors`, so a check that tests only `.compilationErrors == null` passes and reports success without compiling anything. Check the HTTP status and that the response has a `name` before you look at `compilationErrors`.
- Don't run the step with `bash -x`. Tracing prints the `Authorization: Bearer` access token into the build log.

The build's service account needs `dataform.compilationResults.create`; the smallest predefined role that includes it is `roles/dataform.codeViewer`. Make the check fail once on purpose (a bad ref, for example) to prove it can fail.

## Running in GCP

- Run workflows as a custom service account. The default Dataform service account is no longer supported for workflow execution. Grant the custom account:
  - **BigQuery Data Editor**, restricted with IAM conditions to datasets whose names start with `l1_`, `l2_`, `l3p_`, `l3r_` and `dataform_assertions`. Use condition type "Name", operator "Starts with", value `projects/<project>/datasets/l1_`.
  - **BigQuery Data Viewer** on datasets starting with `declaration_`, so raw data stays read-only.
  - **BigQuery Job User**, **Logs Writer**, **Monitoring Metric Writer**, and **Storage Object Viewer** (for external tables on GCS).
- Give the Dataform service agent, `service-<project-number>@gcp-sa-dataform.iam.gserviceaccount.com` (with the numeric project number), the **Service Account Token Creator** role on the custom account, so it can impersonate it.
- Select the custom account in the repository settings and in every workflow configuration, then test-run each configuration.
- The layer prefixes are what make those IAM conditions possible. A dataset outside the naming scheme needs a grant of its own.

## Scheduling

- One release configuration compiles the main branch, and workflow configurations run it.
- Create one workflow per target system or per cadence: `--tags l3p_<target>` with dependencies included, a nightly full run, an intraday run for fast sources.
- Align the schedules with the loaders, so that no model runs before its sources land. When two sources that land at different times are joined, cut both at a common horizon in SQL (section 6 of modeling-patterns.md).
- Monitor pipeline runs as facts in `l2_monitoring`, plus a heartbeat per L3R schema (presentation-contracts.md).

## Documentation

- Keep a `CLAUDE.md` at the repo root (template in `assets/templates/CLAUDE.template.md`) covering the layers, the map of business units, targets and audiences, the names target systems impose, key design decisions, source semantics, the glossary, the commands, and any do-not-touch areas. Keep it current: it's what new engineers and agents read first.
- Keep `docs/glossary.md` as the one glossary of the repository, updated in the same change as the code and checked before every commit (glossary.md). The plugin's commit hook enforces that check for Claude's commits.
- Keep `docs/data-dictionary.md` for every L3P/L3R output model and column, and `docs/manifest.md` for every model and its direct lineage. Review both against the staged diff before every commit, and update them in the same change when their contents are affected (glossary.md).
- Use `docs/<business_unit>/` for calculation references: the lineage, the scope, the rules with worked examples, and a section on differences between the spec and the SQL. Write one whenever a model implements a business rule owned by someone outside the team (commissions, fees, payroll cost composition).
- A model's header comment carries its grain and the reasons behind it. Gold-layer models document table purpose and grain with `description:` and column metadata with `columns`; use catalog descriptions for L2 models when useful.
- Keep work-in-progress code managed by hand outside `definitions/`, so it never compiles, and mark it do-not-modify in CLAUDE.md.
