# Keys and sentinels

## Contents

1. Surrogate keys
2. Composite keys
3. Namespaces
4. 'na' vs 'nd'
5. The "not assigned" sentinel row
6. Kinds of sentinel (comparison)
7. Scoped default members (e.g. sector 0 "Default")
8. Choosing the right kind
9. Joining to dimensions

## 1. Surrogate keys

From L1 on, every exposed key is a hex MD5 string:

```sql
coalesce(to_hex(md5(cast(source_id as string))), to_hex(md5('nd'))) as customer_id
```

Why:

- Raw source keys never leak into L2 or L3, so consumers get stable, opaque ids.
- Every key has the same type (a 32-character hex STRING), so joins never need casts.
- Hashing happens once, in L1, the same way for primary and foreign keys. `md5(cast(x as string))` gives equal hashes on both sides, so any L2 model can join without knowing the source key's type.

Rules:

- Cast to STRING before hashing. `md5(123)` doesn't compile, and `'123'` and `'123.0'` hash differently. If a source stores integer ids as floats, cast them to INT64 first.
- Hash the business key, not the whole row. The id must not change when a non-key column changes.
- Keep hashes deterministic. Never put `current_date()`, `current_timestamp()`, `rand()` or `generate_uuid()` into a key or into a key's null fallback.

## 2. Composite keys

```sql
to_hex(md5(concat(
  coalesce(site_id, to_hex(md5('na')))
  , '|', cast(revenue_dt as string)
  , '|', coalesce(category_cd, 'na')
))) as sales_id
```

- `concat()` returns NULL when any argument is NULL, so coalesce **every** part. A NULL key drops out of every join, and `uniqueKey` doesn't flag it.
- Cast dates and numbers explicitly instead of relying on implicit formatting.
- Put a separator between parts that could run together. Without one, `('ab', 'c')` and `('a', 'bc')` collide.

## 3. Namespaces

When two id spaces can produce the same input string, prefix each one:

- For two legal entities with separate ERP databases, hash `concat('entity_a - ', id)` and `concat('entity_b - ', id)`, and add a discriminator column `source_company_ds`.
- For two groupings computed in one model, prefix one of them (`concat('labour', '|', year, '|', band)`), so that a `peer_group_id` can never equal a `labour_peer_group_id`.

## 4. 'na' vs 'nd'

| Value | Meaning | Where it's produced |
| --- | --- | --- |
| `to_hex(md5('nd'))` | No data: the source key itself was NULL | In L1, as the null fallback of the key hash |
| `to_hex(md5('na'))` | Not assigned: there was a value but no matching entity, or this is the sentinel row | In L2, as the fallback of every dimension lookup, and as the key of every sentinel row |

`md5('nd')` never matches a dimension row, so the L2 lookup turns it into `md5('na')`. The distinction pays off while you debug: `nd` in L1 points at the source, and `na` in L2 points at a mapping gap.

## 5. The "not assigned" sentinel row

Every dimension carries exactly one "not assigned" row:

```sql
, final as (
  select
    customer.customer_id
    , customer.customer_cd
    , customer.customer_ds
    , customer.active_fl
  from l1_erp_customer as customer

  union all strict corresponding

  select
    to_hex(md5('na')) as customer_id
    , 'na'            as customer_cd
    , 'Not Assigned'  as customer_ds
    , false           as active_fl
)
```

- `union all strict corresponding` matches the columns by name and fails when the two column sets differ. A column added to the first branch but missing from the sentinel then fails loudly, instead of shifting values into the wrong columns.
- Facts coalesce every foreign key to the sentinel. An `inner join` from a fact to a dimension then drops no rows, the totals stay complete, and the unknown share appears in reports as "Not Assigned" instead of disappearing.
- Use fixed sentinel values: `'Not Assigned'` or `'na'` for strings, `date '0001-01-01'` or `date '9999-12-31'` for open-ended dates, `false` for flags, NULL for measures. Never `current_date()`.
- L3P filters the sentinel out (`where customer_id != to_hex(md5('na'))`), because target programs don't know the warehouse's placeholders. L3R keeps it, so people see the unassigned bucket.

For a wide dimension, a typed sentinel saves you from listing every column:

