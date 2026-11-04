# Reproduction

## 1. Inspect recorded results without external services

From the repository root, use Python 3.12+:

```bash
python artifact.py verify
python artifact.py verify --section cart-replication --sqlite
python artifact.py summarize --out analysis-paper --group-by app policy timing
python artifact.py summarize --section cart-replication --out analysis-cart --group-by family mode policy
```

`verify` checks all archive/file hashes, assignment uniqueness, cohort counts and recorded technical-error counts. `--sqlite` additionally checks every included SQLite database read-only. It is an integrity check, not a guarantee that every historical scientific interpretation is correct. The summarizer preserves metric-specific denominators and all recorded errors; case interpretation still requires the selecting request and persistent record.

```bash
python artifact.py extract --section cart-replication --out extracted-cart
python artifact.py extract --cohorts handoff_core --out extracted-handoff
```

After extraction, the cart study's independent auditor can compare native saved sessions and order lines with backend JSON, without running PHP or a model:

```bash
python studies/cart_lifecycle/verify_drift_databases.py extracted-cart/artifacts/cart_lifecycle_replication_v1/runs/MODEL_DIRECTORY/paid
```

Use the actual model directory listed under the extracted `runs` directory. The auditor writes a new `DATABASE_AUDIT.json` beside the extracted copy, never into the source archives.

## 2. Test the synthetic and portable cart infrastructure

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -p 'test_*.py' -v
python rq1_runner.py plan --config rq1-models.example.json
python program_runner.py plan --config program-models.example.json
python studies/cart_lifecycle/replicate.py plan --config lifecycle-models.example.json
```

Plan commands do not read keys or send API requests. Browser selftests require native WebMCP support; this does not mean the browser's ordinary Playwright `evaluate` API is itself WebMCP. The cart actor discovers and invokes page-registered native tools in a fresh browser context.

The artifact CI uses Ubuntu 24.04 and Python 3.12 explicitly. Browser/application installation uses public downloads; its job allowance includes those downloads as well as native controls. Experiment deadlines and API spending caps are configured separately.

For a new WooCommerce fixture, install PHP CLI with PDO SQLite, mysqli and mbstring. On Debian/Ubuntu these are `php-cli php-sqlite3 php-mysql php-mbstring`. The following downloads pinned official application packages into a new directory and creates a synthetic database:

```bash
python studies/cart_lifecycle/prepare_runtime.py --download-runtime runtime --out fixture
```

It requires network access for public downloads, but no Docker, MySQL server, API key or production account. Mail and outbound HTTP from the application are disabled. Existing fixture directories are never overwritten.

Copy `lifecycle-models.example.json` to a local ignored configuration. Set `workspace` to the absolute repository directory, `runtime_wp_site` to the resulting `runtime/wordpress`, `base_database` to `fixture/state.sqlite`, and `php_binary` to the PHP executable. Linux uses installed Chromium with `browser_channel` set to an empty string; on Windows an installed compatible Edge can use `browser_channel: "msedge"`.

```bash
python studies/cart_lifecycle/replicate.py selftest --config lifecycle-local.json --out cart-controls
```

This runs 54 scripted controls, with no model calls. It verifies native cart/order semantics, price scope, handoff synchronization, resynchronization and queued autosave behavior.

## 3. Configure an explicit new model replication

Each model object contains an exact served `id`, a Chat Completions compatible HTTPS `base_url`, a `key_env` or `key_file` reference, current input/output rates per million tokens, a provider-enforced output cap and any provider-specific body fields. The example's zero rates and unverified byte/token bound intentionally prevent a paid run until configured. Do not put a key value into a JSON file committed to Git.

The launcher shares a total budget of at most USD 20 and a deadline of at most eight hours across the chosen models/stages. Per-model budgets can be explicit and must sum to no more than the total. These are launcher limits, not a prediction of a provider's billing. Unknown billing reservations stop further stages. Verify rates, model IDs and supported token parameters with the actual provider before enabling calls.

After explicitly configuring credentials and deciding to incur API usage:

```bash
python studies/cart_lifecycle/replicate.py run --config lifecycle-local.json --out new-cart-study
python studies/cart_lifecycle/replicate.py analyze --out new-cart-study
```

Default order runs compatibility episodes for all models before the research matrices. Refusal analysis keeps unreviewed text labels unknown; inspect the generated annotation template. New observations must not be relabeled as the archived results.

The archived GPT/Claude cart replication used the additional provider transport adaptation in `studies/cart_lifecycle/recorded-transport.patch`: custom authorization headers and unwrapping a gateway response while excluding its account key. This changes provider transport only. The public portable client is retained; the patch documents the difference in the recorded execution rather than claiming byte-identical transport.

## 4. Real-application manuscript studies

`studies/real_apps/src` and `scripts` retain the actor/intervention dependency closure used by the recorded Medusa, EasyAppointments and cross-catalog studies. Modules missing from the received top-level source tree were recovered from its identical frozen worker snapshots. The cross-catalog actor imports the portable cart closure instead of a duplicated private source directory.

These historical multi-worker launchers are reference implementations, not a turnkey installer: they expect pinned WindTunnel capsules, prepared SQL fixtures, dedicated container names, plans and original browser connections. Some read historical plans at import time. Running a script merely because its filename starts with `run_` is not an offline verification step. Recreate dedicated local fixtures and new plans before adapting a launch; do not target production services or try to reuse an original user's filesystem paths.

The supplied artifact does not distribute container images or claim that the entire 7,192-assignment application stack can be launched with one command. Offline evidence inspection and the standalone cart reproduction above are independently usable. Exact requests, tool schemas, interventions and persistent outcomes for the registered assignments are included even where rebuilding the original container environment requires additional upstream installation.

## 5. Additional receipt and consent studies

The [operation-binding execution guide](https://github.com/Dentikka/web-agent-intent-integrity/blob/main/docs/RUN_BINDING.md) provides a complete separate path using the same WooCommerce runtime. It includes [a frozen protocol](https://github.com/Dentikka/web-agent-intent-integrity/blob/main/studies/operation_binding/PROTOCOL.md), [model-list example](https://github.com/Dentikka/web-agent-intent-integrity/blob/main/operation-binding-models.example.json), 12 native scripted controls, a bounded launcher and offline state/report auditing. The default workload is 112 research and two compatibility episodes per model. Completed research results for these additional studies are not part of the archived snapshot.

```bash
python studies/operation_binding/run.py plan --config operation-binding-models.example.json
```

For actual preflight, copy the example into `binding-local.json` and set the clean runtime/fixture paths described above. No key or nonzero model pricing is needed for mechanical controls:

```bash
python studies/operation_binding/run.py selftest --config binding-local.json --out binding-controls
```

Do not resume historical runs using this publication snapshot: translated documentation and anonymized metadata produce a different source closure. Use a fresh output root for new research; keep original frozen sources with archived evidence.
