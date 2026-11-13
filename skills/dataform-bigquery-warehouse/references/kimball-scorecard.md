# Kimball scorecard

The scorecard measures how closely a Dataform warehouse, or a single model, follows Ralph Kimball's dimensional modeling: *The Data Warehouse Toolkit* and the Kimball Group's design tips. Use it when someone asks for a score, a grade, an audit or a maturity assessment ("how Kimball is our warehouse?"), or wants a structured review of a model.

## Contents

1. Scale and grades
2. Scoring the warehouse
3. Repository criteria (R1–R16)
4. Model criteria (M1–M15)
5. Kimball in this playbook
6. Report template

## 1. Scale and grades

- Each criterion scores **0** (missing or violated), **1** (partly met, or met by only some models) or **2** (met). A criterion that doesn't apply is left out of the score.
- Weights: **3** critical, **2** important, **1** good practice.
- **Score % = Σ(score × weight) / Σ(2 × weight) × 100**, over the criteria that apply.
- Coverage criteria use fixed thresholds: 2 when at least 90% of the models in scope meet the criterion, 1 for at least 50%, 0 below that.

| Grade | Score | Meaning |
| --- | --- | --- |
| A | 90–100 | Kimball-compliant |
| B | 75–89 | Solid, with gaps |
| C | 60–74 | Dimensional in parts |
| D | below 60 | Not yet dimensional |

**Critical gate:** if any critical criterion scores 0, the grade is capped at C, whatever the percentage. Kimball treats grain and conformed dimensions as preconditions, not as nice-to-haves.

## 2. Scoring the warehouse

