# Real-application study implementations

This directory contains the actor and intervention closure associated with the recorded manuscript corpus: evidence acquisition and effort, static semantic reconciliation, dynamic changes, actor-owned writes, execution guards and operation-bound outcome checks. The Medusa and EasyAppointments integrations use the upstream WindTunnel callbacks; research interventions and guards are separate code.

Use the root `artifact.py` to inspect and reaggregate the archived trials without importing these launchers. Historical multi-worker launchers refer to original plans, dedicated containers and browser endpoints; they require deliberate local environment reconstruction before new runs. They are not started by the artifact verifier or unit-test command.

The cross-catalog actor is under `src/handoff_generalization_v1`; its reusable native cart dependencies are shared with `../cart_lifecycle`. The six catalog definitions and actual native PHP adapter are retained.

See reproduction boundaries (`../../docs/REPRODUCTION.md`) and the protocol overview (`../../docs/PROTOCOL.md`).
