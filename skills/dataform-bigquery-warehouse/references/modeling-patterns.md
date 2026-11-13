# Modeling patterns

These patterns recur across business units. Each one solved a real problem, and the reasoning behind each matters more than the SQL.

## Contents

1. Conformed dimension
2. Fact table
3. Multi-entity sources
4. Cross-system identity bridge
5. Validity-window mapping
6. Latest version of a record
7. Classification rollups
8. KPI tables with time windows
9. Change capture of snapshot feeds
10. Windowed full exports with deletions
11. Reconstructed history
12. Rankings and peer groups (avoiding cycles)
13. Weighted allocation
14. Reference data as code; value sets
15. Calendar dimension
16. Hierarchies for BI
17. JavaScript-generated SQL

## 1. Conformed dimension

Each business entity gets one model in `l2_masterdata`. Build it from the system of record and enrich it from other systems with `left outer join`s.

- Grain: one row per entity, plus the sentinel. Put `uniqueKey` on the key or on the business code.
- Each enrichment join may return at most one row per entity. If the other system can hold duplicates (several CRM accounts with the same customer number), deduplicate in the import CTE first (`qualify row_number() over (partition by number order by modified desc) = 1`) and comment it.
- Derive flags here, once (`active_fl` from the status columns), not in each consumer.
- Add `_long_ds` (`code - name`) for pickers and slicers.
- Flags such as "is a customer of service X" belong on the dimension when the source maintains them.

## 2. Fact table

- State the grain in the first comment line. Every column must depend on that grain.
- Foreign keys: left join to the dimension and wrap the key in `coalesce(..., ${keys.unknown()})`.
- Measures use `_amt`, `_qty` or `_cnt`. Keep signed amounts signed (credit notes negative) and add a flag (`credit_note_fl`) instead of filtering them out.
- When the document date and the business date differ, keep both, and comment which one reports use. A credit note, for example, can carry the date of the invoice it corrects as `date_dt`.
- Don't pre-aggregate in a `fct_` model. Aggregates are `kpi_` models.

## 3. Multi-entity sources

Two legal entities run the same ERP in separate databases. The schemas are identical and the ids overlap.

```sql
, invoices_entity_a as (
  select
    'entity_a'                                                       as source_company_ds
    , ${keys.composite("'entity_a'", "invoice.id")}                 as invoice_sk
    , invoice.id                                                     as invoice_id
    , coalesce(dim_customer.customer_sk, ${keys.unknown()})          as customer_sk
    , invoice.gross_amount                                           as gross_amt
  from l1_erp_invoice_entity_a as invoice
  left outer join l2_sales_dim_customer as dim_customer
    on invoice.customer_ref = dim_customer.customer_id
    and dim_customer.source_company_ds = 'entity_a'
)

, invoices_entity_b as (
  -- same shape, entity_b
)

, final as (
  select * from invoices_entity_a
  union all strict corresponding
  select * from invoices_entity_b
)
```

- Namespace the key and every lookup. Join dimensions on the source id **and** the discriminator.
- The parallel blocks are intentional. Keep them textually identical except for the entity, so a diff between them shows nothing but the entity name. With more than two or three entities, generate the blocks from a JS list (section 17).

## 4. Cross-system identity bridge

Two systems describe the same entity, and the only link is a code someone typed in: an ERP number on a CRM account, or the numeric part of a cost-center code. Make the match its own model, and keep the misses.

```sql
, matched as (
  select
    account.account_sk
    , dim_customer.customer_sk
  from l1_crm_account as account
  full outer join l2_masterdata_dim_customer as dim_customer
    on trim(account.erp_customer_number) = dim_customer.customer_num
)

, final as (
  select
    ${keys.composite("account_sk", "customer_sk")}       as crm_erp_customer_sk
    , coalesce(account_sk, ${keys.unknown()})             as account_sk
    , coalesce(customer_sk, ${keys.unknown()})            as customer_sk
    , case
      when account_sk is null then 'erp only'
      when customer_sk is null then 'crm only'
      else 'matched'
    end                                                   as match_status_cd
    , account_sk is not null and customer_sk is not null  as match_fl
  from matched
)
```

