# AgentMesh Documentation

Use `plan.md` at the repository root as the authoritative runtime architecture
contract. This folder keeps supporting docs grouped by purpose so the root stays
focused on source, tests, deployment, and the primary project entry points.

## Map

- `runtime/`: active runtime behavior, non-functional requirements, roadmap, API
  guide, checkpoint/retry notes, and RFCs such as
  [RFC-001: Intent-Driven Three-Plane Runtime](runtime/rfc-001-three-plane-architecture.md).
- `operations/`: local Docker, demo validation, observability, and
  [merge-gate troubleshooting](operations/merge-gate-troubleshooting.md).
- `project/`: product, architecture, technology, testing, coding standards,
  release management, intellectual-property, and package-layout guidance shared across IDEs and
  assistant tools. Full-system validation is documented in the
  [testing runbook](project/agentmeshTestingSteps.md).
  Branches, releases, reports, and rollback are defined in
  [release management](project/release-management.md).
- `business/`: business problem framing and use-case context.
- `ide/`: optional IDE adapter notes and migrated tool-specific guidance.
- `planning/`: historical plans, gap analysis, and future proposals.
- `graphs/`, `learning/`, and `content/`: supporting diagrams, interview
  learning notes, and publication backlog.
- `../tests/tools/`: executable smoke, sanity, graph, and eval helpers.
