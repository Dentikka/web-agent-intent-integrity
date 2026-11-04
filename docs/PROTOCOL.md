# Experimental design

## Common evaluation contract

An assignment specifies the intended operation, object, quantity or duration, complete monetary conditions, authorization scope and required outcome. The actor can use the permitted UI and/or page-native WebMCP tools. The evaluator separately checks persisted application records and the evidence supporting the actor's report. Evaluator state and answers are unavailable to the actor.

The native application writes create local orders, appointments or cart revisions using synthetic identities. UI observations are DOM text and controls, rather than a screenshot-only interface. Instrumented adapters, schedules and server guards are experimental components; they are not claimed to be standard features of the upstream applications.

## Questions and interventions

1. **Interface selection and evidence acquisition.** Vary whether UI and native evidence are available, the source that is current, initial routes, and the effort required to disclose complete conditions. Distinguish evidence being supplied from evidence returned before the model selected a write.
2. **Preserving the operation's meaning.** Examine product/variant binding, unit versus full price, service identity and duration, authorization, and which state a selected write actually consumes. Compatible differences between representations do not automatically prohibit an action.
3. **Consequences across the trajectory.** Follow actual persistent records, later changes and previously accepted actor-owned writes. Distinguish an intermediate overwrite, an agent repair, a correct report-time state and a correct settled state.
4. **Protection across execution.** Compare behavioral reconciliation, waiting for accepted writes, revision guards, checks on the actual workflow snapshot, operation-bound receipts and report comparators. Correct completion of feasible authorized tasks is measured alongside safety.

## Recorded manuscript corpus

`data/paper/cohorts.json` records the expected and observed assignment counts and technical errors for every cohort. `trials.csv` enumerates all 7,192 selected assignments, including errors. Main, transfer and repeated-transfer cohorts are not combined into independent-site counts. Earlier pilots, calibrations and mechanical controls are not added to this registry.

Study names in the registry describe successive fixed experimental programs, not interchangeable versions of a single benchmark. Exact task specifications, prompts, tool schemas and selecting model requests remain in the associated evidence shards. Source modules are under `studies/real_apps/`; [the reproduction guide](https://github.com/Dentikka/web-agent-intent-integrity/blob/main/docs/REPRODUCTION.md) distinguishes offline checking from recreating application installations.

## Separate cart replication

For each of two served models, the fixed matrices contain 120 form/saved-cart episodes, 48 price-scope episodes, 96 handoff episodes and 24 autosave episodes. Six compatibility episodes per model are separate: 288 research + 6 compatibility episodes per model, 588 total. The scripted native preflight contains 54 controls and is not a model experiment.

Page checkout consumes the local form; native checkout consumes the saved cart. Price-scope tasks include feasible and over-cap requests. Handoff tasks distinguish synchronization directions. Autosave tasks retain the actual earlier accepted UI write and compare immediate versus queued completion, with and without an instruction to await pending writes. The adapter is backed by native WooCommerce APIs; it is not an unmodified production storefront.

## Interpretation

Technical failures remain visible and are separated from behavioral outcomes. No-order alone is not a correct refusal: refusal interpretation requires a reviewed final answer. A completed report alone does not establish a matching persisted operation or a receipt bound to the current operation. The corpus supports mechanism analysis and matched contrasts under the specified interventions, rather than population failure rates on public websites or an overall model leaderboard.

## Additional operation-binding source package

The [receipt/consent protocol](https://github.com/Dentikka/web-agent-intent-integrity/blob/main/studies/operation_binding/PROTOCOL.md) tests whether evidence and approval belong to this operation. Receipt crosses current/foreign first receipts with baseline/explicit comparison (48 episodes per model). Consent crosses requested same/cross route, current/foreign approval and ordinary/binding instruction (64 per model). No server gate forces safe reporting or authorized writes. All alternative checks remain available. The source and implementation controls are included; new model research outcomes are not added to the recorded registry.
