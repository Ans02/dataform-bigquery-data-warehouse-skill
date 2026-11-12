# <Organization> Warehouse Manifest

Inventory of Dataform models and their direct upstream lineage. Keep this file aligned with `definitions/`; list each model once and derive dependencies from its `ref()` calls.

| Layer | Schema | Model | Materialization | Grain | Purpose | Direct upstream models (`ref()`) | L3P target / L3R audience |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<layer>` | `<schema>` | `<model>` | `<view/table/incremental/...>` | <one row represents> | <one-line description> | `<schema>.<model>`, ... | <target or audience; otherwise -> |
