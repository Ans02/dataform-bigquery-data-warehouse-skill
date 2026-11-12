# Review checklist

Report each finding with its severity, `file:line`, a concrete failure (this input → this wrong output) and the fix. If the user wants a score or a grade rather than a list of findings, use the model criteria of kimball-scorecard.md.

- **High**: wrong numbers, lost or duplicated rows, a broken L3P contract, nondeterministic keys.
- **Medium**: layer or dependency violations, a grain without an assertion, fragile joins.
- **Low**: naming, style, comments.

## Placement and dependencies

- [ ] The model sits in the right layer and schema. Its folder is the schema suffix, and its file name equals its `name`.
- [ ] An L2 model is in the schema of the business unit that owns the process behind it. Shared entities are in `l2_masterdata`, and cross-unit mappings are in `l2_relationship`.
- [ ] An L3 model is in L3P only if a program reads it, and in L3R only if people read it. When both read the data, each has its own model.
- [ ] It reads only from the layer below (L2 may also read L2). L3 doesn't read L1 or declarations without a documented reason.
- [ ] An L1 model reads exactly one raw table and contains no business logic.
- [ ] Every reference uses `ref({schema, name})`; there are no hardcoded `project.dataset.table` paths.
- [ ] No cycle is introduced. Derived values that depend on facts live downstream.
- [ ] No mapping logic is duplicated from an existing `rel_` model.

## Naming

- [ ] The table prefix fits (`dim_`, `fct_`, `rel_`, `kpi_`); L3P uses the target system's names.
- [ ] Every new column in L2 and above has the right suffix and an English name.
- [ ] Join-key columns have the same name and type as on the other side.
- [ ] Names imposed by a target system are untouched.

## Keys and sentinels

- [ ] Keys are hashed with `to_hex(md5(cast(... as string)))`, with the `md5('nd')` null fallback in L1.
- [ ] Every part of a composite key is coalesced. Separators appear where parts could run together, and namespaces where id spaces overlap.
- [ ] No `current_date()`, `current_timestamp()` or random value appears in a key or a sentinel row.
- [ ] Every foreign key is coalesced to `md5('na')`.
- [ ] Each dimension has one sentinel row, built with `union all strict corresponding` or as a typed sentinel.
- [ ] Every placeholder has the right kind (keys-and-sentinels.md, "Kinds of sentinel"). A source's catch-all inside a parent (such as sector `0` "Default") is a scoped default member with a parent-scoped key, not `md5('na')`. Facts fall back to the parent's default before `na`. Unmapped values aren't poured into an `'Other'` category.
- [ ] L3P filters out `na` sentinels and keeps default members.
- [ ] Neutral defaults that change totals (`coalesce(percent, 100)`) are commented and match the other models that use the same weights.

## Joins and grain

- [ ] The grain is stated in a comment, and `uniqueKey` matches it.
- [ ] Each join returns at most one row per left row, or the multiplication is intended and commented.
- [ ] Enrichment sources are deduplicated before the join.
- [ ] No full outer join is neutralized by a later `where` or inner join.
- [ ] Validity-window joins can't overlap, and they compare on the documented event date.
- [ ] Cumulative "as of" joins use `<=`.
- [ ] Higher-grain attributes repeated at a lower grain are commented and never summed.
- [ ] Bridges report trivial matches (single member, default member) separately from real ones.

## Logic

- [ ] Every filter, exclusion and hardcoded value has a comment saying why. Hardcoded ids live in `includes/constants.js`.
- [ ] Business rules, thresholds, exclusions, field meanings and L3P field names trace back to a source (a spec, the owner, the data, CLAUDE.md), not to a guess. Anything unconfirmed is an explicit `TODO` and listed as an open question.
- [ ] `row_number()` orderings are deterministic, and the NULL ordering is intended.
- [ ] NULL handling is explicit: `coalesce(x = 'y', false)` for flags, `nullif` for placeholders, `safe_cast` and `safe_divide` where the input can be dirty.
- [ ] `union distinct` isn't hiding duplicates that should be fixed.
- [ ] Relative date logic (`current_date()`) is acceptable for the materialization.
- [ ] Signs, units and scales (cents vs. euros, 0–1 vs. 0–100) are consistent with the neighbouring models.

## Assertions and verification

- [ ] `uniqueKey` is set on the grain, and `nonNull` and `rowConditions` wherever consumers need them.
- [ ] Each cross-row invariant has a custom assertion with a comment saying why.
- [ ] The author shows evidence: row and distinct-key counts, fan-out checks, totals against the source, and a whole-table reconciliation wherever rows fan out.

## Targets and audiences

- [ ] L3P models are tagged, materialized as tables, cast to the target's types, and mirror the target's constraints. Each says whether it holds current state or history.
- [ ] An L3P change that renames, removes or retypes a column was agreed with the target's owner.
- [ ] L3R models are thin and scoped, and the heartbeat is updated when a model is added.
- [ ] If a column was renamed or removed, everything downstream was found and updated: grep for the column across `definitions/`.

## Materialization and cost

- [ ] View, table or incremental fits the situation (see the table in SKILL.md).
- [ ] For incremental models, the incremental and full-refresh branches give the same result, and `uniqueKey` is set only when a merge is intended.
- [ ] Large tables are partitioned and clustered on the filter columns. Nothing beyond L1 runs `select *` on a wide external table.

## Glossary

- [ ] `docs/glossary.md` is updated in the same change, in the sections that references/glossary.md names for each kind of change. If the commit says `Glossary: unchanged` instead, that's true: the change is a pure refactor, formatting or comments.
- [ ] Removed models, columns and codes are removed from the glossary too, and fixed pitfalls are removed from §10.
- [ ] New column names reuse the English terms from the glossary (§4) instead of introducing synonyms.

## Style

- [ ] The model matches its neighbours: lowercase, leading commas, 2-space indent, aligned aliases, a `final` CTE.
- [ ] There is no commented-out code without a reason, and no leftover debugging filter (`--where id = ...`).