```sql
, not_assigned as (
  -- left join on false yields one all-NULL row with the column types of final
  select
    final.* replace (
      to_hex(md5('na')) as customer_id
      , 'Not Assigned'  as customer_ds
      , false           as active_fl
    )
  from (select 1) as one
  left outer join final on false
)

select * from final
union all
select * from not_assigned
```

## 6. Kinds of sentinel

"Sentinel" covers several different things, and mixing them up causes most of the bugs around them. A mature warehouse ends up with every kind below. For each placeholder you add, decide which kind it is: the kinds differ in their key, in whether they carry money, and in what presentation does with them.

| Kind | Example | Meaning | Key | Holds amounts? | L3P (programs) | L3R (people) |
| --- | --- | --- | --- | --- | --- | --- |
| Global "not assigned" row | `md5('na')`, `'Not Assigned'` | A lookup failed: a value exists but no entity matches it | One constant per dimension | Yes: the unassigned share of the facts | Filter out | Show as its own bucket, or filter out |
| "No data" key | `md5('nd')` | The source key was NULL | Constant; never matches a dimension row | Turns into `na` after the L2 lookup | — | — |
| Scoped default member | Sector `0` "Default" for each company and fiscal year | The source system's own catch-all inside a parent: what isn't split explicitly belongs here | A real key, hashed together with its parent | Yes: real business amounts | Keep, with a label | Keep |
| Catch-all category | Country group `'Other'` | A valid class that groups everything not listed separately | An ordinary code | Yes | Keep | Keep |
| Scope sentinel | An L3R member dimension restricted to ordinary members, plus one `na` row | The facts contain entities that this report's dimension leaves out on purpose | `md5('na')`, added in L3R | Yes | — | Show as "Not Assigned" |
| Numeric "not computed" | `peer_group_cd = 0` | The entity wasn't eligible for a computation | A value that can't occur, here `0` | No | Filter out or label | Label it ("not banded") |
| Neutral default weight | `coalesce(percent, 100)` | No allocation is known, so take the full amount | — | **Changes totals** | — | — |
| Open-ended dates | `date '0001-01-01'`, `date '9999-12-31'` | No start, or no end | — | — | NULL, or the consumer's convention | — |
| Hash placeholder | `coalesce(revenue_dt, date '1900-01-01')` inside a composite key | Only keeps `concat` from returning NULL | — | — | Never exposed | Never exposed |

## 7. Scoped default members

Some source systems keep their own catch-all inside a parent entity. An accounting system, for example, can give every company and fiscal year a sector `0` "Default", and postings without a sector land there. That isn't missing data. The default sector is a real member that holds real money, and it has to behave differently from the global `na` row.

The dimension generates the default for every parent:

```sql
-- every customer and year gets a default sector 0, even when the source lists no sectors at all
, all_sectors as (
  select customer_id, year_nr, office_cd, 0 as sector_cd   -- generated default
  from customer_years
  union distinct
  select customer_id, year_nr, office_cd, sector_cd        -- sectors listed by the source
  from source_sectors
)

, final as (
  select
    to_hex(md5(concat(
      all_sectors.customer_id
      , '|', cast(all_sectors.year_nr as string)
      , '|', all_sectors.office_cd
      , '|', cast(all_sectors.sector_cd as string)
    )))                                                         as sector_id
    , all_sectors.customer_id
    , all_sectors.year_nr
    , all_sectors.office_cd
    , all_sectors.sector_cd
    , coalesce(source_sectors.sector_ds, 'Default')             as sector_ds
    , count(*) over (
      partition by all_sectors.customer_id, all_sectors.year_nr, all_sectors.office_cd
    ) = 1                                                       as single_sector_fl
  from all_sectors
  left outer join source_sectors
    using (customer_id, year_nr, office_cd, sector_cd)
)
```

The fact falls back to the parent's default before it falls back to the global sentinel:

