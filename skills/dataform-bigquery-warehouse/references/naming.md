# Naming

## Schemas

| Layer | Pattern | Examples |
| --- | --- | --- |
| Declarations | `declaration_<source>` | `declaration_erp`, `declaration_crm`, `declaration_payroll` |
| L1 | `l1_<source>` | `l1_erp`, `l1_crm` |
| L2 business units | `l2_<business_unit>` | `l2_sales`, `l2_finance`, `l2_hr`, `l2_tax_advisory` |
| L2 shared | `l2_masterdata`, `l2_relationship`, `l2_monitoring` | |
| L3P (machine to machine) | `l3p_<target>`, named after the target system | `l3p_webapp`, `l3p_crm`, `l3p_partner_export` |
| L3R (people) | `l3r_<audience>`, named after the audience | `l3r_management`, `l3r_finance`, `l3r_regulator` |
| Assertions | `dataform_assertions` | set in `workflow_settings.yaml` |

Source, business-unit, target and audience names are short, stable, lowercase snake_case.

- Name a source after the system (`erp`, `pms`, `payroll`), not after the vendor.
- Name a business unit after what it does, not after the current department label, so the name survives a reorganization.
- Name a target after the system that reads it, not after the team that runs it.

## Tables

| Prefix | Use | Grain example |
| --- | --- | --- |
| `dim_` | Dimension: one row per entity, plus the sentinel | `dim_customer`: one row per customer |
| `fct_` | Fact: events or measurements | `fct_invoice`: one row per invoice |
| `rel_` | Bridge or mapping between entities or systems | `rel_crm_erp_customer`: one row per account/customer pair |
| `kpi_` | Pre-aggregated measures | `kpi_customer`: one row per customer and time window |

Suffixes on table names:

- `_hist`: a reconstructed or historized version of a model (`fct_booking_hist`).
- `_src`, `_updates`: the steps of an L1 change-capture stack. The public model keeps the plain name.
- `_tvf`: a table-valued function.
- `fct_last_refresh`: the refresh heartbeat of a reporting schema.

L1 models keep the raw table's name, minus loader suffixes. L3P models use the target system's entity names (`customers`, `members`, `bookings`).

## Columns

| Suffix | Meaning | Type | Examples |
| --- | --- | --- | --- |
| `_id` | Surrogate or foreign key, hex MD5 | STRING | `customer_id`, `site_id` |
| `_cd` | Business code: ids shown to people, ISO codes, postal codes, phone numbers, category codes | STRING (INT64 only for truly numeric codes) | `customer_cd`, `country_cd`, `postal_cd` |
| `_ds` | Description or label | STRING | `customer_ds`, `street_ds` |
| `_long_ds` | Display label `code - description` | STRING | `customer_long_ds` |
| `_dt` | Date or timestamp | DATE / TIMESTAMP | `entry_dt`, `document_dt`, `update_dt` |
| `_fl` | Boolean flag | BOOL (INT64 0/1 if the BI tool sums flags) | `active_fl`, `latest_fl` |
| `_nr` | Ordinal or sequence number | INT64 | `sort_nr`, `level_nr`, `year_nr`, `month_nr` |
| `_qt` | Count or quantity | INT64 / NUMERIC | `room_qt`, `invoice_qt` |
| `_vl` | Amount or numeric value | NUMERIC / FLOAT64 | `gross_amount_vl`, `revenue_vl` |
| `_pc` | Percentage | FLOAT64 / NUMERIC | `occupancy_pc` |

Rules:

- A column name is `<entity or measure>_<qualifier>_<suffix>`: `invoice_recipient_ds`, `revenue_room_adults_vl`.
- Choose one convention per concept and keep it repository-wide: `year_nr` or `year_cd`, not both. A column used as a join key across models has the same name and type everywhere.
- Flags: choose BOOL or 0/1 per table and never mix the two within a table. Document INT64 flags, because `where latest_fl` fails on an INT64.
- Percentages: say in a comment whether `_pc` runs from 0 to 1 or from 0 to 100.
- Where users search by the raw source id, keep it in L2 next to the hash: `source_customer_id` (raw) beside `customer_id` (hash).
- Store numeric-looking source ids as STRING when they are identifiers rather than quantities.

## Language

- L1 keeps the source language. Column names are often German, Italian or vendor jargon.
- L2 and L3R use English column names. Values shown to users (status labels, category names) can stay in the users' language.
- Keep a glossary in CLAUDE.md (source term → English term), so the same source term always turns into the same English word.

## CTEs and aliases

- An import CTE is named `<schema>_<model>` (`l2_masterdata_dim_customer`). A CTE that derives something is named after what it holds (`first_invoice_per_customer`).
- A table alias names the table's role: `dim_customer`, `fct_invoice`. When the same dimension is joined twice, use `dim_address` and `dim_post_address`.
- The last CTE is `final`.

## Tags

- Every L3P model gets `tags: ["l3p_<target>"]`. The target's schedule runs `dataform run --tags l3p_<target> --include-deps`.
- Business-unit tags (`["sales"]`) are optional. Use them for a unit's schedule and for its custom assertions.
- Use tags for scheduling only; don't put ownership or status in them.

## Names imposed by a target system

Some target systems fix their field names: an app API (`id`, `created_at`, `updated_at`), CRM logical names (`statuscode`, publisher-prefixed custom fields), or a .NET service that expects PascalCase. In L3P these names override the suffix rules. List them per schema in CLAUDE.md under "do not rename", and keep everything else in the model on convention. Inside the model, the CTE columns keep warehouse names; only the final select aliases them to the target's names.

L3R doesn't have imposed names. People read it, so use readable warehouse names there; the BI tool can relabel them for display.
