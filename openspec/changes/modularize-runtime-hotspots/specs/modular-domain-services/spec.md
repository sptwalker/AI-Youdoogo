## ADDED Requirements

### Requirement: Domain service splits preserve public behavior
Desktop chat, Feishu login, and meeting service refactors SHALL preserve existing public function signatures, API responses, authorization rules, and transaction semantics.

#### Scenario: Existing API tests run after module extraction
- **WHEN** callers use the existing service or API import paths
- **THEN** behavior remains compatible without caller changes

### Requirement: Streaming orchestration is independently testable
Desktop chat SSE rendering and orchestration progress emission SHALL be separated from message persistence and participant resolution.

#### Scenario: Orchestration progress is emitted
- **WHEN** a durable workflow is submitted during a desktop chat stream
- **THEN** the extracted streaming component emits the same event payload and ordering as before

### Requirement: Feishu transient token logic is isolated
OAuth state and exchange token creation, validation, expiry, and single-use consumption SHALL be implemented in a focused component independent from Feishu API orchestration.

#### Scenario: Exchange token is consumed twice
- **WHEN** the same login exchange token is consumed more than once
- **THEN** only the first consumption succeeds and existing error behavior is preserved

### Requirement: Meeting AI actions are isolated from meeting CRUD
AI speaking, voting, minutes generation, and resolution-to-task behavior SHALL be implemented separately from meeting CRUD and human vote persistence.

#### Scenario: AI expert streams a response
- **WHEN** an existing meeting API requests AI expert speech
- **THEN** it delegates to the extracted AI action component and preserves the SSE contract

### Requirement: Large frontend pages become route containers
Large frontend pages SHALL delegate independent presentation sections and reusable stateful behavior to focused components or hooks while preserving routes and API calls.

#### Scenario: Frontend production build runs
- **WHEN** Dashboard and organization administration are rendered after extraction
- **THEN** TypeScript compilation and production build succeed with unchanged route-level behavior
