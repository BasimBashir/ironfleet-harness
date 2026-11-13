
# IronFleet — Enterprise Legal Agent OS

## Product Vision, Architecture Direction & Repository Audit Specification

**Document Type:** Product and Technical Architecture Brief
**Project:** IronFleet Harness Core
**Target:** Enterprise-grade Legal Agent Operating System
**Status:** Architecture approval granted — repository audit required before implementation
**Implementation Authorization:** NOT GRANTED
**Priority:** Critical

---

# 1. Executive Directive

We are evolving IronFleet from its existing agent harness and terminal-oriented experience into an **enterprise-grade, matter-centric Legal Agent Operating System**.

The objective is not simply to redesign the terminal UI or introduce a dashboard. The objective is to create a professional legal operations environment in which lawyers can manage matters, supervise AI agents, coordinate parallel agent swarms, review evidence, inspect research, approve deliverables, and intervene in long-running autonomous workflows.

The platform should be designed for sophisticated legal environments comparable in operational expectations to:

- Kirkland & Ellis
- Dentons
- JPMorgan legal and compliance departments
- Large corporate legal departments
- Litigation and arbitration practices
- Financial institutions and regulated organizations

These organizations are reference points for enterprise expectations, not claims of affiliation or existing functionality.

## Critical instruction

**DO NOT DELETE, MODIFY, REFACTOR, REPLACE, MIGRATE, OR IMPLEMENT ANYTHING YET.**

The first task is a comprehensive audit of the existing repository.

You must understand the current architecture, identify what already works, determine what can be extended, and identify what genuinely needs replacement.

Your first deliverable must be a detailed technical assessment and proposed target architecture.

Wait for explicit approval before making code changes.

---

# 2. Product Vision

IronFleet should become a persistent, intelligent, multi-agent legal operating environment.

A lawyer should be able to create a legal matter, define its objectives, upload documents, assign work to an AI lead counsel, and have that lead counsel coordinate specialized agents.

The system should support:

- Multiple legal matters running concurrently.
- Multiple agents working on the same matter.
- Parallel agent execution.
- Synchronous and asynchronous execution.
- Long-running workflows lasting hours or days.
- Persistent execution across process restarts.
- Human intervention at any point.
- Evidence-backed legal research.
- Collaborative drafting and document review.
- Approval workflows.
- Complete execution history and auditability.

The platform must make agent activity visible and understandable rather than hiding the work behind a terminal or opaque orchestration process.

**Core product principle: The lawyer supervises the work; the agents execute it.**

The lawyer must retain control over legal decisions, external communications, filings, and other consequential actions.

---

# 3. Core Product Experience

The proposed experience combines three integrated interfaces.

These are not competing products. They are different views of the same matter and execution state.

## 3.1 Matter Board — Primary Interface

The Matter Board should become the main landing page.

It provides a portfolio-level view of all legal matters and their current operational status.

Each matter should display:

- Matter name and reference.
- Client or organization.
- Matter type.
- Jurisdiction.
- Lead counsel agent.
- Number of active agents.
- Current execution stage.
- Priority.
- Last activity.
- Outstanding human approvals.
- Deadlines.
- Deliverable status.
- Relevant risk indicators.

### Matter states

The board should support clear states such as:

| State           | Meaning                                 |
| --------------- | --------------------------------------- |
| Draft           | Matter created but not activated        |
| Queued          | Waiting for execution capacity          |
| Running         | Agents actively executing               |
| Waiting on you  | Human input or approval required        |
| Blocked         | Execution cannot proceed                |
| Review required | Work is ready for human review          |
| Completed       | Current workflow completed              |
| Failed          | Execution failed and requires attention |
| Archived        | Matter closed or archived               |

### Important UX requirement

**Waiting on you must be a first-class state.**

Human approvals, missing information, unresolved questions, and agent escalation requests must never disappear inside logs or notifications.

A lawyer should immediately understand which matters require attention.

### Matter board interactions

A user should be able to:

- Open a matter.
- Inspect current activity.
- View agent assignments.
- Review pending approvals.
- Resume paused workflows.
- Pause or cancel authorized execution.
- Change matter priority.
- Assign or reassign work.
- Inspect completed deliverables.
- Navigate to the swarm graph.

Do not implement these interactions yet. Audit existing capabilities and specify the required architecture.

---

## 3.2 Interactive Agent Swarm — Execution Interface

The second major interface is an interactive visualization of agent orchestration.

The user must be able to see how the AI system is actually working.

