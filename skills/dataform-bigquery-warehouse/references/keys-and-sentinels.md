# Keys and sentinels

## Contents

1. Choosing a key strategy
2. The keys helper
3. Key rules
4. 'na' vs 'nd'
5. The "not assigned" sentinel row
6. Kinds of sentinel (comparison)
7. Scoped default members (e.g. sector 0 "Default")
8. Choosing the right kind
9. Joining to dimensions

## 1. Choosing a key strategy

Surrogate keys decouple the warehouse from source keys. They integrate several sources into one key space, survive a source re-keying, and keep raw ids out of presentation. *How* to compute them depends on the system, so there is no single right answer. Choose once per repository, before the first model, and record the choice in `includes/keys.js` and CLAUDE.md.

**An existing repository keeps the strategy it already uses**, often `to_hex(md5(...))` written inline. Changing it changes every key downstream, which breaks every L3P target and anything that stored keys.

| Strategy | Generated SQL | Type | Strengths | Weaknesses |
| --- | --- | --- | --- | --- |
| `md5_hex` | `to_hex(md5(cast(x as string)))` | STRING, 32 chars | Portable: Postgres (`md5()`), Python (`hashlib`), Java and Spark compute the same key, so apps and other databases can produce or check keys. 128 bits make collisions negligible | Four times wider than INT64: more storage, slower joins, larger BI models |
| `farm_fingerprint` | `farm_fingerprint(cast(x as string))` | INT64 | BigQuery-native, with the smallest storage and fastest joins. Integer relationships compress best in Power BI and Analysis Services import models. Matches Kimball's preference for integer keys | Hard to reproduce outside BigQuery. 64 bits: the chance of any collision is about n²/2⁶⁵, roughly 1 in 37 million at 1 million members and 1 in 3,700 at 100 million. Keys can be negative |
| `sha256_hex` | `to_hex(sha256(cast(x as string)))` | STRING, 64 chars | Meets security policies that ban MD5 | The widest key |
| `natural` | `cast(x as string)` | STRING | Simplest, and readable | Exposes raw ids to consumers, breaks when the source re-keys, and still needs namespacing when sources overlap |

Choose by what the system does with its keys:

| If the system … | Choose |
| --- | --- |
| Sends keys out of BigQuery: L3P tables expose keys that apps store or join on, reverse ETL writes them back, or another database must compute the same key | `md5_hex` |
| Keeps keys inside BigQuery and its BI tool, especially Power BI or Looker import models over large facts | `farm_fingerprint` |
| Has key spaces that can exceed about 100 million members (events, sessions, devices) | `md5_hex`, or `farm_fingerprint` with a `uniqueKey` assertion and an explicitly accepted collision risk |
| Must follow a policy that bans MD5, or needs pseudonymous keys | `sha256_hex`, with a secret salt prefix for pseudonymization. An unsalted hash of a low-entropy id, such as a customer number, can be reversed by brute force, so hashing alone isn't anonymization |
| Is a small, single-source project whose ids are stable, meaningless and not sensitive | `natural` |

Notes:

- **Decouple L3P when you can.** If apps shouldn't depend on warehouse keys at all, expose business codes (`customer_cd`) in L3P. The internal strategy then stays free to change.
- **Use one strategy per repository.** With mixed strategies, joins fail on type mismatches (STRING against INT64), or silently match nothing because the same entity gets different keys.
- **Classic sequence keys (1, 2, 3 …)** need a persisted key map, because BigQuery has no sequences and `row_number()` renumbers on every rebuild. Use them only when a consumer demands small sequential integers: keep an incremental `key_map_<entity>` table that assigns each new business key `max(key) + row_number()` exactly once, and join to it.
- **When the system's needs are unclear** (who consumes the keys, which BI tool reads them, how big the key spaces get), ask before choosing. This decision is expensive to change.

## 2. The keys helper

The template project ships `includes/keys.js`. Its `STRATEGY` constant holds the choice, and every model calls the helper, so no model hardcodes a hash function. Dataform exposes the file as the global `keys`:

```sqlx
-- L1: key the primary key and every foreign key once
, ${keys.surrogate("id")}           as invoice_id
, ${keys.surrogate("customer_ref")} as customer_id

-- L2: fall back to the unknown member when a lookup fails
, coalesce(dim_customer.customer_id, ${keys.unknown()}) as customer_id

-- composite or namespaced keys
, ${keys.composite("'entity_a'", "invoice.id")} as invoice_id
```

What the calls generate:

| Call | `md5_hex` | `farm_fingerprint` | `natural` |
| --- | --- | --- | --- |
| `keys.surrogate("id")` | `coalesce(to_hex(md5(cast(id as string))), to_hex(md5('nd')))` | `coalesce(farm_fingerprint(cast(id as string)), -2)` | `coalesce(cast(id as string), 'nd')` |
| `keys.composite("a", "b")` | `to_hex(md5(concat(coalesce(cast(a as string), 'na'), '\|', coalesce(cast(b as string), 'na'))))` | the same `concat`, wrapped in `farm_fingerprint` | the `concat` itself |
| `keys.unknown()` | `to_hex(md5('na'))` | `-1` | `'na'` |
| `keys.noData()` | `to_hex(md5('nd'))` | `-2` | `'nd'` |
| `keys.type()` | `string` | `int64` | `string` |

`sha256_hex` matches `md5_hex`, with `sha256` in place of `md5`. INT64 keys use Kimball's conventional `-1` and `-2` for the sentinels.

