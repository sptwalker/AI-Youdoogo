## ADDED Requirements

### Requirement: HTTP entrypoints are thin transport adapters
Each business HTTP entrypoint SHALL authenticate and authorize the caller, validate transport input, construct a plain command or query, invoke one primary Application use case, and map its result or application error to the existing HTTP envelope. Entrypoints MUST NOT query ORM models, execute SQL, commit transactions, call repositories, invoke LLM or storage implementations, or import legacy business services.

#### Scenario: HTTP request reaches a migrated capability
- **WHEN** a valid request reaches a migrated Proposal, Group Messaging, Meeting, Knowledge, Identity, Organization, or Operational Analytics endpoint
- **THEN** the route translates the request and principal into a Context command or query and delegates the behavior to one Application use case

#### Scenario: Entrypoint dependency rule is violated
- **WHEN** a migrated route imports an ORM model, a concrete repository, or a module under `app.services` to implement business behavior
- **THEN** the architecture boundary test fails and identifies the forbidden dependency

### Requirement: HTTP contracts remain backward compatible
Entrypoint migration SHALL preserve supported HTTP methods, `/api/v1` paths, query and body fields, authentication and role rules, status codes, `{code, msg, data}` envelopes, download responses, and application-error mappings. An intentional public contract change MUST be specified and versioned separately.

#### Scenario: Existing client calls a migrated endpoint
- **WHEN** the frontend or an external client sends a request using a currently supported route and payload
- **THEN** it receives the same supported status, envelope shape, field semantics, authorization outcome, and error code as before the migration

#### Scenario: Attachment is uploaded or downloaded
- **WHEN** an authorized group member uses the existing attachment upload or download endpoint
- **THEN** the 20 MB limit, attachment metadata, channel membership check, chat-object path restriction, authenticated download behavior, and binary response remain unchanged

### Requirement: Bootstrap remains the route composition root
Bootstrap SHALL be the only layer that assembles concrete Application dependencies and registers Context or compatibility routers on the FastAPI application. A Context Entrypoint MUST NOT construct Infrastructure implementations or import unrelated Context internals, and route migration MUST NOT create a second application factory or route registry.

#### Scenario: A legacy router is replaced by a Context router
- **WHEN** a migrated Context Entrypoint becomes canonical
- **THEN** Bootstrap wires its dependencies and registers it under the existing `/api/v1` prefix while unmigrated routers continue to be registered through the same composition root

### Requirement: Group chat is organized as a discussion feature
The frontend SHALL organize group-chat behavior under a discussion feature boundary that owns its API adapter, hooks, stateful containers, and presentation components. The route-level Discussion page and the exported GroupChat entry component MUST become composition containers rather than owning message transport, polling, read tracking, membership mutations, uploads, and streaming state directly.

#### Scenario: Group chat feature is rendered
- **WHEN** the Discussion route selects a channel and renders GroupChat
- **THEN** the container composes feature-owned hooks and focused presentation components while preserving the existing visible controls and interaction flow

#### Scenario: Frontend dependency boundaries are inspected
- **WHEN** tests or static checks inspect the discussion presentation components
- **THEN** transport calls and lifecycle effects are located in the feature API adapter or hooks rather than duplicated in MessageList, MessageComposer, MemberPicker, or member-list presentation

### Requirement: Message-session state and effects are owned by a dedicated hook
The discussion feature SHALL provide a message-session hook that owns current-channel message state, initial refresh, abortable channel switching, realtime-message ingestion, identifier-based deduplication, read acknowledgements, and polling fallback. The hook MUST prevent requests or events for a previously selected channel from mutating the current channel state.

#### Scenario: User switches channels quickly
- **WHEN** a message refresh for the previous channel completes after a new channel is selected
- **THEN** the previous request is aborted or ignored and its messages do not appear in the newly selected channel

#### Scenario: Realtime connection is unavailable
- **WHEN** the current channel is open and realtime is disconnected
- **THEN** the hook refreshes messages immediately, marks the channel read, notifies the parent read callback, and continues the existing five-second polling fallback until realtime reconnects or the channel unmounts

#### Scenario: Realtime message is also returned by refresh
- **WHEN** the same message arrives through the realtime stream and a list refresh
- **THEN** the hook retains exactly one message with that identifier and does not lose another just-arrived current-channel message that is absent from the refresh response

### Requirement: Message composition and streaming are owned by a dedicated hook
The discussion feature SHALL provide a message-composer hook that owns draft text, selected mentions, pending attachments, upload state, send state, mention-prefix construction, the maximum of three mentioned AI identifiers sent for response, and streamed message reconciliation. The hook MUST expose intent-oriented actions to presentation components instead of exposing transport callbacks as UI business logic.

#### Scenario: User sends text with human and AI mentions
- **WHEN** the user submits a non-empty draft with selected channel members
- **THEN** the hook prefixes the visible member names, passes at most three selected AI identifiers to the existing message API, clears the submitted draft state, and prevents a duplicate concurrent send