A matter may contain a lead counsel agent coordinating multiple specialist agents.

Illustrative execution:

```text
                    LEAD COUNSEL
                          |
           +--------------+--------------+
           |              |              |
      Research Agent  Evidence Agent  Contract Agent
           |              |              |
      Case Law Search  Document Review  Clause Analysis
           |              |              |
           +--------------+--------------+
                          |
                  Synthesis Agent
                          |
                  Drafting Agent
                          |
                   Review Agent
                          |
                  Human Approval
```

This is illustrative only. The actual topology must be dynamically generated from execution state rather than hardcoded.

### Swarm visualization requirements

Display:

- Agent identity and role.
- Current status.
- Assigned task.
- Parent-child relationships.
- Task dependencies.
- Parallel execution branches.
- Execution duration.
- Current activity.
- Tool calls.
- Model/provider information where permitted.
- Relevant input and output artifacts.
- Errors and retry attempts.
- Resource consumption where available.
- Human intervention points.

### Agent states

At minimum:

- Created
- Queued
- Running
- Waiting
- Blocked
- Awaiting approval
- Completed
- Failed
- Cancelled
- Timed out

### Agent inspection

Selecting an agent should open a detailed inspection panel containing:

1. Agent identity and persona.
2. Assigned objective.
3. Parent task and dependencies.
4. Current execution state.
5. Execution timeline.
6. Tool usage and relevant inputs.
7. Retrieved evidence and references.
8. Generated output.
9. Errors and retry history.
10. Relevant logs and trace information.
11. Token and resource metrics, if available.

### Agent intervention

Authorized users should eventually be able to:

- Pause an agent.
- Resume an agent.
- Cancel execution.
- Redirect its objective.
- Provide additional evidence.
- Supply missing information.
- Challenge its findings.
- Request a revision.
- Spawn follow-up work.
- Escalate to lead counsel.
- Approve or reject a deliverable.

These actions must be governed by permissions and execution-state rules.

The UI must never imply that an action succeeded before the backend confirms it.

---

## 3.3 Counsel Interaction — Conversational Interface

The third interface is a persistent interaction channel with the lead counsel agent.

This is not intended to be a generic chatbot.

It is the operational interface through which a lawyer supervises and directs the matter's agent team.

Examples:

- "Investigate the latest developments in this case."
- "Challenge the opposing counsel's interpretation of clause 14."
- "Compare the two versions of the agreement."
- "Identify missing evidence."
- "Ask the research agent to verify these authorities."
- "Pause drafting until the evidence review is complete."
- "Prepare a revised submission using only verified sources."

### Requirements

The interaction layer should support:

- Matter-specific conversational context.
- Persistent conversation history.
- Agent delegation.
- Follow-up instructions.
- Task creation.
- Evidence references.
- Artifact references.
- Approval requests.
- Execution status updates.
- Human-to-agent and agent-to-agent communication where authorized.

The lead counsel agent should act as the primary coordination point, while retaining the ability to delegate work to specialized agents.

---

# 4. Matter-Centric Workspace

Every legal matter should have its own persistent workspace.

The workspace is the primary organizational boundary for legal work.

Proposed sections:

| Section   | Purpose                                              |
| --------- | ---------------------------------------------------- |
| Overview  | Matter summary, objectives, status and deadlines     |
| Parties   | Clients, opposing parties and relevant organizations |
| Documents | Uploaded documents and generated artifacts           |
| Evidence  | Evidence records, provenance and references          |
| Research  | Legal research, authorities and retrieval results    |
| Work Plan | Tasks, dependencies and execution plans              |
| Agents    | Agent roster and execution status                    |
| Swarm     | Interactive orchestration visualization              |
| Drafts    | Generated documents and version history              |
| Decisions | Human decisions, approvals and rejections            |
| Activity  | Matter-wide event timeline                           |
| Audit     | Traceable record of actions and changes              |

### Matter metadata

A matter should be capable of representing:

- Matter identifier.
- Client identifier.
- Matter title.
- Matter category.
- Jurisdiction.
- Applicable legal framework.
- Parties.
- Objectives.
- Important dates.
- Deadlines.
- Confidentiality classification.
- Access policy.
- Assigned human team.
- Assigned agents.
- Status.
- Created and updated timestamps.

Do not assume all legal matters have the same structure. The architecture must accommodate configurable matter types.

---

# 5. Broad Legal Domain Support

The system must not be designed around a single legal practice area.

