# Quality and testing

## Assertions in config

```js
assertions: {
  uniqueKey: ["invoice_id"],            // the grain; composite keys allowed: ["company_id", "year_nr"]
  nonNull: ["customer_id", "document_dt"],
  rowConditions: [
    "gross_amount_vl = net_amount_vl + vat_amount_vl",
    "exit_dt is null or exit_dt >= entry_dt"
  ]
}
```

- Put `uniqueKey` on every dimension, bridge and fact whose grain is a key. It's the cheapest fan-out detector there is.
- Put `nonNull` on keys and on every column a consumer requires.
- Use `rowConditions` for invariants within a row. In L3P, they hold copies of the target system's CHECK constraints.
- If you disable an assertion temporarily, comment it out with the reason and a date; don't delete it.
- By default, an assertion that fails doesn't stop the models downstream of it. If a model must not refresh while an upstream assertion fails (typically an L3P table a program reads), make it depend on that assertion. The Dataform documentation lists the dependency options.

## Custom assertion models

For an invariant that spans rows, write a `type: "assertion"` model that returns the offending rows. Zero rows means the assertion passes.

```sqlx
config {
  type: "assertion",
  schema: "dataform_assertions",
  name: "assert_bridge_weights_sum_to_100",
  tags: ["finance"]
}

-- bridge.percent splits a sector's revenue across its sites, so it must sum to ~100 per
-- sector and year. Duplicated bridge rows (a sum of 200) silently double the revenue of every
-- affected site and corrupt everything ranked on it. Fix at the source mapping table.
select
  sector_id
  , year_nr
  , count(*)     as site_qt
  , sum(percent) as percent_sum_vl
from ${ref({schema: 'l2_finance', name: 'rel_sector_site'})}
group by sector_id, year_nr
having sum(percent) not between 95 and 105
```

Custom assertions worth having:

- weights summing to 100;
- the share of facts mapped to the sentinel staying below a threshold;
- exactly one scoped default member per parent;
- no overlapping validity windows per key;
- child totals equal to parent totals;
- every entity a consumer sees present in the conformed dimension.

The header comment says why the invariant matters, what breaks downstream when it fails, and where to fix it.

## Verification before "done"

Compiling only proves the SQL is well-formed. Before calling a change done, run the queries that would catch it being wrong. With read access, run them yourself (`bq query`, the BigQuery console, an MCP tool); without it, hand them to the user.

**Grain:**

```sql
select key_id, count(*) as row_qt
from model
group by key_id
having count(*) > 1
```

**Fan-out per join:** the row count of the driving CTE must be the same before and after each join, unless the join is meant to multiply rows.

**Unassigned share:**

```sql
-- in SQLX use ${keys.unknown()}; in the console, the literal of your strategy:
-- to_hex(md5('na')), -1 or 'na'
select countif(customer_id = to_hex(md5('na'))) / count(*) as unassigned_pc
from l2_sales.fct_invoice
```

**Totals against the source:** sum the main measure per month in the model and in L1. The difference must be zero or explained by documented filters and exclusions.

**Child-to-parent reconciliation**, over the whole table, not one example:

```sql
with child as (
  select parent_id, sum(revenue_vl) as revenue_vl
  from fct_detail
  group by parent_id
)

select count(*) as mismatch_qt
from fct_parent as parent
full outer join child using (parent_id)
where abs(coalesce(parent.revenue_vl, 0) - coalesce(child.revenue_vl, 0)) > 0.01
```

**Before and after a change:** the row count, the distinct key count and the main totals should be unchanged, unless the change was meant to change them. For a model whose output must not change at all:

```sql
(select * from new_version except distinct select * from old_version)
union all
(select * from old_version except distinct select * from new_version)
```

Build the new version under a separate schema (`dataform run --schema-suffix dev`) to compare side by side. `except distinct` doesn't work on ARRAY, STRUCT or JSON columns, so compare those with `to_json_string`.

**Mechanical refactors** (JS templating, reshuffled CTEs): compare the compiled SQL from `dataform compile --json` before and after.

**Dry run:** `dataform run --dry-run --actions <model>` has BigQuery validate the generated SQL without writing anything.

**One entity end to end:** pick a known record and follow it from L1 to L3. This is good at catching semantic errors and useless for proving a join correct for all rows, so do it in addition to the whole-table checks, never instead of them.

## Source semantics

Most bad numbers come from a field that means something other than its name suggests.

- Check a field's meaning against the data. Is a "pick-down date" a departure or a cancellation? If it is never after the revenue date and is NULL for active bookings, it's a cancellation.
- When joining two feeds of the same system, measure the match rate at date offsets of -1, 0 and +1 days. A one-day convention between files stands out clearly, for example 43% at offset 0 against 98% at offset +1.
- Record findings where the next person will look: CLAUDE.md, the model header, or a page in docs/.
- The newest periods of accounting data can be preliminary (accruals, books not yet closed). Mismatches confined to the latest one or two periods are often not bugs; label them as preliminary.
- Labels aren't identifiers, and two codes can share a display label. Join and filter on codes.

## Unit tests

Dataform supports unit tests (`dataform test`, or `dataform run --run-tests`) that run a model against fixed inputs and compare it with an expected output. They pay off for logic that amounts to a table of rules: classification rules, banding, status logic. The Dataform documentation describes the test syntax.