- Keep the unmatched rows on both sides, with `match_status_cd` and `match_fl`. Dropping them hides exactly the rows someone has to fix. QA reports filter on `match_fl = false`.
- Put filters in the import CTEs. A `where` on either side's columns after a full outer join, or an inner join added later, silently turns it into a one-sided join. Check that both "only" statuses still occur.
- A heuristic match (digits extracted with `regexp_replace(code, r'[^0-9]', '')`, then `safe_cast(... as int64)`) needs its own status and a QA query that lists its misses.
- Trivial matches inflate the match rate: a parent whose only member is its default member matches anything. Give them their own status (`single candidate`). See "Scoped default members" in keys-and-sentinels.md, which also covers default members on both sides of a bridge.
- When the match depends on time (a cost center valid in one fiscal year), add the period to the grain and to the key.
- A bridge that becomes important deserves a curated mapping table (kept in a spreadsheet or seed) that overrides the heuristic. Before switching to it, check the consumers of `match_fl = false`.

## 5. Validity-window mapping

A mapping changes over time: a channel account belonged to site A until March, then to site B. Store `valid_from_dt` and `valid_to_dt` in the bridge, join events inside the window, and fall back to the latest mapping:

```sql
-- in the bridge: open-ended windows get fixed far-past/far-future values so "between" always works
, coalesce(mapping.valid_from, date '0001-01-01') as valid_from_dt
, coalesce(mapping.valid_to, date '9999-12-31')   as valid_to_dt
, coalesce(mapping.valid_to, date '9999-12-31') = max(coalesce(mapping.valid_to, date '9999-12-31')) over (
  partition by mapping.channel_hotel_id
)                                                 as latest_fl

-- in the fact
left outer join rel_channel_site as rel_window
  on booking.channel_hotel_id = rel_window.channel_hotel_id
  and booking.departure_dt between rel_window.valid_from_dt and rel_window.valid_to_dt
left outer join rel_channel_site as rel_latest
  on booking.channel_hotel_id = rel_latest.channel_hotel_id
  and rel_latest.latest_fl
-- in the select list:
, coalesce(rel_window.site_sk, rel_latest.site_sk, ${keys.unknown()}) as site_sk
```

- Overlapping windows make the in-window join fan out. Add an assertion that the windows of one key never overlap, and make sure `latest_fl` is true for exactly one row per key.
- Choose the event date that decides the window (arrival, departure or booking date) and document the choice.
- When two sources define the window (a contract period and a membership period), require the event to fall inside both.

## 6. Latest version of a record

```sql
, case
  when row_number() over (
    partition by booking_id
    order by modified desc, created desc, version_id desc
  ) = 1 then 1
  else 0
end as latest_fl
```

- Order by enough columns to make the result deterministic: the last tie-breaker must be unique. Otherwise `latest_fl` flips between runs.
- Know where NULLs sort. With `desc`, BigQuery sorts NULLs last, so a version that was never modified (`modified` is NULL) loses to any modified one. Make that a decision, not an accident.
- A reimport can bring back an old version with a newer import timestamp. Order by the business timestamp first, and use the import timestamp only as a tie-breaker.
- Either expose `latest_fl` in L2 and filter on it in L3, or filter in L2 and say so in the grain comment. Never do both without saying so.
- If one source lags another, cut both at the same horizon (`where created <= current_date() - 2`) and comment why.

## 7. Classification rollups

Classify the lower level first, then roll it up with an explicit priority:

```sql
, site_class as (
  select
    site_sk
    , company_sk
    , case
      when has_lodging = 1 and has_food = 0 then 'lodging'      -- lodging dominates "other"
      when has_lodging = 0 and has_food = 1 and has_other = 0 then 'food'
      when has_lodging = 0 and has_food = 0 and has_other = 1 then 'other'
      else 'mixed'
    end as site_class_cd
  from (
    select
      site_sk
      , company_sk
      , max(if(type_ds = 'lodging', 1, 0)) as has_lodging
      , max(if(type_ds = 'food', 1, 0))    as has_food
      , max(if(type_ds = 'other', 1, 0))   as has_other
    from site_types
    group by site_sk, company_sk
  )
)

, company_class as (
  select
    company_sk
    , case
      when countif(site_class_cd = 'mixed') > 0 then 'mixed'   -- one mixed site makes the company mixed
      when countif(site_class_cd = 'lodging') > 0
        and countif(site_class_cd in ('food', 'other')) = 0 then 'lodging'
      -- ... remaining rules
      else 'mixed'
    end as company_class_cd
  from site_class
  group by company_sk
)
```

- Write the priority rules as comments next to the branches, and in CLAUDE.md.
- Give each class a stable code (`'001'`, `'999'`) next to its label. Reports sort and filter on the code.
- When a higher-level class repeats on lower-grain rows (the company class on every site-type row), comment that summing at that grain double-counts, and deduplicate by the higher-level key first.