It should support configurable legal workflows across different domains.

Examples include:

1. Commercial litigation.
2. Civil litigation.
3. Criminal law.
4. Corporate law.
5. Mergers and acquisitions.
6. Banking and finance.
7. Regulatory compliance.
8. Employment law.
9. Intellectual property.
10. Contract drafting and review.
11. Arbitration.
12. Internal investigations.
13. Due diligence.
14. Privacy and data protection.
15. Legal operations and risk management.

### Architectural requirement

Avoid creating a completely separate orchestration engine for every practice area.

Instead, evaluate a configurable architecture based on:

- Agent personas.
- Skills.
- Tool permissions.
- Matter metadata.
- Workflow definitions.
- Jurisdiction-specific knowledge.
- Practice-area-specific templates.
- Reusable execution primitives.

The same orchestration foundation should be able to support different legal workflows without tightly coupling the core engine to individual practice areas.

---

# 6. Agent Architecture

The existing IronFleet agent execution engine is a critical asset.

Do not assume it should be replaced.

Audit it and determine how it can support the target operating model.

### Proposed agent hierarchy

```text
Matter
  |
  +-- Lead Counsel Agent
         |
         +-- Research Specialist
         |
         +-- Evidence Analyst
         |
         +-- Contract Analyst
         |
         +-- Legal Drafting Agent
         |
         +-- Citation Verification Agent
         |
         +-- Quality Review Agent
```

This is an example, not a mandatory fixed hierarchy.

The architecture should support:

- Dynamic agent creation.
- Configurable personas.
- Agent specialization.
- Task delegation.
- Agent-to-agent communication.
- Parent-child execution relationships.
- Parallel tasks.
- Dependency-aware execution.
- Shared matter context.
- Isolated agent working context where appropriate.
- Structured outputs.
- Error handling.
- Retry policies.
- Human escalation.

### Agent execution model

Evaluate whether the current execution engine supports:

- Concurrent matters.
- Multiple agents within a matter.
- Parallel execution.
- Per-matter isolation.
- Task-level scheduling.
- Execution cancellation.
- Checkpointing.
- Recovery.
- Retry and timeout handling.
- Durable event history.
- Idempotent task execution.
- Worker supervision.

Document existing capabilities separately from proposed capabilities.

Do not assume that an architectural feature exists merely because it appears in a roadmap or handoff document.

Verify it against source code and tests.

---

# 7. Long-Running Durable Execution

This is one of the most important architectural requirements.

Agents must be able to perform complex work that lasts hours or days.

A process restart, worker crash, application update, or temporary provider outage must not destroy the matter's execution state.

### Required capabilities

- Persistent workflow state.
- Durable task scheduling.
- Checkpoints.
- Event history.
- Recovery after restart.
- Retry policies.
- Timeout management.
- Cancellation.
- Pause and resume.
- Worker supervision.
- Idempotency.
- Dependency tracking.
- Failure recovery.
- Human wait states.
- Execution observability.

### Critical architectural question

Determine whether the current scheduler is genuinely durable or primarily in-process.

An in-memory queue is not sufficient as the sole execution mechanism for enterprise-grade, multi-day workflows.

Investigate:

1. Current scheduler implementation.
2. Persistence mechanism.
3. Database schema.
4. Job lifecycle.
5. Worker process lifecycle.
6. Recovery behavior.
7. Retry semantics.
8. Event persistence.
9. Duplicate execution risks.
10. Cross-process coordination.

### Proposed conceptual architecture

```text
Matter Workspace
       |
       v
Workflow Orchestrator
       |
       v
Durable Execution Layer
       |
       +------ Workflow State
       |
       +------ Task Scheduler
       |
       +------ Event Store
       |
       +------ Checkpoint Store
       |
       +------ Worker Supervisor
       |
       v
Agent Execution Workers
       |
       +------ LLM Providers
       +------ Tools
       +------ Legal RAG
       +------ Document Processing
       +------ External Integrations
```

This is a target design for evaluation, not an instruction to introduce a new technology immediately.

First assess whether existing components can be extended.

---

# 8. Legal Intelligence and RAG

Legal intelligence is a core capability, not an optional chatbot feature.

The platform must provide reliable access to matter-specific documents, evidence, authorities, and research.

Audit the current legal RAG implementation thoroughly.

### Required capabilities

