# AgentMesh AI Assistant Instructions

This file is the single source of truth for AI assistants working in this
repository. Codex, Claude, Kiro, VS Code GitHub Copilot, and future IDE agents
should follow this file first. Tool-specific files may point here, but should not
duplicate these rules.

## Audience

Work as if Sarvagya is the developer maintaining the project and interviewers may
read the repository to understand architecture decisions. Prefer precise,
interview-ready explanations: name the boundary, explain the tradeoff, and keep
claims grounded in the code or docs.

## Authority Order

1. Explicit user instruction in the current task.
2. `plan.md` for authoritative agent-runtime architecture.
3. This `AGENTS.md` file for repository-wide assistant behavior.
4. Focused Markdown docs listed in the Documentation Map below.
5. Historical learning logs, proposals, and generated reports are context only;
   do not rewrite them unless requested.

## Documentation Map

Read the relevant Markdown before editing code or docs. Prefer active source docs
over generated or historical material.

- Runtime architecture: `plan.md`, `agent_runtime/README.md`,
  `docs/agent-runtime-functional.md`,
  `docs/agent-runtime-non-functional.md`, `docs/agent-runtime-roadmap.md`,
  `docs/agent-runtime-api-worker-registry-guide.md`
- Project overview and local operation: `README.md`, `docs/docker-operations.md`
- Database and deployment boundaries: `deployment/postgres/README.md`,
  `deployment/agentcore/README.md`
- Worker package behavior: package README files under `src/agentmesh/agents/`
  and service README files under `src/agentmesh/services/`
- Product and business context: `.kiro/steering/product.md`,
  `docs/business/BUSINESS_PROBLEMS.md`
- Tech, testing, and style context: `.kiro/steering/tech.md`,
  `.kiro/steering/testing.md`, `.kiro/steering/coding-standards.md`,
  `pyproject.toml`
- IDE adapters: `CLAUDE.md`, `.github/copilot-instructions.md`,
  `.github/instructions/*.instructions.md`, and `.kiro/steering/*.md` should
  point back here instead of duplicating full rules.

## Project Context

AgentMesh is a durable multi-agent runtime for job-search automation and future
agentic workflows. The system favors event sourcing, deterministic state
projection, explicit service boundaries, and local-first operation.

## Runtime Architecture

Use `plan.md` as the source of truth for runtime architecture. Use
`docs/agent-runtime-functional.md` to understand behavior and
`docs/agent-runtime-non-functional.md` to understand reliability, recovery,
security, determinism, provider, and operability constraints.

## Service Boundaries

- Keep route handlers thin: validate input and delegate business logic.
- Keep durable workflow state in the control plane and PostgreSQL-backed
  repositories.
- Do not let agents call each other directly.
- Do not let workers select downstream recipients or mutate DAG state.
- Do not let the supervisor bypass control-plane validation, queues, leases, or
  event append/query paths.
- Keep worker packages focused on their own execution behavior, prompts, schemas,
  and tools.

## Documentation Rules

- Documentation-only tasks must not add runtime code, migrations, Docker changes,
  or unrelated generated output.
- Update active README/runbook/API/user-story docs when architecture language
  changes.
- Keep functional runtime behavior in `docs/agent-runtime-functional.md` and
  non-functional qualities in `docs/agent-runtime-non-functional.md`.
- Avoid duplicating the full design across IDE instruction files. Point back to
  this file and the focused runtime docs.
- Keep Kiro steering, Claude, Codex, and VS Code/GitHub Copilot guidance aligned
  through this file; tool-specific files should be short adapters unless they are
  domain docs such as product, tech, testing, or coding standards.
- Keep explanations concise enough for maintainers, but clear enough that an
  interviewer can follow the architecture and tradeoffs.
- Preserve historical learning logs and future proposals unless the task
  explicitly asks to revise archival material.

## Validation

Use the smallest useful checks for the change. For documentation-only edits,
prefer link, spelling, formatting, and targeted text searches. For code changes,
use the project commands from `README.md` and `pyproject.toml` where practical:

```powershell
python -m pytest -q
python -m ruff check src tests
python -m mypy --strict src
```

## Git Hygiene

- Do not revert user changes.
- Keep edits scoped to the requested files and materially affected docs.
- Inspect `git diff` before reporting completion.
- Report files changed, checks run, and any active docs intentionally left
  untouched.
