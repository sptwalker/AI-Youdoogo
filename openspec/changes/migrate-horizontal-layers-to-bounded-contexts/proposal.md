## Why

The modular runtime refactor removed several local hotspots, but the application still concentrates most business behavior in horizontal `app/services`, `app/models`, `app/agents`, and `app/knowledge` packages. This leaves global import cycles, scattered transaction ownership, framework-bound contracts, and high change amplification while the documented bounded-context architecture remains only partially implemented.

## What Changes

- Enforce an acyclic application-wide dependency graph and prevent new code from depending on legacy horizontal implementation packages.
- Break the Environment Projection, Agent package, and Knowledge package dependency cycles without changing public API or runtime behavior.
- Replace database- and ORM-shaped Agent, Capability, Planning, Workflow, and Task boundaries with plain request/result contracts, application-owned ports, and outer adapters.
- Complete vertical bounded-context slices for Proposal Management and progressively migrate Identity, Organization, Environment Projection, Communication, Meeting, Knowledge, and Operational Analytics behavior behind use cases.
- Convert legacy service modules into one-way compatibility facades and remove them after all internal callers migrate.
- Move HTTP entrypoints away from direct ORM/service access and organize frontend state and effects by business feature, beginning with group chat.
- Add characterization, contract, architecture, unit, adapter, and regression tests so each migration remains behavior-preserving.

## Capabilities

### New Capabilities

- `acyclic-modular-boundaries`: Application-wide import direction, cycle prevention, compatibility-facade rules, and migration guardrails.
- `clean-execution-contracts`: Framework-independent Agent, Capability, Planning, Workflow, Task, transaction, and execution contracts.
- `bounded-context-vertical-slices`: Behavior-preserving migration of business and foundation capabilities into owned Domain/Application/Entrypoint/Infrastructure slices.
- `feature-oriented-entrypoints-ui`: Thin HTTP entrypoints and feature-owned frontend state, effects, API adapters, and presentation components.

### Modified Capabilities

None. Existing completed changes remain behaviorally compatible; this change advances their implementations into the current DDD boundaries.

## Impact

- Backend packages: `app/contexts`, `app/bootstrap`, `app/platform`, and legacy `app/api`, `app/services`, `app/models`, `app/agents`, `app/knowledge`, `app/llm`, and `app/integrations` compatibility paths.
- Runtime: Workflow, Agent, Tool/Capability, Task, Environment Projection, Outbox handlers, transaction ownership, and composition wiring; database schema and public API remain compatible unless a later task explicitly documents a migration.
- Frontend: discussion/group-chat feature state and selected route containers; routes and API contracts remain compatible.
- Verification: architecture graph checks, focused characterization tests, full Ruff/Mypy/Pytest gates, frontend tests/lint/build, and migration-head validation.
