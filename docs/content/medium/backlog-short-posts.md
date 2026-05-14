# Medium / LinkedIn Short Post Backlog

## Purpose

Small features, minor learning points, or implementation details that are not large enough for a full Medium article should be added here as short post ideas.

When a short post idea grows into something worth a full article, promote it to its own file under `docs/content/medium/YYYY-MM-DD-<topic-slug>.md`.

---

## How to Use This Document

For each small feature or insight, add one entry using the template below.

Mark the status as one of: `Draft` | `Ready` | `Published` | `Promoted to full post`

---

## Backlog Table

| Feature | Phase | Key Insight | Status |
|---------|-------|-------------|--------|
| _(entries will be added as phases complete)_ | — | — | — |

---

## Entry Template

Copy this block for each new short post idea:

```
# Topic: <topic name>

## Hook
Write a short interesting opening that makes someone stop scrolling.

## Core Idea
Explain the idea simply in 2–3 sentences.

## Why It Matters
Explain why this matters in production or for a business.

## AgentMesh Example
Map it to a specific part of this project.

## LinkedIn-Ready Version
Write a short post (3–5 sentences) ready to copy-paste to LinkedIn.

## Hashtags
Add 3–5 suggested hashtags.
```

---

## Entries

_(No entries yet — entries will be added as phases complete.)_

---

# Topic: Why I Designed Each AI Agent as a Package, Not a Single File

## Hook

Most tutorials show AI agents as a single Python file. That works for demos. It falls apart the moment your agent needs a scraper, a prompt template, an API client, and its own config. Here's what I did instead.

## Core Idea

Each agent in AgentMesh is a Python package — a folder with separate files for the agent class, input/output schemas, external tools, LLM prompts, and config. This is the same principle as keeping your kitchen organised: the chef, the recipes, the ingredients, and the equipment are all separate things, even though they work together.

## Why It Matters

In production, agents grow. A job detector might need a job board API client, a relevance scorer, a deduplication check, and retry logic. Keeping all of that in one file becomes unmaintainable fast. Package-based agents let each agent own its complexity cleanly — and let you scale or deploy one agent without touching the others.

## AgentMesh Example

In AgentMesh, `agents/job_detector/` is a package. `tools.py` holds the job board API client behind an abstract interface. `prompts.py` holds the relevance scoring prompt. `runners/run_job_detector.py` lets you start just the job detector as a standalone process. It talks to MCP through `clients/mcp_client.py` — never through direct service imports.

## LinkedIn-Ready Version

Most AI agent tutorials show a single Python file. That works for demos. In production, agents grow — they need tools, prompts, schemas, and config. In AgentMesh, I structured each agent as a Python package with separate files for each concern. This means each agent can be tested, deployed, and scaled independently. Small design decision. Big production difference.

## Hashtags

#Python #SystemDesign #MultiAgent #SoftwareArchitecture #AIEngineering

---

# Topic: How I Designed My Agent System to Be Local-First but Cloud-Ready with AWS AgentCore

## Hook

Every cloud tutorial starts with "first, create an AWS account." I started with "first, make it work for free on your laptop." Here's how I designed AgentMesh to run locally with zero cloud cost — and scale to AWS when ready, without rewriting anything.

## Core Idea

AgentMesh uses feature flags and injectable adapter interfaces to keep AWS optional. `AWS_AGENT_REGISTRY_ENABLED=false` means no AWS calls. `LLM_PROVIDER=mock` means no Bedrock calls. All AWS clients implement the same abstract interfaces as local implementations — so the service layer never knows whether it's talking to AWS or a local mock.

## Why It Matters

Cloud costs are real. AWS mistakes are expensive. A local-first design means you can build, test, and demo the entire system for free. When the business is ready to scale — or when compliance requires a centralised agent catalogue — you flip a flag. Nothing else changes.

## AgentMesh Example

In AgentMesh, `agents/job_detector/agent_manifest.json` describes the agent's capabilities and governance metadata. Locally, `RegistryService` reads this from the filesystem. When `AWS_AGENT_REGISTRY_ENABLED=true`, the same service syncs it to AWS Agent Registry. The agent itself doesn't change — it still polls MCP via `clients/mcp_client.py` whether it's running locally or on AgentCore.

## LinkedIn-Ready Version

Most AI projects start with cloud dependencies baked in. I took the opposite approach with AgentMesh: local-first, cloud-optional. All core functionality runs on a laptop with Docker Compose. AWS Agent Registry and AgentCore are opt-in via feature flags. Unit tests never call AWS. When you're ready to scale, you flip a flag — nothing else changes. That's the kind of architecture that survives contact with production.

## Hashtags

#Python #AWSAgentCore #SystemDesign #MultiAgent #CloudArchitecture #LocalFirst
