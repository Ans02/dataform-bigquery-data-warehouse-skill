# The repository glossary

Every warehouse repository keeps one glossary, `docs/glossary.md`. It explains, in plain language, what the warehouse contains and what its names mean: layers, sources, business terms, codes, measures, every L2 and L3 object, and the names that mislead. It describes **what the SQL does now**, not what it was meant to do.

The glossary is only useful if it is current. **A change isn't done until the glossary matches it**, and that includes every commit. The template is `assets/templates/docs/glossary.md`.

## Contents

1. Structure
2. Read it before you work
3. Update it with every change
4. Before every commit
5. Writing entries
6. Full reviews
7. Data dictionary and Manifest

## 1. Structure

| Section | Holds |
| --- | --- |
| 1. Architecture and layers | The layer table, every L2 schema with its business unit, every L3 schema with its target system or audience |
| 2. Source systems | Every source: L1 schema, what the system is, its main data, load cadence |
| 3. Naming conventions | Prefixes, suffixes, the key formula, sentinel values, and any local deviation from the conventions |
| 4. Business glossary (source language → English) | One row per business term, grouped by business unit: the term, its language, the English word used in column names, notes |
| 5. Codes and enumerations | Every code list the SQL decodes or relies on (status codes, type codes, option sets), plus hardcoded ids worth knowing |
| 6. Calendar and period flags | Calendar flags and how they're computed, fiscal calendars, period pickers, data-release cut-offs |
| 7. Measures by business unit | Every measure column: its meaning, its source field, its unit and its sign |
| 8. L2 object catalogue | Per L2 schema, one row per model: type (view/table/incremental), grain, description |
| 9. L3 object catalogue | Per L3 schema, one row per model: reader (program or people), grain, description, fixed field names |
| 10. Pitfalls: names that mislead | Every place where the SQL does something other than its name suggests |

A repository can add sections, but it keeps these ten and their order, so people and agents always know where to look.

## 2. Read it before you work

Before naming, modeling or reviewing, read the sections the task touches:

- Naming a column: §4 holds the English word for each source term. Reuse it; don't invent a synonym.
- Decoding a code or a status: §5. If the code list isn't there and the data doesn't settle it, ask.
- Adding a measure: §7, for the same measure computed elsewhere and its sign and unit conventions.
- Placing a model: §1 and §8, for the business unit that owns the process and for models that already exist.
- Reviewing: §10, for traps that already exist.

When the glossary and the SQL disagree, the SQL is the truth: fix the glossary in the same change. If you can't tell which one is wrong, ask.

## 3. Update it with every change

Update the glossary in the same change as the code, not in a later clean-up:

| Change | Update |
| --- | --- |
| A source or declaration is added, renamed or removed | §2 |
| An L2 schema or business unit, or an L3 schema, target or audience, is added or changed | §1, and §8 or §9 |
| A model is added, renamed, removed, or changes type, grain or purpose | §8 or §9 |
| A column is added or renamed using a business term that isn't in §4 yet | §4 |
| A measure is added, or its meaning, unit or sign changes | §7 |
| A code mapping (`case` on codes), a status rule or an enumeration is added or changed | §5 |
| A hardcoded id is added to `includes/constants.js` | §5, "hardcoded ids" |
| A calendar flag, fiscal rule or release cut-off is added or changed | §6 |
| A naming convention or a sentinel kind changes | §3 |
| You find a misleading name or surprising behaviour | §10 |
| A pitfall gets fixed | Remove it from §10 |
| An L3P field name imposed by a target changes | §9 (and the "do not rename" list in CLAUDE.md) |
| Something is removed | Delete its entries. A stale entry is worse than a missing one |

Pure refactors, formatting, comments and test-only changes usually need no glossary update. Decide that deliberately; don't assume it.

## 4. Before every commit

Run this for every commit that touches `definitions/` or `includes/`:

1. List the changed files: `git diff --cached --name-only` (or `git diff HEAD --name-only` for `git commit -a`).
2. Read the diff of each changed model and walk through the table in section 3. Look in particular for new or renamed columns, new `case` mappings, new filters and exclusions, changed grains, and new or removed models.
3. Update `docs/glossary.md` and stage it with the change.
4. If nothing in the change belongs in the glossary, say so explicitly. With the plugin's commit hook (below), add the trailer `Glossary: unchanged` to the commit message.
5. In the commit message or the PR description, mention which glossary sections changed.

The plugin ships a commit hook that enforces this when Claude commits. It blocks a `git commit` that changes files under `definitions/` or `includes/` without staging `docs/glossary.md`. The commit goes through once the glossary is staged, or once the message carries the `Glossary: unchanged` trailer. The hook does nothing in repositories without `docs/glossary.md`. Commits made outside Claude aren't covered; for those, the review checklist asks for the glossary.

## 5. Writing entries

- One term, code or object per row. Give its column, model or code in backticks, so people can search for it.
- Business terms: give the source-language term, its language, the English word used in column names, and a note on where it appears (`dim_branch`, `branch_cd`).
- Codes: give every value with its meaning, and the model that decodes it. When the SQL maps unknown values to a fallback (`else 'Not Assigned'`), say so.
- Measures: give the meaning, the source field, the unit, and the sign (credit notes negative?). If a column's suffix contradicts its content (a `_qt` column holding money), the column also goes in §10.
- Objects: give the type, the grain in a few words, and a one-line description. Use the grain from the model's header comment.
- Pitfalls: say where, what the name suggests, and what the SQL actually does. Date the section ("as of <date>").
- Write for a newcomer: short sentences and no unexplained abbreviations. Business-unit jargon goes in §4, not in the descriptions.
- Never copy secrets, personal data or real customer values into the glossary. Codes and ids of test records are fine.

## 6. Full reviews

Per-change updates drift over time. Every few months, or after a large refactor, compare the whole glossary with `definitions/`:

- every model in §8 and §9 exists, and every model in `definitions/l2` and `definitions/l3*` is listed;
- the code lists in §5 match the `case` expressions in the SQL;
- the pitfalls in §10 still exist.

Record the date and branch at the top ("Last full review: <date>, against `main`").

## 7. Data dictionary and Manifest

The glossary is complemented by two repository documents:

- `docs/data-dictionary.md` describes every L3P and L3R output model and column, including the model's grain and purpose, column types, business descriptions, synonyms, and verified examples, allowed values or constraints where applicable. Keep it aligned with the Dataform descriptions and column metadata.
- `docs/manifest.md` is the inventory and direct-lineage index for every Dataform model. Record its layer, schema, name, materialization, grain, purpose and direct upstream `ref()` dependencies; include the L3P target or L3R audience where applicable.

Create either file from its template in `assets/templates/docs/` if it is missing, and populate it from the actual models. Before every commit, compare the staged diff with both documents. Update and stage a document in the same change when its contents are affected; leave it unchanged when the change does not affect it. Never guess metadata or include sensitive real-world example values.