## 8. KPI tables with time windows

```sql
, time_range as (
  select
    'mr12'                                                            as time_range_cd
    , date_add(date_trunc(current_date(), month), interval -11 month) as start_dt
    , current_date()                                                  as end_dt
  union all
  select 'cy', date_trunc(current_date(), year), current_date()
)

, per_window as (
  select
    customer.company_sk
    , time_range.time_range_cd
    , count(distinct invoice.invoice_sk) as invoice_cnt
  from fct_invoice as invoice
  inner join dim_customer as customer
    on invoice.customer_sk = customer.customer_sk
  inner join time_range
    on invoice.document_dt between time_range.start_dt and time_range.end_dt
  where not invoice.credit_note_fl
  group by customer.company_sk, time_range.time_range_cd
)
```

- Cross join the population with the windows, then left join the measures. Every entity then appears once per window, with a 0 instead of a missing row.
- Aggregate at the measure's own grain before joining finer data: sum invoices at invoice grain, not after joining the invoice lines.
- Write status rules (`new`, `active`, `lost`, `inactive`) as a `case` in priority order, with a comment on each branch, and give each status a sort number for reports.
- Exclude rows that would collapse into the sentinel (`where company_sk != ${keys.unknown()}`), and comment why.
- A `kpi_` model is usually a `table`: it is read often, and its windows move only once a day.

## 9. Change capture of snapshot feeds

Some systems ship a full snapshot of a table every day (forecasts, availability, balances). Keeping every snapshot is huge and mostly redundant; keeping only the last one loses the history. The answer is to store a row only when it changed. This takes three models.

`<table>_src` (view) parses the snapshot and adds the snapshot date and a hash of the measures:

```sql
select
  ${keys.surrogate("hotel_ref")}                                       as client_sk
  , stay_date
  , category_code
  , parse_date('%Y%m%d', file_date)                                    as create_dt
  , rooms_occupied
  , revenue
  , to_hex(md5(to_json_string(struct(rooms_occupied, revenue))))      as row_hash
from ${ref({schema: 'declaration_pms', name: 'daily_snapshot'})}
```

`<table>_updates` (incremental, partitioned by snapshot date) appends only the rows that changed:

```sqlx
config {
  type: "incremental",
  schema: "l1_pms",
  name: "daily_snapshot_updates",
  bigquery: {
    partitionBy: "create_dt"
  }
}

${when(incremental(), `
  with snap as (
    select *
    from ${ref({schema: 'l1_pms', name: 'daily_snapshot_src'})}
    where create_dt > (select max(create_dt) from ${self()})
  )
  , current_hashes as (
    select client_sk, stay_date, category_code, row_hash
    from ${self()}
    qualify row_number() over (partition by client_sk, stay_date, category_code order by create_dt desc) = 1
  )
  , snap_with_prev as (
    select
      snap.*
      , coalesce(
        lag(snap.row_hash) over (partition by snap.client_sk, snap.stay_date, snap.category_code order by snap.create_dt)
        , cur.row_hash
      ) as prev_hash
    from snap
    left outer join current_hashes as cur
      on snap.client_sk = cur.client_sk
      and snap.stay_date = cur.stay_date
      and snap.category_code is not distinct from cur.category_code
  )
  select * except (prev_hash)
  from snap_with_prev
  where prev_hash is null or row_hash != prev_hash
`, `
  with all_with_prev as (
    select
      *
      , lag(row_hash) over (partition by client_sk, stay_date, category_code order by create_dt) as prev_hash
    from ${ref({schema: 'l1_pms', name: 'daily_snapshot_src'})}
  )
  select * except (prev_hash)
  from all_with_prev
  where prev_hash is null or row_hash != prev_hash
`)}
```

`<table>` (view) adds the validity range:

```sql
select
  *
  , create_dt                                                     as start_date
  , lead(date_sub(create_dt, interval 1 day)) over (
    partition by client_sk, stay_date, category_code order by create_dt
  )                                                                as end_date
from ${ref({schema: 'l1_pms', name: 'daily_snapshot_updates'})}
```

