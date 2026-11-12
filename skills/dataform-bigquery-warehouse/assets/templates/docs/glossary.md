# <Organization> Data Warehouse Glossary

This glossary covers the whole warehouse: the layers, the source systems, the naming conventions, business terms, codes, measures, and every L2 and L3 object. It describes what the SQL does. Where the SQL behaves differently from what a name suggests, the difference is listed in [§10 Pitfalls](#10-pitfalls-names-that-mislead).

Update this file in the same change as the code it describes; the dataform-bigquery-warehouse skill's `references/glossary.md` says which change updates which section.

**Target:** BigQuery project `<project>`, location `<location>`.
**Last full review:** <date>, against `main`.

## Contents

1. [Architecture and layers](#1-architecture-and-layers)
2. [Source systems](#2-source-systems)
3. [Naming conventions](#3-naming-conventions)
4. [Business glossary (source language → English)](#4-business-glossary-source-language--english)
5. [Codes and enumerations](#5-codes-and-enumerations)
6. [Calendar and period flags](#6-calendar-and-period-flags)
7. [Measures by business unit](#7-measures-by-business-unit)
8. [L2 object catalogue](#8-l2-object-catalogue)
9. [L3 object catalogue](#9-l3-object-catalogue)
10. [Pitfalls: names that mislead](#10-pitfalls-names-that-mislead)

---

## 1. Architecture and layers

```text
raw sources ──► declaration_{source} ──► l1_{source} ──► l2_{business_unit} ──► l3p_{target} / l3r_{audience}
```

| Layer | Schema pattern | Purpose |
| --- | --- | --- |
| Declaration | `declaration_{source}` | Read-only references to raw tables loaded by the ELT jobs |
| L1 | `l1_{source}` | One model per raw table. Columns keep their source names |
| L2 | `l2_{business_unit}` | Business logic, one schema per business unit, plus shared schemas |
| L3P | `l3p_{target}` | Tables read by a program (machine to machine) |
| L3R | `l3r_{audience}` | Views read by people through BI |
| Assertions | `dataform_assertions` | Data-quality checks |

### L2 schemas

| Schema | Business unit / role |
| --- | --- |
| `l2_masterdata` | Shared: conformed dimensions (customer, …) |
| `l2_relationship` | Shared: bridges between units and their systems |
| `l2_sales` | Sales: invoices, … |

### L3 schemas

| Schema | Reader | Target or audience |
| --- | --- | --- |
| `l3p_webapp` | Program | Web app backend (sync job) |
| `l3r_sales` | People | Sales dashboard |

## 2. Source systems

| Source | L1 schema | What it is | Main data | Load cadence |
| --- | --- | --- | --- | --- |
| ERP | `l1_erp` | <system> | Customers, invoices | <daily> |
| CRM | `l1_crm` | <system> | Accounts | <daily> |

## 3. Naming conventions

### Table prefixes

| Prefix | Meaning |
| --- | --- |
| `dim_` | Dimension |
| `fct_` | Fact |
| `rel_` | Bridge or mapping |
| `kpi_` | Pre-aggregated measures |

### Column suffixes

| Suffix | Type | Examples |
| --- | --- | --- |
| `_id` | Hashed key | `customer_id` |
| `_cd` | Code | `customer_cd`, `country_cd` |
| `_ds` | Description | `customer_ds` |
| `_dt` | Date or timestamp | `entry_dt` |
| `_fl` | Flag | `active_fl` |
| `_nr` | Ordinal or sequence number | `year_nr` |
| `_qt` | Quantity or count | `invoice_qt` |
| `_vl` | Amount or value | `gross_amount_vl` |
| `_pc` | Percentage | `occupancy_pc` |

### Surrogate keys

`coalesce(to_hex(md5(cast(source_id as string))), to_hex(md5('nd')))`, hashed once in L1.

### Sentinel values

| Value | Meaning |
| --- | --- |
| `to_hex(md5('na'))`, `'Not Assigned'` | Not assigned: a lookup failed, or the dimension's sentinel row |
| `to_hex(md5('nd'))` | No data: the source key was null |

## 4. Business glossary (source language → English)

### <Business unit>

| Term | Language | English | Notes |
| --- | --- | --- | --- |
| Kunde | DE | Customer | `dim_customer` |

## 5. Codes and enumerations

### Invoice document type (`fct_invoice.credit_note_fl`)

| Code | Meaning |
| --- | --- |
| `CREDIT_NOTE` | Credit note: amounts are negative, `credit_note_fl = true` |

### Hardcoded ids worth knowing

| Where | Id | Meaning |
| --- | --- | --- |
| `includes/constants.js` `excluded_customer_cds` | `900001`, `900002` | ERP test and training customers, excluded from `dim_customer` |

## 6. Calendar and period flags

| Flag | Meaning |
| --- | --- |
| `cy_fl` | Date is in the current year |

### Data-release cut-offs

| Source | Rule |
| --- | --- |
| ERP invoices | History starts in 2020 (`l1_erp.invoice`): earlier invoices were re-keyed in the migration |

## 7. Measures by business unit

### 7.1 Sales

| Column | Meaning |
| --- | --- |
| `gross_amount_vl` | Invoice total including VAT; negative for credit notes |
| `net_amount_vl` | Invoice total excluding VAT |
| `open_amount_vl` | Amount not yet paid |

## 8. L2 object catalogue

Types: **V** view, **T** table, **I** incremental.

### `l2_masterdata`

| Object | Type | Grain | Description |
| --- | --- | --- | --- |
| dim_customer | V | Customer | ERP customers with code, name, country and activity flag, plus the `na` row |

### `l2_sales`

| Object | Type | Grain | Description |
| --- | --- | --- | --- |
| fct_invoice | V | Invoice document | ERP invoices and credit notes with customer and amounts |

### `l2_relationship`

| Object | Type | Grain | Description |
| --- | --- | --- | --- |
| rel_crm_erp_customer | V | CRM account × ERP customer | Match on the ERP number typed into the CRM; misses kept with `match_status_cd` |

## 9. L3 object catalogue

### `l3p_webapp` (program)

| Object | Type | Grain | Description | Fixed field names |
| --- | --- | --- | --- | --- |
| customers | T | Customer | Customer list for the web app | `id`, `name`, `country`, `entry_date`, `exit_date`, `is_active`, `updated_at` |

### `l3r_sales` (people)

| Object | Type | Grain | Description |
| --- | --- | --- | --- |
| dim_customer | V | Customer | Customer dimension for the sales dashboard, `na` row included |
| fct_invoice | V | Invoice document | Invoices of the last 10 years |
| fct_last_refresh | I | Run | Refresh heartbeat |

## 10. Pitfalls: names that mislead

These come from the SQL as it stands on <date>. Check before relying on them.

| Where | Issue |
| --- | --- |
| <model.column> | <what the name suggests vs. what the SQL does> |
