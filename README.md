# Intent integrity across web interfaces

Research code and recorded evidence for studying how web agents preserve a user's object, conditions, authorization and required result across UI and native WebMCP interactions.

## Start here

Python 3.12 or newer is sufficient for inspecting the recorded evidence. These commands use the standard library, require no credentials, and never call a model or launch an application:

```bash
python artifact.py verify
python artifact.py verify --section cart-replication
python artifact.py summarize --out analysis-paper
python artifact.py summarize --section cart-replication --out analysis-cart --group-by family mode policy
```

For an independent SQLite integrity check, add `--sqlite` to `verify`. To inspect the complete requests, responses, traces and persisted state for a cohort:

```bash
python artifact.py extract --cohorts component_ablation --out extracted-component
```

Extraction creates a new directory and preserves the evidence's relative paths. Outputs never overwrite the recorded corpus. Source and data hashes are distinct from hashes of the original, pre-anonymization records.

## Contents

| Location | Contents |
|---|---|
| `data/paper/` | 7,192 selected assignments in 28 cohorts from the supplied manuscript evidence registry, including technical errors |
| `data/cart-replication/` | Separate GPT/Claude replication: 576 research episodes and 12 compatibility episodes |
| `studies/real_apps/` | Real-application actor, intervention, scheduling and guard implementations recovered from the recorded source snapshots |
| `studies/cart_lifecycle/` | Portable WooCommerce fixture preparation, four study matrices, model launcher, 54 scripted controls and independent SQLite auditor |
| `studies/operation_binding/` | Additional receipt/consent studies: fixed matrices, bounded launcher, 12 native controls and independent state/report audits; source package, not a completed research corpus |
| Root `rq1_*`, `intent_*`, `program_*` | Earlier synthetic benchmark and tests; separate from the 7,192-trajectory manuscript corpus |
| `artifact.py` | Offline integrity verification, extraction and transparent all-cell score aggregation |
| `docs/` | Protocol overview, evidence schema, reproduction boundaries and upstream dependencies |

The paper's final selection can change independently of this frozen evidence snapshot. Cohorts remain separate; the repository does not pool them into a single model ranking or success rate. Compatibility episodes, pilots and scripted controls are not interchangeable with research assignments.

## Run the infrastructure tests

```bash
python -m pip install -r requirements.txt
python -m unittest discover -p 'test_*.py' -v
python studies/cart_lifecycle/replicate.py plan --config lifecycle-models.example.json
```

These commands contain no paid model calls. Browser-based controls additionally need Chromium/Edge with native WebMCP and, for WooCommerce, PHP with SQLite support. See reproduction instructions (`docs/REPRODUCTION.md`).

New model experiments are an explicit separate operation. Model IDs, HTTPS endpoints, credential environment variables, rates and provider-specific token caps are supplied in a local configuration copied from an example. No key, private endpoint, user session or deployed application is included.

See experimental design (`docs/PROTOCOL.md`), data format and anonymization (`docs/DATA.md`), and third-party dependencies (`docs/THIRD_PARTY.md`).

The publication audit is in `AUDIT_REVIEWED.json`. The earlier raw `CHECKS.json` flags a substring inside an opaque provider signature; review confirmed that it is not author metadata. The recorded evidence bytes were retained.

## Additional operation-binding studies

Follow [the complete execution guide](https://github.com/Dentikka/web-agent-intent-integrity/blob/main/docs/RUN_BINDING.md) and [fixed protocol](https://github.com/Dentikka/web-agent-intent-integrity/blob/main/studies/operation_binding/PROTOCOL.md). For each configured model, the default programme has 48 receipt episodes, 64 consent episodes and two compatibility episodes: **224 research + 4 compatibility = 228 episodes for two models**. The same portable WooCommerce runtime is reused. Native controls and planning require no model calls:

```bash
python studies/operation_binding/run.py plan --config operation-binding-models.example.json
```

The guide includes fixture preparation, model/provider configuration, a spending cap, selftests, execution, offline analysis and archival requirements. No completed GPT/Claude research outcomes from these new studies are claimed or merged into the archived corpora. New paid execution requires explicit operator authorization and verified billing settings.
