# AgentMesh Documentation

Use `plan.md` at the repository root as the authoritative runtime architecture
contract. This folder keeps supporting docs grouped by purpose so the root stays
focused on source, tests, deployment, and the primary project entry points.

## Map

- `runtime/`: active runtime behavior, non-functional requirements, roadmap, API
  guide, and checkpoint/retry notes.
- `operations/`: local Docker, demo validation, and observability runbooks.
- `project/`: product, architecture, technology, testing, coding standards, and
  package-layout guidance shared across IDEs and assistant tools. Full-system
  validation is documented in the
  [testing runbook](project/agentmeshTestingSteps.md).
- `business/`: business problem framing and use-case context.
- `ide/`: optional IDE adapter notes and migrated tool-specific guidance.
- `planning/`: historical plans, gap analysis, and future proposals.
- `graphs/`, `learning/`, and `content/`: supporting diagrams, interview
  learning notes, and publication backlog.
- `../tests/tools/`: executable smoke, sanity, graph, and eval helpers.
