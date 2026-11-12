# Presentation (L3P, machine to machine) and reporting (L3R, for people)

## Which layer?

The reader decides: a program reads L3P, and a person reads L3R.

| | L3P: machine to machine | L3R: for people |
| --- | --- | --- |
| Reader | A program: an app backend, an API, a CRM or ERP import, a reverse-ETL or export job, another team's pipeline | A person, through a dashboard, a BI report, a connected spreadsheet or an ad-hoc analysis |
| Schema | `l3p_<target>`, one per target system | `l3r_<audience>`, one per audience |
| Contract | Strict: the target dictates names, types and constraints | Loose: the report owns the shape |
| Changes | Coordinated like an API change | Released together with the report |
| Typical model | `table`, current state, tagged for the target's sync | Thin `view` over L2 |
| Sentinels | `na` rows filtered out | `na` rows shown as "Not Assigned" |
| Monitoring | The sync job's own monitoring | A `fct_last_refresh` heartbeat |

Edge cases:

- An app that shows charts or tables to its users belongs in L3P. Its backend reads the table, and the app decides what people see.
- A scheduled file export to a partner or an authority belongs in L3P, because the receiving system parses it.
- A BI semantic model (a Power BI dataset, a Looker model) belongs in L3R. The BI tool is software, but everything it builds is for people.
- When a person and a program read the same data, give each its own model, one in L3P and one in L3R, because their contracts change for different reasons.

## L3P: one schema per target system

L3P holds exactly what one target system reads: a web app's backend, a member portal's API, the CRM import, a reverse-ETL job that writes back into a source system, an integration that fills an intranet list, or an export to a partner. The target owns the contract, and the warehouse adapts to it.

Rules:

1. **One schema per target system**, named `l3p_<target>`. Never let two targets share a table, because their contracts drift independently.
2. **The target's names win.** Alias to the target's field names and types in the final select only. List the fixed names per schema in CLAUDE.md under "do not rename". Everything else in the model follows the warehouse conventions.
3. **Treat the schema as an API.** Adding a column is safe. Renaming or removing a column, or changing its type or meaning, needs the target owner's agreement and a coordinated release. Record the target's owner in CLAUDE.md.
4. **Filter out sentinels** and other warehouse artifacts (`where customer_id != ${keys.unknown()}`, `customer_cd != 'na'`). Scoped default members, such as a company's "Default" sector, hold real amounts and stay in (keys-and-sentinels.md).
5. **Cast to the target's types.** Use `safe_cast(customer_cd as int64) as id` when the app uses integer ids and `cast(x as timestamp)` when the API expects timestamps, and lowercase emails and URLs if the target compares them.
6. **Mirror the target's constraints as assertions.** Copy NOT NULL constraints into `nonNull`, unique constraints into `uniqueKey`, and CHECK constraints into `rowConditions`, with each constraint's name in a comment. A bad row then fails the run in Dataform, before the sync job writes half a batch.

   ```sqlx
   config {
     type: "table",
     schema: "l3p_portal",
     name: "members",
     tags: ["l3p_portal"],
     assertions: {
       uniqueKey: ["id"],
       nonNull: ["id"],
       rowConditions: [
         // members_check1: companies have a company name
         "company_name is not null or type not in ('partnership', 'corporation')",
         // members_check2: persons have a first name
         "first_name is not null or type in ('partnership', 'corporation')"
       ]
     }
   }
   ```

7. **Tag** every model `l3p_<target>`, and schedule the target with `--tags l3p_<target> --include-deps`.
8. **Materialize as a `table`.** Programs read whole tables, often more than once, and a view re-runs the whole L2 stack on every read. Partition and cluster on what the target filters by:

   ```js
   bigquery: {
     partitionBy: "RANGE_BUCKET(Year, GENERATE_ARRAY(2010, 2100, 1))",
     clusterBy: ["Month", "CompanyId"]
   }
   ```

