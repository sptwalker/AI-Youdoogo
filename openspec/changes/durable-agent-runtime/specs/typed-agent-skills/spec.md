## ADDED Requirements

### Requirement: Typed skill contract
Every executable Agent skill SHALL implement a common typed executor contract and SHALL return a validated SkillResult.

#### Scenario: Skill is registered
- **WHEN** a skill is added to the registry
- **THEN** prompt metadata and execution behavior are available through the same descriptor without modifying AgentRuntime

### Requirement: Dependency-injected Agent runner
Skills that invoke another Agent SHALL receive an AgentRunner dependency and MUST NOT import the concrete Agent base module.

#### Scenario: Consultation invokes another Agent
- **WHEN** the collaboration skill handles a consultation request
- **THEN** it calls the injected AgentRunner and does not introduce an import cycle

### Requirement: Structured action validation
The ToolDispatcher SHALL validate structured actions against the target skill request schema before execution.

#### Scenario: Model emits invalid action arguments
- **WHEN** an action does not satisfy the skill schema or policy
- **THEN** the action is rejected as a recorded tool failure without executing a side effect

### Requirement: Legacy directive compatibility
The system SHALL support existing Chinese text directives through an adapter that produces the same typed SkillRequest objects.

#### Scenario: Existing delivery directive is returned
- **WHEN** an Agent output contains a valid `【交付】` directive
- **THEN** the legacy adapter converts it to a typed delivery request and ToolDispatcher executes it

### Requirement: Red-line policy remains external to model output
The skill registry MUST NOT expose business-effecting approval or decision actions to AI execution.

#### Scenario: Model requests an unregistered approval action
- **WHEN** a model output asks to approve funds, personnel, projects, or business decisions
- **THEN** ToolDispatcher rejects the action and the workflow remains waiting for authenticated human input
