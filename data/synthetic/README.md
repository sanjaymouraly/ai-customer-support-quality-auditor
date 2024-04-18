# Synthetic scenario dataset

`cases.json` contains 170 fictional support scenarios across 18 categories. Each row has a stable case ID, category, customer request, fictional context facts, active-policy IDs, candidate response, expected actions and escalation, severity, synthetic reference disposition, notes, and evaluation metadata. No real customer records are used.

Reference labels are synthetic design expectations, not human review. `evaluation_metadata.dataset_split` is `development_benchmark`; rule behavior was inspected on this dataset during development. The data is suitable for offline demos, schema validation, QA regression tests, and annotation practice—not as a generalizable accuracy claim or an unbiased holdout.

See `docs/annotation_guidelines.md` for provenance and human-labeling workflow.