1. **Run the scan.** It's read-only and needs only Python 3, with no packages and no BigQuery access:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/kimball_scan.py" <repo>
   ```

   The script is in this skill's `scripts/` folder. Options: `--all` lists every model, `--model <name>` checks one model, `--json` gives machine-readable output, and `--fail-under <pct>` makes CI fail below a threshold. The scan scores ten criteria automatically (R1–R4, R7, R9, R13–R16). It also lists the dimensions built in several schemas and the calendars, and generates the **bus matrix** from the code, so the bus matrix never needs maintaining by hand.
2. **Confirm the automatic scores.** The checks are regex heuristics. Open two or three flagged models per criterion. If a heuristic is wrong, override the score and cite the evidence.
3. **Score the review criteria** (R5, R6, R8, R10, R11, R12) by sampling at least five facts and five dimensions across business units. Prefer the dimensions the bus matrix shows as most used. Cite `file:line` for every judgment.
4. **Ask before guessing** where the code can't settle it: whether two same-named dimensions are really different entities (R3), which attributes the business needs history for (R11), and whether a measure is additive when the source doesn't say (R8).
5. **Compute the score**, apply the critical gate, and report it with the template in section 6.
6. **Rank the improvements** by the points each would gain: (2 − score) × weight. Break ties by effort, cheapest first.
7. **Keep a record only if asked.** To track progress, save the report under `docs/` with its date and commit, and compare later scans against it. The `--json` output is stable enough to diff.

## 3. Repository criteria

The scope is the L2 models plus the L3R presentation views. L3P tables are machine-to-machine contracts outside Kimball's presentation area, so they aren't scored. The total weight is 32, for a maximum of 64 points.

| ID | Criterion | Kimball principle | Weight | 2 when … (1 = partly, 0 = not) | Scan |
| --- | --- | --- | --- | --- | --- |
| R1 | Grain declared | Step 2 of the four-step design: declare the grain before choosing dimensions and facts | 3 | ≥ 90% of L2 `dim_`/`fct_`/`rel_`/`kpi_` models state their grain in a header comment | auto |
| R2 | Grain enforced | The declared grain is a unique key | 3 | ≥ 90% of those models assert `uniqueKey` on the grain | auto |
| R3 | Conformed dimensions | Enterprise bus architecture: one dimension per entity, shared by every fact; shrunken dimensions keep the keys | 3 | No entity is modeled as independent dimensions in several schemas. Copies derived from `l2_masterdata` are fine | proposed |
| R4 | Unknown-member rows | Default rows, so that fact foreign keys never need NULL | 2 | ≥ 90% of dimensions have a global `na` row. A scoped default member (such as sector 0 "Default") doesn't replace it: facts with an unknown parent still need `na` | auto |
| R5 | Fact foreign keys never null | Every fact row joins to every dimension | 3 | In the sampled facts, every foreign key is coalesced to the unknown member, and a query shows no NULL keys | review |
| R6 | Surrogate keys | Dimensions use meaningless surrogate keys; natural keys stay as attributes | 2 | One key strategy across the repository, fitting the system. Every sampled dimension has a hashed `_sk` key and keeps its natural/source key (`_id` or `_cd`); facts carry surrogate `_sk` keys | review |
| R7 | One conformed date dimension | A single date dimension; role-playing views for several dates | 2 | Exactly one calendar generates dates; fiscal and unit calendars are derived from it | auto |
| R8 | Fact types and additivity | Transaction, periodic snapshot, accumulating snapshot or factless; additive, semi-additive and non-additive measures | 2 | Every sampled fact is a single type, stated in its header; semi- and non-additive measures (balances, ratios) are documented, and ratios are stored as numerator and denominator | review |
| R9 | Aggregates on atomic facts | Aggregates complement the atomic grain; they never replace it | 2 | Every `kpi_` model is built from a `fct_` model | auto |
| R10 | Star, not snowflake | Denormalized dimensions; hierarchies flattened; outriggers rare | 1 | Sampled dimensions carry their hierarchy levels as columns, and facts join dimensions directly | review |
| R11 | Slowly changing dimension policy | SCD type 1 overwrites, type 2 adds history rows with valid-from/to and a current flag | 2 | Each sampled dimension states which attributes keep history, and history exists where the business reports "as it was" | review |
| R12 | Bridges for many-to-many | Bridge tables with a weighting factor | 1 | Every many-to-many relationship goes through a `rel_` model; weights sum to 100 per group, enforced by an assertion | review |
| R13 | Naming conventions | Consistent, business-friendly names | 1 | ≥ 90% of column aliases carry a valid suffix, and ≥ 90% of L2 models a `dim_`/`fct_`/`rel_`/`kpi_` prefix | auto |
| R14 | Presentation area for people | Business users query star schemas, never the staging area | 1 | Every L3R model reads only L2 and L3R | auto |
| R15 | Data-quality screens | The data-quality screens of Kimball's ETL subsystems | 2 | ≥ 90% of typed L2 models have assertions, and at least one custom cross-row assertion exists | auto |
| R16 | Documentation | Business metadata for the people who use the data | 2 | ≥ 90% of L2 and L3 models are in `docs/glossary.md` | auto |

The critical criteria are R1, R2, R3 and R5.

## 4. Model criteria

Use these to score a single model in a review. Score only the criteria that apply to the model's kind. `--model <name>` prints the scan's evidence for that model.

| ID | Criterion | Applies to | Weight | 2 when … |
| --- | --- | --- | --- | --- |
| M1 | Grain declared | all | 3 | A header comment states one row = … in business terms |
| M2 | Grain enforced | all | 3 | `uniqueKey` asserts exactly the declared grain |
| M3 | One grain only | fct, kpi, rel | 3 | No total rows, and no union of different grains without a discriminator column |
| M4 | Business process and owner | fct | 1 | Measures a single business process, and lives in the schema of the unit that owns it |
| M5 | Foreign keys never null | fct, rel | 3 | Every foreign key is coalesced to the unknown member |
| M6 | Fact type and additivity | fct, kpi | 2 | The header states the fact type; non-additive measures are flagged, and ratios are stored as their parts |
| M7 | Lean facts | fct | 1 | Only keys, measures and degenerate dimensions (document numbers); descriptive text lives in dimensions |
| M8 | Keys and unknown row | dim | 3 | A surrogate `_sk` key, the natural/source `_id` kept as an attribute, and a global `na` row |
| M9 | Descriptive attributes | dim | 2 | Codes are decoded into `_ds` labels, `_long_ds` exists for pickers, and hierarchy levels are flattened into columns |
| M10 | Conformed | dim | 3 | It is the hub dimension, or derived from it with the same keys |
| M11 | SCD policy | dim | 1 | The header says which attributes keep history (type 2) and which are overwritten (type 1) |
| M12 | Bridge weights | rel with weights | 2 | Weights sum to 100 per group, and an assertion enforces it |
| M13 | Atomic source | kpi | 2 | Built from an atomic `fct_` model |
| M14 | Naming | all | 1 | The model's prefix is right, and every column has a valid suffix |
| M15 | Glossary | all | 1 | The model and its business terms are in `docs/glossary.md` |

Critical for the gate: M1, M2, M3, M5, M8 and M10.

## 5. Kimball in this playbook

| Kimball concept | In this playbook |
| --- | --- |
| Four-step design: business process, grain, dimensions, facts | The schema of the owning business unit, the grain comment, `dim_` and `fct_` models |
| Bus architecture, conformed dimensions | The `l2_masterdata` hub; the scan's bus matrix |
| Surrogate keys | Hashed `_sk` keys from one strategy per repository (`includes/keys.js`). `farm_fingerprint` gives Kimball's integer keys; `md5_hex` trades width for portability when keys leave BigQuery |
| Unknown and default members | The `na` sentinel row; scoped default members (keys-and-sentinels.md) |
| Bridge tables with weighting factors | `rel_` models with a `percent` weight and an assertion |
| Aggregate fact tables | `kpi_` models |
| Presentation area | L3R. L3P tables are integration contracts outside Kimball's presentation area |
| Periodic and accumulating snapshots | The change-capture stack and booking curves (modeling-patterns.md) |
| Audit and ETL metadata | `l2_monitoring` facts and the refresh heartbeats |
| Data-quality screens | Built-in and custom assertions |

Where this playbook deliberately differs from Kimball, don't deduct points:

- **Hashed string keys are a valid choice.** Kimball prefers integer surrogate keys for join performance. `farm_fingerprint` gives INT64 keys on BigQuery, while `md5_hex` trades width for portability when keys leave BigQuery, and neither needs a key-lookup step. Score R6 on whether the strategy is consistent, meaningless and right for the system, not on the key type.
- **History on demand.** Kimball builds type 2 history broadly. Here history is added where the business reports "as it was". Score R11 on whether the policy is declared and fits the business, not on how many type 2 dimensions exist.

## 6. Report template

```markdown
## Kimball score: <repository or model>: <NN>% (grade <A–D>)

Scope: <repository or model>, commit <sha>, <date>. Automatic scan subtotal: <NN>%.

| ID | Criterion | Weight | Score | Evidence |
| --- | --- | --- | --- | --- |
| R1 | Grain declared | 3 | 0 | 3 of 104 typed L2 models declare their grain (scan) |
| R5 | Fact foreign keys never null | 3 | 2 | 6 sampled facts, every key coalesced: fct_invoice.sqlx:32, … |
| … | | | | |

Critical gate: <passed | grade capped at C because R1 scored 0>.

### Biggest gains

1. <criterion>: <concrete action> (+<points> points)
2. …

### Bus matrix

<from the scan>
```
