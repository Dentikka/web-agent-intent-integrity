# Recorded evidence

Each dataset section contains:

- `trials.csv`: one row per registered assignment, cohort, source result path, original-result hash when supplied, artifact hash and recorded error field.
- `index.json`: cohort counts, evidence-file count and SHA-256 of every ZIP shard.
- `files.json`: exact path, shard, received-byte hash, exported-byte hash and size for each evidence file.
- Cohort ZIP shards: result, task specification, available prompts, requests/responses, trace, events, backend snapshots and native SQLite captures associated with every registered episode.

`data/cart-replication/models.json` records the served IDs and non-secret generation settings associated with its two model directories. Historical billing rates in this metadata are provenance, not current pricing recommendations.

`recorded-analyses.zip` and its `support.json` index retain the supplied aggregate analyses, database-audit reports and reviewed text annotations. Full extraction includes these files. They are recorded supporting outputs, not extra assignments; their historical source/database hashes can differ from the publication export hashes.

The manuscript's supplied registry describes 7,192 assignments in 28 cohorts. The cart replication is a separate corpus of 588 episodes; its smoke cohort is explicitly labeled. Neither dataset includes the earlier exploratory Flash trials as evidence for GPT or Claude.

`studies/operation_binding/` is an additional source package, with no completed GPT/Claude research dataset in this snapshot. Its 224 planned research episodes for two models are not observations and are not added to either registry. Technical validation does not establish a policy benefit or a research effect.

## Export scope

The publication tree omits installed application/runtime bundles, caches, worker console logs, screenshots, local machine configurations, credentials, internal correspondence, draft reports and manuscript revisions. It retains the selected episodes' machine-readable records and available databases. Some integrations record backend query snapshots instead of full database captures; absence of a SQLite file is not a claim that a database capture exists.

The shards use deterministic file timestamps and contain no Git directory or commit history. Local paths, author identifiers, credential references and private API endpoints are anonymized. Synthetic fixture identities, operation capabilities, model IDs, task specifications, numerical scores, tool calls and actual outcome records retain their measurement roles. JSON is serialized canonically; normalization changes byte hashes without changing numerical results. Incoming pre-anonymization hashes, received-export hashes and this artifact's hashes are deliberately distinguished.

SQLite identifying text is changed through SQL, followed by `PRAGMA integrity_check`; raw binary search-and-replace is not used. Anonymization of metadata does not turn this artifact into a byte-identical copy of the original execution directory.

## Reanalysis

```bash
python artifact.py summarize --out cells --group-by app policy timing
```

The output contains a row for every observed cohort/model/factor cell. Every boolean metric has its own `k` and `n`; missing labels are not converted to negatives. Technical errors have a separate count and are excluded from behavioral metric denominators. The utility intentionally does not compute a pooled success rate, automatically rank actors, or infer statistical independence across repeated task templates.

Original metric names differ across study stages; inspect the result schema before comparing them. `valid_commit`, `dangerous_commit`, `false_completion`, `settled_valid` and `transient_overwrite` measure different events. The generic cell export is an inspection tool; mechanism claims require reading the task, selecting context, trace and actual record together.
