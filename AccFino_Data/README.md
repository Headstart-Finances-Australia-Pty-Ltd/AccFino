# AccFino_Data  (ACCFINO_DATA_ROOT)

Persistent business data and documents. **Not part of the application package.** Point the application at this folder with

    ACCFINO_DATA_ROOT=/path/to/AccFino_Data        (Docker / Northflank: mount a volume at /data and set ACCFINO_DATA_ROOT=/data)

If the variable is not set the application uses `<folder next to AccFino>/AccFino_Data`.

```
reference/            chart of accounts, knowledge base, RDR rules, pricing, companies, lending rules (edited at runtime)
config/               runtime integration settings (integrations.json - may hold credentials: keep private, never commit)
legal/                legal documents served by the website (PDF)
shared/ml_models/     trained classifier models
shared/llm_cache/     LLM answer caches
modules/<module>/     per-module files: trading/{inputs,output,cost_base}, cashflow/outputs, open_banking/exports, reconciliation/sessions
```

Read-only first-run defaults ship in `AccFino/deploy/data-seed/` and are copied here only when a file is missing - existing files are never overwritten.
Test datasets are separate: see `AccFino_Testing/testdata` (ACCFINO_TEST_DATA_ROOT).