#### Scenario: User sends attachments without text
- **WHEN** one or more successfully uploaded attachments are pending and the text draft is empty
- **THEN** the hook sends the existing attachment placeholder content and attachment metadata through the same message endpoint

#### Scenario: AI response streams into the conversation
- **WHEN** the send stream emits `message_start`, one or more `delta` events, and `message_end`
- **THEN** the hook creates one temporary streaming message, appends deltas in order, replaces or removes the temporary message on completion, and deduplicates the persisted message by identifier

### Requirement: Membership behavior is owned by a dedicated hook
The discussion feature SHALL provide a membership hook that owns abortable member loading, member identity lookup, available human and AI choices, add and remove mutations, owner protection, and refresh after membership changes. Presentation components MUST receive member state and intent-oriented actions without calling membership APIs directly.

#### Scenario: Channel membership is loaded
- **WHEN** the current channel changes
- **THEN** the membership hook loads the new member list and prevents a late response for the previous channel from overwriting it

#### Scenario: Owner adds or removes members
- **WHEN** an authorized owner confirms adding eligible humans or AI agents, or removing a non-owner member
- **THEN** the hook performs the existing mutation, refreshes the member list, and invokes the existing membership-change notification exactly once

#### Scenario: Removal targets the channel owner
- **WHEN** the UI renders the owner in the member list
- **THEN** it does not offer a removal action for that owner and preserves the backend owner-protection behavior

### Requirement: Group chat presentation is split into focused components
The discussion feature SHALL separate message rendering, message composition, pending attachments, membership selection, member-list management, and channel actions into focused components. These components MUST receive serializable view data and event handlers, MUST NOT own cross-cutting request lifecycles, and MUST preserve AI Markdown rendering, attachment previews and downloads, sending indicators, owner badges, empty-state text, and automatic scroll-to-latest behavior.

#### Scenario: Messages are rendered after component extraction
- **WHEN** human, AI, streaming, image-attachment, and file-attachment messages are present
- **THEN** the focused message presentation renders the same speaker labels, AI Markdown, attachment actions, ordering, and loading feedback as the current GroupChat

#### Scenario: Member dialogs are rendered after component extraction
- **WHEN** the user opens the add-member or member-list dialog
- **THEN** the same eligible choices, owner badge, confirmation actions, and user feedback remain available through focused components

### Requirement: Discussion API and SSE behavior remain stable
The discussion feature migration SHALL preserve the existing channel, membership, unread, message, attachment, disband, promotion, and realtime API routes and semantics. The message-post stream MUST retain its supported `message_start`, `delta`, and `message_end` event names and payload meanings, and the user realtime subscription MUST continue to deliver only messages from channels the principal is authorized to access.

#### Scenario: Existing message stream is consumed after refactoring
- **WHEN** the frontend posts a group message that mentions one or more AI members
- **THEN** the existing SSE client consumes the same event names and ordering and produces the same final persisted messages without requiring a route or payload change

#### Scenario: Realtime authorization changes
- **WHEN** a user is no longer a member of a channel while a realtime subscription is active
- **THEN** subsequent delivery for that channel is rejected by the existing membership authorization behavior

#### Scenario: Realtime connection recovers
- **WHEN** realtime changes from disconnected to connected for an open channel
- **THEN** the message session performs the existing catch-up refresh and stops scheduling fallback polls after synchronization

### Requirement: Route-level and component call compatibility is preserved
The frontend migration SHALL preserve the existing Discussion route path, selected-channel behavior, GroupChat input properties and callbacks, authentication behavior, and user-visible workflow. If a temporary component re-export or wrapper is retained, it SHALL act only as a one-way facade to the canonical discussion feature and MUST NOT duplicate state or effects.

#### Scenario: Existing Discussion page renders the migrated GroupChat
- **WHEN** the current route container passes `channelId`, channel metadata, realtime state, owner state, and existing callbacks
- **THEN** the canonical feature accepts the same inputs and produces the same callback semantics without requiring a route change

#### Scenario: Legacy GroupChat import path is retained temporarily
- **WHEN** an unmigrated frontend module imports the existing GroupChat path
- **THEN** that module receives a one-way re-export or wrapper around the canonical feature implementation with no duplicate network or state lifecycle

### Requirement: Entrypoint and UI extraction is covered by focused tests
The system SHALL add Entrypoint contract tests and discussion feature tests before switching canonical callers. Tests MUST cover authorization and envelope mapping, channel switching cancellation, polling and realtime transitions, message deduplication, read acknowledgement, stream event reconciliation, attachments, membership mutations, and route-level rendering, and the existing frontend test, lint, and production-build gates MUST remain green.

#### Scenario: Refactored discussion feature passes verification
- **WHEN** focused hook and component tests, API contract tests, lint, TypeScript compilation, and production build run
- **THEN** they pass while demonstrating unchanged route, REST, download, and SSE behavior

#### Scenario: HTTP router is structurally migrated
- **WHEN** the migrated router is tested with fake Application dependencies
- **THEN** parameter, principal, authorization, result, and error mapping are verifiable without querying ORM state or importing a legacy business service
