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
| `_id` | Natural or source identifier | Source type, usually STRING or INT64 | `customer_id`, `stripe_charge_id` |
| `_sk` | Warehouse-generated hashed/integer surrogate key, computed with the repository's key strategy (`includes/keys.js`) | STRING or INT64, depending on the strategy | `customer_sk`, `date_sk` |
| `_cd` | Business code: ISO codes, postal codes, category codes | STRING (INT64 only for truly numeric codes) | `country_cd`, `postal_cd`, `category_cd` |
| `_ds` | Description or label | STRING | `customer_ds`, `street_ds` |
| `_long_ds` | Display label `code - description` | STRING | `customer_long_ds` |
| `_dt` | Date or timestamp | DATE / TIMESTAMP | `entry_dt`, `document_dt`, `update_dt` |
| `_fl` | Boolean flag | BOOL (INT64 0/1 if the BI tool sums flags) | `active_fl`, `latest_fl` |
| `_num` | Assigned number or label/code, not a count | STRING or numeric | `customer_num`, `invoice_num`, `tracking_num`, `phone_num` |
| `_qty` | Quantity | INT64 / NUMERIC | `room_qty`, `returned_qty` |
| `_cnt` | Count (use `_count` when readability matters more than brevity) | INT64 | `login_cnt`, `item_cnt` |
| `_amt` | Amount (use `_amount` when readability matters more than brevity) | NUMERIC / FLOAT64 | `gross_amt`, `refund_amt` |
| `_pct` | Percentage | FLOAT64 / NUMERIC | `discount_pct`, `tax_pct` |
| `_ytd`, `_mtd`, `_qtd` | Year-, month- or quarter-to-date measure | Type of the measure | `revenue_ytd`, `spend_mtd` |
| `_utc` | Coordinated Universal Time | TIMESTAMP or DATETIME | `created_at_utc` |
| `_url`, `_uri` | URL or URI | STRING | `landing_page_url`, `avatar_uri` |
| `_ip` | IP address | STRING | `client_ip`, `signup_ip` |
| `_os` | Operating system | STRING | `device_os`, `os_version` |
| `_geo`, `_lat`, `_lon` | Geographic value, latitude or longitude | GEOGRAPHY / FLOAT64 | `store_geo`, `store_lat`, `store_lon` |

Rules:

- A column name is `<entity or measure>_<qualifier>_<suffix>`: `invoice_recipient_ds`, `gross_amt`. Use `avg_`, `min_` and `max_` as prefixes for summary statistics (`avg_order_value`, `max_login_at`).
- `_id` names natural/source identifiers; `_sk` names warehouse surrogate keys. Never use `_id` for a generated hash. Do not add `pk` or `fk` when `_id` or `_sk` already identifies the key role; use those labels only when a consumer specifically requires them.
- Choose one convention per concept and keep it repository-wide. A column used as a join key across models has the same name and type everywhere.
- Flags: choose BOOL or 0/1 per table and never mix the two within a table. Document INT64 flags, because `where latest_fl` fails on an INT64.
- Percentages: say in a comment whether `_pct` runs from 0 to 1 or from 0 to 100.
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