- Matter-specific document ingestion.
- Structure-aware document splitting.
- Hybrid retrieval.
- Metadata filtering.
- Jurisdiction-aware retrieval.
- Citation preservation.
- Evidence provenance.
- Source references.
- Reranking.
- Quote verification.
- Retrieval evaluation.
- Document version tracking.
- Incremental ingestion.
- Reproducible evaluation.

### Legal reliability

Legal outputs must distinguish between:

- Verified source material.
- Retrieved supporting evidence.
- Agent interpretation.
- Unverified assertions.
- Missing information.
- Conflicting authorities.

Every material legal assertion should be traceable to its supporting source where applicable.

The system should not fabricate citations or imply that a source has been verified when it has not.

### Evaluation requirements

Audit existing benchmarks and test cases.

Assess:

- Retrieval precision.
- Retrieval recall.
- Citation accuracy.
- Grounding.
- Quote verification.
- Source coverage.
- Reranking effectiveness.
- Jurisdiction filtering.
- Cross-matter isolation.
- End-to-end answer quality.

Do not report a legal RAG system as production-ready based only on successful retrieval or passing unit tests.

Identify quality gaps and propose measurable acceptance criteria.

---

# 9. Human Supervision and Governance

This is a human-supervised autonomous system.

Agents may perform research, analyze evidence, prepare drafts, and coordinate work.

However, consequential legal actions must remain subject to appropriate human oversight.

### Approval-gated actions

Evaluate approval requirements for:

- External communications.
- Court filings.
- Submission of legal documents.
- Final legal opinions.
- Client-facing deliverables.
- Changes to legal strategy.
- Irreversible external actions.
- Access to sensitive matter data.

### Human intervention architecture

A workflow should be able to enter a durable wait state when an agent requires:

- Approval.
- Additional evidence.
- Clarification.
- A strategic decision.
- Conflict resolution.
- Permission to use a tool.

The workflow should resume from its previous state once the required intervention is completed.

### Audit requirements

Record:

- Who initiated an action.
- Which agent performed it.
- Which matter it belongs to.
- What action was requested.
- What inputs were used.
- What outputs were generated.
- Whether approval was required.
- Who approved or rejected it.
- When the action occurred.
- Whether execution succeeded or failed.

Audit history should be tamper-resistant and append-only where appropriate.

---

# 10. Enterprise Security and Isolation

Enterprise legal environments require strict confidentiality boundaries.

Security must be considered at the architecture level, not added as a UI feature later.

### Required security capabilities

- Tenant isolation.
- Matter-level access controls.
- Role-based access control.
- Matter-specific permissions.
- Ethical walls.
- Agent tool permissions.
- Provider egress controls.
- Secrets management.
- Encryption in transit.
- Encryption at rest.
- Audit logging.
- Data retention policies.
- Secure document handling.
- Access revocation.
- Controlled external integrations.

### Matter isolation

One matter must never accidentally expose another matter's:

- Documents.
- Evidence.
- Conversation history.
- Agent memory.
- Retrieval results.
- Execution artifacts.
- Tool outputs.

Cross-matter operations must be explicitly authorized and auditable.

### Agent permissions

An agent must not automatically inherit unrestricted permissions simply because it belongs to a matter.

Evaluate scoped permissions for:

- Reading documents.
- Writing artifacts.
- Accessing legal research.
- Calling tools.
- Using external providers.
- Communicating with other agents.
- Accessing other matters.
- Performing external actions.

### MCP and external tool integrations

Investigate the existing MCP integration and provider egress boundaries.

Specifically determine whether MCP calls can bypass existing egress controls.

Do not weaken existing security gates to simplify integration.

If an integration cannot preserve matter isolation, provenance, and egress controls, document it as a blocker.

---

# 11. Proposed High-Level Architecture

The following is the conceptual target architecture.

Do not implement it until the repository audit and architecture review are complete.