```sql
, coalesce(dim_sector.sector_id, dim_sector_default.sector_id, to_hex(md5('na'))) as sector_id
-- ...
left outer join l2_finance_dim_sector as dim_sector
  on fct.customer_id = dim_sector.customer_id
  and fct.year_nr = dim_sector.year_nr
  and fct.office_cd = dim_sector.office_cd
  and fct.sector_cd = dim_sector.sector_cd
left outer join l2_finance_dim_sector as dim_sector_default
  on fct.customer_id = dim_sector_default.customer_id
  and fct.year_nr = dim_sector_default.year_nr
  and fct.office_cd = dim_sector_default.office_cd
  and dim_sector_default.sector_cd = 0
```

Rules:

- **Generate the default for every parent**, whether or not the source lists it, so the fallback always has a target. Assert that every parent has exactly one default member.
- **Key it like a real member, scoped by its parent.** Never give it `md5('na')`. The amount must stay with its company and year, and a global `na` would pool every company's defaults into one row.
- **Fall back in order:** the exact member, then the parent's default, then the global `na`. Use the global `na` only when the parent itself is unknown.
- **Presentation keeps it**, with a readable label ("Default", "General"). Filtering it out the way you filter `na` deletes real amounts.
- **Flag single-member parents** (`single_sector_fl`). When the default is a parent's only member, every match against that parent is trivial. Report such matches under their own status (`single sector`), or they inflate the match rate. In one cross-system bridge, most "matches" turned out to be single-sector defaults.
- **Keep real codes from colliding with the default.** If the other side of a match can carry a genuine code `0` or `000`, null it out (`nullif(safe_cast(code as int64), 0)`), so that only a deliberately generated default can match the default member.
- **In a multi-member parent, an unused default is normal.** Don't report it as a gap; exclude it from "unmatched" QA lists (`where not (sector_cd = 0 and not single_sector_fl)`).
- **Defaults can meet each other.** Give the other side of a bridge its own generated default: for example, an employer without cost centers gets a default cost center 0 that matches the default sector 0. The two systems' catch-alls then pair up instead of both showing as unmatched. Flag the generated one (`default_cost_center_fl`) so it stays distinguishable from a real cost center.
- **Weights:** if the default member takes part in an allocation (a percentage split across sites), give it the same neutral weight in every model that allocates (`coalesce(percent, 100)`), and comment it.

## 8. Choosing the right kind

- **Is the value unknown, or did the source put it in a bucket on purpose?** If it's unknown, use `na`. If it's deliberate, use a scoped default member or a catch-all category.
- **Does the bucket belong to a parent** (a company, a year)? If yes, it's a scoped default member with a parent-scoped key. If no, it's a catch-all category code.
- **Don't pour unmapped values into a catch-all category.** `coalesce(country_group_cd, 'Other')` hides mapping gaps inside a legitimate bucket. Map unmapped values to `na` / "Not Assigned" and keep "Other" for values that were mapped to it on purpose. If a report insists on a single bucket, keep a `_mapped_fl` column so QA can still find the gaps.
- **A report dimension narrower than its facts** (only ordinary members, only active sites) needs a scope sentinel in L3R. Facts outside the scope then show up as "Not Assigned" instead of vanishing in an inner join, or showing a blank member.
- **Numeric markers** (`0` = not banded) must use a value that can never occur. Document the value next to the column, and prefer it to NULL, which drops out of group-bys and joins.
- **Labels:** use one label per kind across the repository: `'Not Assigned'` for `na`, `'Default'` for default members, `'Other'` for catch-alls. Filter on keys and codes, never on labels. Labels get translated, and changing a label repository-wide is a large diff that touches every dimension.
- **Dates:** pick one pair for open-ended ranges (`0001-01-01` / `9999-12-31`) and one placeholder for hashes. Don't mix `1900-01-01`, `1970-01-01`, `2001-01-01` and `2099-12-31` across models; each new variant breaks someone's `where end_dt = ...`.
- **Neutral weights** (`coalesce(percent, 100)`) change totals. Comment every one, and use the same default in every model that allocates with the same weights.

## 9. Joining to dimensions

```sql
from l1_erp_invoice as invoice
left outer join l2_masterdata_dim_customer as dim_customer
  on invoice.customer_id = dim_customer.customer_id
-- in the select list:
, coalesce(dim_customer.customer_id, to_hex(md5('na'))) as customer_id
```

Use a `left outer join` while building the fact and coalesce on the way out. Downstream models, L3 and BI can then use inner joins safely.
