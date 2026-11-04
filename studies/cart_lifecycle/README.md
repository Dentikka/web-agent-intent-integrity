# Native cart lifecycle studies

Portable entrypoints: `replicate.py plan`, `selftest`, `run`, and `analyze`. See the root reproduction guide (`../../docs/REPRODUCTION.md`) and model-list example (`../../lifecycle-models.example.json`).

The fixed research matrices contain 120 form/saved-cart episodes, 48 price-scope episodes, 96 handoff episodes and 24 autosave episodes per model. Six compatibility episodes per model are separate. The native preflight has 54 scripted controls and makes no model calls.

`prepare_runtime.py` downloads pinned public WordPress/WooCommerce/SQLite integration packages and prepares a new synthetic fixture. PHP CLI and a compatible native-WebMCP browser are required; Docker and a MySQL server are not.

The native `Surface` has a small historical support dependency closure (`rq1_*`, `intent_*`). Use `replicate.py` as the study entrypoint. `verify_drift_databases.py` checks captured SQLite records independently of PHP and model outputs. The meaning analyzer does not count an unreviewed no-order result as a correct refusal.