```text
+-------------------------------------------------------+
|               ENTERPRISE LEGAL WORKSPACE              |
|                                                       |
|  Matter Board | Matter Workspace | Counsel Chat       |
|                                                       |
|  Swarm Graph  | Documents | Evidence | Approvals      |
+---------------------------+---------------------------+
                            |
                            v
+-------------------------------------------------------+
|                APPLICATION SERVICES                   |
|                                                       |
|  Matter Management                                    |
|  User and Permission Management                       |
|  Workflow Management                                  |
|  Artifact and Document Management                     |
|  Approval and Governance                              |
|  Activity and Audit                                   |
+---------------------------+---------------------------+
                            |
                            v
+-------------------------------------------------------+
|                AGENT ORCHESTRATION                     |
|                                                       |
|  Lead Counsel                                         |
|  Agent Delegation                                     |
|  Task Dependencies                                    |
|  Parallel Execution                                   |
|  Agent Communication                                  |
|  Human Intervention                                   |
+---------------------------+---------------------------+
                            |
                            v
+-------------------------------------------------------+
|              DURABLE EXECUTION PLATFORM               |
|                                                       |
|  Scheduler                                            |
|  Persistent Workflow State                            |
|  Event Store                                          |
|  Checkpoints                                          |
|  Worker Supervision                                   |
|  Recovery and Retries                                 |
+---------------------------+---------------------------+
                            |
                            v
+-------------------------------------------------------+
|                  IRONFLEET CORE                       |
|                                                       |
|  Existing Agent Harness                               |
|  Personas and Skills                                  |
|  Tool Execution                                       |
|  Model Routing                                        |
|  Memory                                               |
|  Security Gates                                       |
|  Legal RAG                                            |
|  Observability                                        |
+---------------------------+---------------------------+
                            |
                            v
+-------------------------------------------------------+
|                INFRASTRUCTURE                         |
|                                                       |
|  Database                                             |
|  Document Storage                                     |
|  Vector Retrieval                                     |
|  Model Providers                                      |
|  Workers                                              |
|  External Integrations                                |
+-------------------------------------------------------+
```

### Architectural principle

Preserve the existing IronFleet core wherever it provides proven functionality.

Introduce new services and abstractions only where the audit identifies a genuine architectural gap.

Avoid rewriting stable components merely to achieve architectural uniformity.

---

# 12. Repository Audit — First Authorized Task

The only authorized task at this stage is to inspect and document the existing implementation.

Do not modify files.

Do not create new project code.

Do not install dependencies.

Do not run migrations.

Do not delete or rename anything.

Do not change configuration.

Do not run commands that mutate the repository or external state.

Read-only inspection and non-destructive tests are permitted where safe.

## Phase A — Repository Inventory

Inspect the entire repository.

Identify:

- Top-level directory structure.
- Application entry points.
- Core modules.
- Agent execution components.
- Scheduler.
- Database layer.
- Persistence layer.
- API layer.
- CLI and TUI.
- Frontend components, if any.
- Configuration files.
- Personas.
- Skills.
- Tools.
- MCP integrations.
- Legal RAG.
- Document ingestion.
- Tests.
- Benchmarks.
- Deployment and packaging.
- Documentation.

Deliver a repository map with a short explanation of each important component.

Identify duplicated, obsolete, experimental, and production-critical components.

Do not assume documentation reflects the latest code.

## Phase B — Existing TUI and User Experience

Inspect the current terminal interface.

Document:

- Current screens.
- Navigation.
- Components.
- Interaction model.
- State management.
- Data sources.
- Execution visibility.
- Limitations.
- Missing workflows.
- Dependencies on backend internals.

Identify which functionality is reusable and which presentation elements should eventually be replaced.

The objective is to replace the user experience, not automatically replace the execution engine.

If screenshots or visual references are available, inspect them.

## Phase C — Agent Execution and Orchestration

Trace the complete execution lifecycle.

Start from the point where a user initiates a task and follow it through:

1. Task creation.
2. Matter association.
3. Agent selection.
4. Persona resolution.
5. Prompt/context construction.
6. Model selection.
7. Tool execution.
8. Delegation.
9. Parallel execution.
10. Output generation.
11. Persistence.
12. Error handling.
13. Completion reporting.

Determine whether execution state is shared, isolated, persistent, or ephemeral.

Identify all concurrency and synchronization mechanisms.

## Phase D — Scheduler and Durability

Inspect the scheduler in detail.

Answer:

- Is it in-process or distributed?
- Does it persist jobs?
- Does it persist workflow state?
- Can it recover after a restart?
- Can a task be resumed?
- Are retries safe?
- Is execution idempotent?
- Can duplicate workers execute the same job?
- Can workflows wait for human intervention?
- Can workflows run for multiple days?
- Can tasks be cancelled safely?
- Are events persisted?
- Are state transitions validated?

Provide source-file references and relevant implementation details.

Do not simply describe intended behavior from documentation.

## Phase E — Legal RAG and Document Processing

Inspect:

- Ingestion pipeline.
- Corpus storage.
- Document parsing.
- Structure-aware splitting.
- Embedding generation.
- Vector storage.
- Lexical retrieval.
- Hybrid retrieval.
- Reranking.
- Evidence extraction.
- Citation generation.
- Quote verification.
- Evaluation harness.