- The incremental branch and the full-refresh branch must produce the same result. Test this once with `--full-refresh` and compare.
- Use `is not distinct from` for key parts that can be NULL.
- Hash only the measures. `row_hash` detects changes and is never a key, so MD5 is fine here whatever the key strategy. A hash that includes metadata such as the load time changes every day, and then every row gets stored.
- Bad early data (one source's snapshots before a known go-live date) is excluded in `_src`, with a comment.

## 10. Windowed full exports with deletions

Some exports re-send every record in a date window each time, for example the next 365 days. A record that disappears from a newer export inside its window was deleted or cancelled, and its older copies must stop counting.

```sql
, file_coverage as (
  select
    hotel_ref
    , file_date
    , min(stay_date) as min_stay_date
    , max(stay_date) as max_stay_date
  from src
  group by hotel_ref, file_date
)

, latest_file as (
  select
    days.hotel_ref
    , days.stay_date
    , max(file_coverage.file_date) as latest_file_date
  from (select distinct hotel_ref, stay_date from src) as days
  inner join file_coverage
    on days.hotel_ref = file_coverage.hotel_ref
    and days.stay_date between file_coverage.min_stay_date and file_coverage.max_stay_date
  group by days.hotel_ref, days.stay_date
)

select
  src.*
  , src.file_date = latest_file.latest_file_date as latest_fl
from src
inner join latest_file using (hotel_ref, stay_date)
```

`latest_fl` is true only for rows from the newest file whose window covers that date. Consumers of the current state filter on it; consumers of booking curves use every row.

## 11. Reconstructed history

When a source only recently started delivering snapshots, older history can sometimes be rebuilt from event data, such as bookings with a booking date and a cancellation date. These rules kept such models correct:

- Mark generated rows (`is_generated_fl = 1`) and keep their logic apart from the real snapshots; union the two only at the end.
- A cumulative "as of" curve is a running sum: `sum(x) over (partition by key order by create_dt rows between unbounded preceding and current row)`. Joining event detail back to such a curve needs `event_dt <= snapshot_dt`, not `=`.
- Generated rows exist only where events exist. Ratios need a denominator for every key and day, including the available capacity of unbooked days. Add zero-valued anchor rows at the start of each curve, and anchor the curve where it should start (for example at the entity's first event), not at an arbitrary fixed date. A missing denominator shows up as occupancy that jumps or dips while the occupied units only grow.
- Know what every event date means (booking, cancellation or departure) and how every feed dates its snapshots (two feeds can be a day apart). When joining two feeds, measure the match rate at offsets of -1, 0 and +1 days; the right offset is obvious from the numbers.
- Cancelled events stay in later snapshots with a cancellation date. Count only `cancel_dt is null` for active volume.
- Verify by reconciling the child rows against the parent curve for **every** key and snapshot (quality-and-testing.md). A fix verified on one entity has turned out wrong for most of the table before.
- Three models at three grains (the snapshot curve, the event-detail fan-out, the reconstructed history) are fine. Don't merge them to save code.

## 12. Rankings and peer groups (avoiding cycles)

Benchmarks often compare an entity with peers of similar size, ranked by a measure from a fact. When the fact itself depends on the dimension (say, the fact allocates revenue using the dimension's weights), ranking on the dimension creates a cycle: `dim → fct → dim`. Put the ranking in a downstream `rel_` model and let consumers join it.

Equal-count bands of at most about 30 members per peer group:

```sql
, cast(ceil(row_num * band_cnt / grp_cnt) as int64) as peer_group_cd
-- computed from:
, row_number() over (partition by type_cd, year_num order by coalesce(total_revenue_amt, 0)) as row_num
, count(*) over (partition by type_cd, year_num)                                           as grp_cnt
, ceil(count(*) over (partition by type_cd, year_num) / 30.0)                              as band_cnt
```

- Output one row per entity and period for the whole population (left join the bands), with `0` meaning "not banded" (excluded or ineligible). Consumers then never lose rows.
- When the same entities are banded by several measures, build a separate key per banding (`peer_group_sk`, `labour_peer_group_sk`), each with its own namespace prefix.
- Coalesce the key parts inside the id hash (`coalesce(type_cd, 'na')`). Otherwise an entity without a type gets a NULL id and silently drops out of every join.
- Materializing the bands as a `table` also keeps the consumers' queries small enough for BigQuery to plan.

## 13. Weighted allocation

Say a ledger posts revenue per accounting sector, a sector can serve several sites, and a site can span several sectors. A bridge with a `percent` weight splits the amounts:

```sql
sum(fct.amount_amt * bridge.percent / 100) as allocated_amt
```

Add a custom assertion that the weights of each sector and period sum to about 100. Duplicated bridge rows (a sum of 200) silently double the allocated revenue of every affected site, and of everything ranked on it. When no weight is known, the neutral default (`coalesce(percent, 100)`) also changes totals; see the sentinel comparison in keys-and-sentinels.md.

## 14. Reference data as code; value sets

When no system holds a small reference table (fee schedules, tier boundaries, report layouts), write it as SQL in a `view` under a dedicated source (`l1_common_data`), with its provenance in the header:

```sql
-- Membership fee tiers. 2003–2010: official fee schedule (docs/fees.csv).
-- 2011–2024: derived from billing data. From 2025: two schedules by business type.
select year_num, schedule_cd, tier_num, amount_amt, turnover_from_amt, turnover_to_amt
from unnest([2025]) as year_num
cross join unnest([
  struct('food' as schedule_cd, 1 as tier_num, 200.0 as amount_amt, 0.0 as turnover_from_amt, 50000.0 as turnover_to_amt)
  , struct('food', 2, 260.0, 50000.01, 100000.0)
])
```

To translate source codes into target codes (exit reasons, statuses for one consumer), keep a value-set table that the business maintains, for example a spreadsheet loaded as a source. It has the columns `source, source_field, source_value, target, target_field, target_value`, is exposed as `l2_masterdata.dim_valueset`, and is joined with `target_ds = '<consumer>' and target_field_ds = '<field>'`. A mapping then changes without a deploy.

## 15. Calendar dimension

Generate the calendar instead of loading it:

```sql
with date_spine as (
  select date_dt
  from unnest(generate_date_array('2005-01-01', '2035-12-31')) as date_dt
)

select
  date_dt
  , extract(year from date_dt)                                                             as year_num
  , extract(quarter from date_dt)                                                          as quarter_num
  , format_date('%Y%m', date_dt)                                                           as year_month_cd
  , extract(isoweek from date_dt)                                                          as iso_week_num
  , date_trunc(date_dt, month)                                                             as first_day_of_month_dt
  , if(extract(year from date_dt) = extract(year from current_date()), 1, 0)               as cy_fl
  , if(extract(year from date_dt) = extract(year from current_date()) - 1, 1, 0)           as py_fl
  , if(extract(dayofyear from date_dt) < extract(dayofyear from current_date()), 1, 0)     as ytd_fl
  , if(
    date_dt between date_sub(date_trunc(current_date(), month), interval 11 month)
    and last_day(current_date(), month), 1, 0
  )                                                                                        as mr12_fl
from date_spine
```

- Relative flags make BI filters trivial (`cy_fl = 1`). In a `table` they freeze at build time, so rebuild the table daily or make it a view.
- Day-of-year flags such as `ytd_fl` compare the same period across years. Check how they behave in leap years if February matters.
- Business-unit calendars (a fiscal year, one unit's working-day calendar) are separate models in that unit's schema, joined to the base calendar in `l2_masterdata`.
- Report-specific period pickers ("last 7 days vs. the same period last year") are helper views in L3R, built on the calendar.

## 16. Hierarchies for BI

BI tools handle fixed-depth level columns much better than parent-child tables. Flatten an outline into `level1_cd`/`level1_ds` through `level4_cd`/`level4_ds`, plus `sort_num`, `level_num`, and a `sign_num` that says how a line adds into its total. When the outline skips a level (a level-4 line that rolls straight into a level-2 subtotal), leave the skipped level NULL instead of inventing a parent, and comment the rule. Display labels can repeat across different codes, so join and filter on codes, never on labels.

## 17. JavaScript-generated SQL

Use a `js { }` block when the same expression repeats over a list of columns:

```sqlx
js {
  const cumulativeColumns = ['revenue_amt', 'room_nights_cnt', 'guest_nights_cnt'];
  const cumulativeSum = (columns) => columns
    .map((c) => `sum(${c}) over (partition by sales_sk order by create_dt rows between unbounded preceding and current row) as ${c}`)
    .join('\n    , ');
}

select
  sales_sk
  , ${cumulativeSum(cumulativeColumns)}
from ...
```

Good uses: running sums over many measures, the zero columns of an anchor row, label maps (`code → name` as a `case`), joins to a code list for every enumerated column of a statistical table, unpivots.

- Keep the list in one `const` at the top, so adding a column is a single edit.
- Shared helpers go in `includes/`, where Dataform exposes each file as a global named after it. A helper used by one model stays in that model.
- After a mechanical refactor into JS, compare the compiled SQL before and after (`dataform compile --json`). Apart from whitespace, it should be identical.
- Give sqlfluff a placeholder value for any identifier inside `${}` that must expand to valid SQL (tooling-and-ops.md).