In a repository without the helper, follow its inline formula exactly. The rules below apply either way.

## 3. Key rules

- **Key once, in L1.** Key the primary key and every foreign key the same way in L1, so any L2 model can join without knowing the source key's type.
- **Cast to STRING before hashing.** `'123'` and `'123.0'` hash differently. If a source stores integer ids as floats, cast them to INT64 first.
- **Key the business key, not the row.** The key must not change when a non-key column changes. A type 2 history row gets its own key: `keys.composite("customer_ref", "valid_from_dt")`.
- **Keep keys deterministic.** Never put `current_date()`, `current_timestamp()`, `rand()` or `generate_uuid()` into a key or into a key's NULL fallback.
- **Coalesce and separate every part of a composite key.** `concat()` returns NULL when any argument is NULL, and `('ab', 'c')` collides with `('a', 'bc')` without a separator. The helper handles both. Inline code must do it by hand.
- **Namespace overlapping id spaces.** Two legal entities with separate ERP databases need `keys.composite("'entity_a'", "id")` and `keys.composite("'entity_b'", "id")`, plus a discriminator column `source_company_ds`. Two groupings computed in one model need prefixes too (`'labour'`), so their ids can never be equal.
- **Assert `uniqueKey` on every key**, especially with 64-bit keys, where it is also the collision alarm.

## 4. 'na' vs 'nd'

| Key | Meaning | Where it's produced |
| --- | --- | --- |
| `keys.noData()` (`md5('nd')`, `-2`, `'nd'`) | No data: the source key itself was NULL | In L1, as the NULL fallback of `keys.surrogate` |
| `keys.unknown()` (`md5('na')`, `-1`, `'na'`) | Not assigned: there was a value but no matching entity, or this is the sentinel row | In L2, as the fallback of every dimension lookup, and as the key of every sentinel row |

The no-data key never matches a dimension row, so the L2 lookup turns it into the unknown key. The distinction pays off while you debug: `nd` in L1 points at the source, and `na` in L2 points at a mapping gap.

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
    ${keys.unknown()} as customer_id
    , 'na'            as customer_cd
    , 'Not Assigned'  as customer_ds
    , false           as active_fl
)
```

- `union all strict corresponding` matches the columns by name and fails when the two column sets differ. A column added to the first branch but missing from the sentinel then fails loudly, instead of shifting values into the wrong columns.
- Facts coalesce every foreign key to the unknown key. An `inner join` from a fact to a dimension then drops no rows, the totals stay complete, and the unknown share appears in reports as "Not Assigned" instead of disappearing.
- Use fixed sentinel values: `'Not Assigned'` or `'na'` for strings, `date '0001-01-01'` or `date '9999-12-31'` for open-ended dates, `false` for flags, NULL for measures. Never `current_date()`.
- Use one label across the whole repository (`'Not Assigned'`, or a translation of it). To change it, change every model at once.
- L3P filters the sentinel out (`where customer_id != ${keys.unknown()}`), because target programs don't know the warehouse's placeholders. L3R keeps it, so people see the unassigned bucket.

For a wide dimension, a typed sentinel saves you from listing every column:

```sql
, not_assigned as (
  -- left join on false yields one all-NULL row with the column types of final
  select
    final.* replace (
      ${keys.unknown()} as customer_id
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
| Global "not assigned" row | `keys.unknown()`, `'Not Assigned'` | A lookup failed: a value exists but no entity matches it | One constant per dimension | Yes: the unassigned share of the facts | Filter out | Show as its own bucket, or filter out |
| "No data" key | `keys.noData()` | The source key was NULL | Constant; never matches a dimension row | Turns into `na` after the L2 lookup | — | — |
| Scoped default member | Sector `0` "Default" for each company and fiscal year | The source system's own catch-all inside a parent: what isn't split explicitly belongs here | A real key, built together with its parent | Yes: real business amounts | Keep, with a label | Keep |
| Catch-all category | Country group `'Other'` | A valid class that groups everything not listed separately | An ordinary code | Yes | Keep | Keep |
| Scope sentinel | An L3R member dimension restricted to ordinary members, plus one `na` row | The facts contain entities that this report's dimension leaves out on purpose | `keys.unknown()`, added in L3R | Yes | — | Show as "Not Assigned" |
| Numeric "not computed" | `peer_group_cd = 0` | The entity wasn't eligible for a computation | A value that can't occur, here `0` | No | Filter out or label | Label it ("not banded") |
| Neutral default weight | `coalesce(percent, 100)` | No allocation is known, so take the full amount | — | **Changes totals** | — | — |
| Open-ended dates | `date '0001-01-01'`, `date '9999-12-31'` | No start, or no end | — | — | NULL, or the target's convention | — |
| Hash placeholder | `coalesce(revenue_dt, date '1900-01-01')` inside an inline composite key | Only keeps `concat` from returning NULL | — | — | Never exposed | Never exposed |

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
    ${keys.composite("all_sectors.customer_id", "all_sectors.year_nr", "all_sectors.office_cd", "all_sectors.sector_cd")} as sector_id
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
, coalesce(dim_sector.sector_id, dim_sector_default.sector_id, ${keys.unknown()}) as sector_id
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
- **Key it like a real member, scoped by its parent.** Never give it the unknown key. The amount must stay with its company and year, and the global `na` row would pool every company's defaults into one.
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
, coalesce(dim_customer.customer_id, ${keys.unknown()}) as customer_id
```

Use a `left outer join` while building the fact and coalesce on the way out. Downstream models, L3 and BI can then use inner joins safely.