Identify which capabilities are implemented, tested, experimental, or incomplete.

Assess whether the current design supports enterprise matter isolation.

## Phase F — Security and Governance

Inspect:

- Authentication.
- Authorization.
- Matter-level isolation.
- Agent permissions.
- Tool permissions.
- Egress controls.
- MCP boundaries.
- Secrets handling.
- Database access controls.
- File storage.
- Audit logs.
- Approval mechanisms.

Identify security gaps and potential cross-matter data leakage paths.

Treat these as high-priority architectural risks.

## Phase G — API and Integration Readiness

Determine whether the existing backend can support a separate enterprise frontend.

Inspect:

- Existing API endpoints.
- Request and response schemas.
- Authentication.
- Streaming support.
- Event delivery.
- WebSocket or server-sent events.
- Execution status retrieval.
- Agent inspection endpoints.
- Task control endpoints.
- Artifact retrieval.
- Approval endpoints.

Identify missing API capabilities.

Do not build endpoints yet.

## Phase H — Testing and Reliability

Inspect the test suite.

Determine:

- Total test coverage where measurable.
- Existing integration tests.
- Unit tests.
- Concurrency tests.
- Recovery tests.
- Security tests.
- RAG benchmarks.
- Legal quality evaluation.
- Windows compatibility.
- Packaging tests.

Run only non-destructive tests if they are safe in the current environment.

Clearly distinguish:

- Tests that already exist.
- Tests that were executed.
- Tests that passed.
- Tests that failed.
- Tests that could not be run.

Do not modify the test environment or install dependencies without approval.

---

# 13. Required Audit Classification

Every significant component must receive one of the following classifications.

| Classification | Meaning                                                               |
| -------------- | --------------------------------------------------------------------- |
| KEEP           | Existing implementation is suitable and should be preserved           |
| EXTEND         | Existing implementation is valuable but needs additional capabilities |
| REPLACE        | Existing implementation is unsuitable for the target architecture     |
| RETIRE         | Component is obsolete, redundant, or no longer needed                 |
| INVESTIGATE    | Insufficient evidence to make a decision                              |

For each classification, provide:

- Component name.
- File or directory location.
- Current implementation.
- Existing functionality.
- Dependencies.
- Evidence from source code.
- Relevant tests.
- Known limitations.
- Recommended classification.
- Reasoning.
- Migration implications.
- Risk level.

**Do not classify a component as RETIRE or REPLACE without identifying its dependencies and the functionality that would need to be preserved.**

---

# 14. Required Architecture Deliverables

After completing the audit, produce the following documents.

## Deliverable 1 — Repository Audit

Suggested filename:

`docs/enterprise/01-repository-audit.md`

Include:

- Repository structure.
- Core component inventory.
- Existing TUI architecture.
- Agent architecture.
- Scheduler architecture.
- Persistence.
- Legal RAG.
- Security.
- APIs.
- Tests.
- Technical debt.
- Risks.
- KEEP / EXTEND / REPLACE / RETIRE / INVESTIGATE classification.

## Deliverable 2 — Target Architecture

Suggested filename:

`docs/enterprise/02-target-architecture.md`

Include:

- System architecture.
- Service boundaries.
- Domain model.
- Matter lifecycle.
- Agent lifecycle.
- Workflow lifecycle.
- Event architecture.
- Data flow.
- Persistence architecture.
- API architecture.
- Security architecture.
- Frontend architecture.
- Observability.
- Deployment considerations.

Include Mermaid diagrams where appropriate.

## Deliverable 3 — Data Model Proposal

Suggested filename:

`docs/enterprise/03-data-model.md`

Evaluate the required entities, including:

- Tenant.
- User.
- Role.
- Permission.
- Matter.
- Party.
- MatterDocument.
- Evidence.
- Agent.
- AgentRun.
- Task.
- Workflow.
- WorkflowExecution.
- WorkflowEvent.
- Checkpoint.
- Artifact.
- Approval.
- Conversation.
- AuditEvent.

For each entity, identify:

- Purpose.
- Key fields.
- Relationships.
- Ownership.
- Access boundaries.
- Persistence requirements.

This is a proposed model, not an instruction to create migrations.

## Deliverable 4 — API and Event Contract

Suggested filename:

`docs/enterprise/04-api-and-events.md`

Define proposed API contracts for:

- Matter management.
- Agent management.
- Workflow creation.
- Execution status.
- Agent inspection.
- Pause and resume.
- Cancellation.
- Human approvals.
- Document management.
- Evidence access.
- Artifact retrieval.
- Live activity.
- Agent communication.

Evaluate REST, WebSockets, and server-sent events based on the actual existing stack.

Do not introduce a technology merely because it is fashionable.

## Deliverable 5 — UI/UX Specification

Suggested filename:

`docs/enterprise/05-product-and-ux-specification.md`

Specify:

- Matter Board.
- Matter Workspace.
- Swarm Graph.
- Agent Inspection Panel.
- Counsel Chat.
- Approval Center.
- Document and Evidence views.
- Activity Timeline.
- Navigation.
- Responsive behavior.
- Loading and error states.
- Empty states.
- Permission-dependent interactions.

The visual direction should be professional, restrained, information-dense, and appropriate for enterprise legal teams.

Avoid a generic AI chatbot aesthetic.

## Deliverable 6 — Migration and Implementation Roadmap

Suggested filename:

`docs/enterprise/06-migration-roadmap.md`

Provide a staged implementation plan.

Each phase must include:

- Objective.
- Scope.
- Components affected.
- Dependencies.
- Technical approach.
- Testing requirements.
- Acceptance criteria.
- Rollback strategy.
- Risks.
- Estimated complexity.

Prioritize preserving existing functionality and avoiding unnecessary rewrites.

---

# 15. Implementation Roadmap — Proposed Stages

These stages are planning guidance only. Do not execute them yet.

| Stage | Focus                      | Objective                                      |
| ----- | -------------------------- | ---------------------------------------------- |
| 0     | Repository audit           | Establish actual current state                 |
| 1     | Architecture foundation    | Finalize domain boundaries and contracts       |
| 2     | Matter platform            | Establish matter-centric data and APIs         |
| 3     | Durable execution          | Support persistent long-running workflows      |
| 4     | Agent orchestration        | Expose reliable agent lifecycle and delegation |
| 5     | Enterprise workspace       | Introduce the new primary interface            |
| 6     | Swarm visualization        | Expose execution and intervention              |
| 7     | Counsel interaction        | Integrate conversational supervision           |
| 8     | Legal intelligence         | Harden RAG, evidence and citations             |
| 9     | Security and governance    | Complete enterprise access and audit controls  |
| 10    | Reliability and deployment | Validate operational readiness                 |

The actual ordering may change based on audit findings.

For example, security and durable execution may need to precede the frontend.

The coding agent must justify any proposed sequencing changes.

---

# 16. Non-Functional Requirements

The architecture must consider:

### Reliability

- Recoverable execution.
- Persistent state.
- Graceful failure handling.
- Retry safety.
- Worker health monitoring.
- Consistent state transitions.

### Scalability

- Multiple matters.
- Multiple concurrent agents.
- Multiple users.
- Parallel workflows.
- Configurable execution limits.
- Resource isolation.

### Performance

- Responsive matter board.
- Efficient event delivery.
- Incremental activity updates.
- Efficient document retrieval.
- Controlled concurrency.
- No unnecessary full-page refreshes.

### Observability

- Structured logs.
- Distributed traces where appropriate.
- Workflow-level correlation IDs.
- Matter-level activity.
- Agent execution timelines.
- Error tracking.
- Provider latency.
- Resource metrics.
- Retry and failure visibility.

### Maintainability

- Clear service boundaries.
- Typed contracts.
- Testable components.
- Versioned schemas.
- Documented execution behavior.
- Backward compatibility where appropriate.

### Security

- Least privilege.
- Matter isolation.
- Tenant isolation.
- Secure secrets.
- Auditable actions.
- Controlled egress.
- Human approval for consequential actions.

---

# 17. Engineering Principles and Constraints

The following principles are mandatory.

1. **Preserve proven functionality.** Do not rewrite existing working systems without technical justification.
2. **Audit before implementation.** Source-code evidence takes priority over assumptions and documentation.
3. **Matter-centric design.** A legal matter is the primary business and data boundary.
4. **Durability by design.** Long-running execution must survive process restarts.
5. **Human-supervised autonomy.** Agents may work independently within authorized boundaries.
6. **Evidence-first legal AI.** Legal outputs must be traceable to reliable sources.
7. **Security by default.** Matter isolation and permissions must be enforced in the backend.
8. **Observable execution.** Agent activity must be inspectable.
9. **API-first architecture.** The frontend must not depend on private in-process implementation details.
10. **Incremental migration.** Preserve existing capabilities during the transition.
11. **No premature technology selection.** Evaluate the current stack before introducing new infrastructure.
12. **No unnecessary complexity.** Every new abstraction must solve an identified requirement.