9. **State whether a table is current state or history** in its header comment, for example: "one row per source/company/branch, replaced each run; the history lives in l2_monitoring.fct_job_run".
10. **Delta feeds.** If the target wants only changed rows, filter on a reliable update timestamp with a margin wider than the schedule (`where last_update_dt >= current_date() - 5` for a daily job), and let the target upsert by key. Document the margin.
11. **Demo and test records** the app needs (a demo company for screenshots, a test tenant) are appended in L3P only, with ids outside the real range and a comment. Never put them in L2.

### Parameterized access: table functions

When the target program has to pass filters (an office, a list of departments), publish a table-valued function:

```sqlx
config {
  type: "operations",
  hasOutput: true,
  schema: "l3p_intranet",
  name: "open_items_tvf",
  tags: ["l3p_intranet"]
}

create or replace table function ${self()}(p_department_cd array<string>, p_office_cd string) as (
  select ...
  from ${ref({schema: 'l2_finance', name: 'fct_open_item'})}
  where
    department_cd in unnest(p_department_cd)
    and office_cd = p_office_cd
)
```

`hasOutput: true` makes the function `ref`-able, which puts it in the dependency graph.

### Reverse ETL

A target that writes warehouse data back into an operational system (absences into a calendar, a device inventory into an asset tool) gets its own `l3p_<sync_target>` schema. The table is the sync job's complete input: one row per target record, with the target's field names and nothing left for the job to compute. The sync job itself lives outside Dataform.

## L3R: one schema per audience

L3R is what people read, through the BI tools (Power BI, Looker Studio, Tableau) that connect to it. Create one schema per audience: management, a business unit's team, a regulator.

Rules:

1. **Thin views.** Most L3R models are a `select *` over an L2 model, with at most a filter or a few renames. Logic belongs in L2, where other reports and targets can reuse it.
2. **Re-expose the dimensions** the report needs, so the BI model connects to a single dataset. For example, `l3r_finance.dim_customer` is a view over `l2_masterdata.dim_customer`.
3. **Apply the report's scope here:** `where latest_fl = 1`, `where extract(year from date_dt) >= extract(year from current_date()) - 10`.
4. **Make it readable.** Use clear English column names, `_long_ds` labels for slicers, and status codes with a sort number. The report can change these freely, because no program depends on them.
5. **Report-only shapes are fine in L3R**: a time-selection helper that lists "last 7 days / same period last year" per date, or a hierarchy flattened for one report.
6. **Sentinels:** keep the `na` row so the report shows a "Not Assigned" bucket. When a report dimension is narrower than its facts (only ordinary members, say), add a scope sentinel so the out-of-scope facts appear as "Not Assigned" (keys-and-sentinels.md).
7. **Refresh heartbeat.** Each L3R schema gets a `fct_last_refresh`, so people can see how fresh the data is:

   ```sqlx
   config {
     type: "incremental",
     schema: "l3r_finance",
     name: "fct_last_refresh"
   }

   -- Refresh heartbeat. It references every model of this schema, so it runs only after all of
   -- them succeeded, and it appends one row per run. Dashboards show max(refresh_dt) as "data as of".
   -- Add a CTE here for every model added to l3r_finance.
   with dim_customer as (
     select * from ${ref({schema: 'l3r_finance', name: 'dim_customer'})}
   )

   , fct_invoice as (
     select * from ${ref({schema: 'l3r_finance', name: 'fct_invoice'})}
   )

   select
     current_date()        as refresh_dt
     , current_timestamp() as refresh_time_dt
   ```

   The CTEs are never selected from, so BigQuery doesn't scan those tables. The `ref`s exist only to create the dependencies.

## Checklist for a new L3 schema

- [ ] The reader is clear: a program means L3P, a person means L3R.
- [ ] The schema `l3p_<target>` or `l3r_<audience>` exists, and CLAUDE.md has an entry for it (target and owner, or audience; fixed field names for L3P).
- [ ] L3P: every model is tagged, a schedule runs the tag with `--include-deps`, and the target's owner knows how changes will be announced.
- [ ] Sentinels are filtered out (L3P) or deliberately kept (L3R); default members are kept in both.
- [ ] L3P: the target's constraints are mirrored as assertions, and column types match the target's schema.
- [ ] L3P: the header says whether the table is current state or history.
- [ ] L3R: a heartbeat is in place. L3P: the sync job is monitored.