---

# 18. Strict Execution Boundaries

This section overrides any general coding-agent instruction that might otherwise encourage autonomous implementation.

## Authorized now

- Read repository files.
- Inspect source code.
- Inspect configuration.
- Inspect tests.
- Inspect documentation.
- Inspect Git history without changing it.
- Trace execution paths.
- Run safe, non-destructive tests.
- Produce architecture diagrams.
- Produce Markdown documentation as audit deliverables, preferably outside existing application code.
- Identify risks and recommend solutions.

## Not authorized now

- Delete files or directories.
- Rewrite the TUI.
- Build a frontend.
- Create new application services.
- Change the database schema.
- Run migrations.
- Replace the scheduler.
- Replace the agent harness.
- Change model routing.
- Change provider configuration.
- Modify security gates.
- Change MCP integrations.
- Install packages.
- Upgrade dependencies.
- Change lockfiles.
- Modify production data.
- Change environment variables.
- Modify deployment configuration.
- Commit or push changes.
- Automatically fix issues discovered during the audit.

If a test or inspection requires modifying repository state, stop and explain the requirement instead of proceeding.

If an existing component appears obsolete, document the evidence and recommend its disposition. Do not remove it.

If the architecture appears to require a new dependency or infrastructure service, document the trade-offs and wait for approval.

---

# 19. Final Audit Report

At the end of the audit, provide an executive-level report containing:

## A. Current State

What IronFleet actually is today, based on source-code inspection.

## B. Existing Strengths

Which existing components should be preserved and leveraged.

## C. Critical Gaps

What prevents the current implementation from supporting the enterprise Legal Agent OS vision.

## D. Architectural Risks

Especially:

- In-process scheduling.
- Long-running execution.
- Persistence and recovery.
- Cross-matter isolation.
- MCP egress.
- Legal RAG accuracy.
- Agent observability.
- API readiness.
- Human approval controls.

## E. Proposed Target Architecture

A complete explanation of how the current platform should evolve.

## F. Component Disposition

A file-by-file or subsystem-by-subsystem KEEP / EXTEND / REPLACE / RETIRE / INVESTIGATE matrix.

## G. Migration Strategy

A staged plan that minimizes risk and preserves existing working functionality.

## H. Decisions Required

A concise list of architectural decisions requiring owner approval.

## I. Implementation Readiness

Classify each major subsystem:

- Ready to extend.
- Requires architectural changes.
- Requires additional research.
- Blocked by missing infrastructure.
- Not suitable for implementation yet.

---

# 20. Definition of Success

The audit is successful when the project owner can clearly answer:

1. What does IronFleet currently contain?
2. What is genuinely working?
3. Which components are production-critical?
4. What is the actual scheduler and persistence architecture?
5. Can the current engine support long-running, multi-agent workflows?
6. Can multiple legal matters execute concurrently and safely?
7. What is missing for enterprise matter isolation?
8. Can legal research and evidence be trusted?
9. Can the existing backend power a modern enterprise workspace?
10. What should be retained, extended, replaced, or retired?
11. What is the lowest-risk migration strategy?
12. What should be implemented first, and why?

The result must be grounded in source-code evidence, not speculation.

---

# 21. Final Instruction to the Coding Agent

You are acting as a principal software architect and senior engineering auditor.

Your task is to understand the existing IronFleet implementation and design its evolution into an enterprise-grade Legal Agent Operating System.

Think beyond a conventional dashboard or chatbot.

The platform must provide a persistent legal matter workspace, a sophisticated agent orchestration layer, durable multi-day execution, interactive swarm visibility, human supervision, evidence-backed legal intelligence, and enterprise-grade security.

However, **do not begin implementation**.

First inspect the repository, trace the actual architecture, identify the existing assets and limitations, and produce the complete audit and architecture proposal.

Challenge assumptions where the source code contradicts the documentation.

Prefer extending proven components over replacing them.

Do not invent capabilities, benchmarks, or implementation status.

Do not delete, refactor, migrate, or build anything without explicit approval.

**The required outcome of this phase is an evidence-based architecture proposal and a safe implementation roadmap — nothing more.**

Wait for the project owner's review and separate authorization before proceeding to implementation.
