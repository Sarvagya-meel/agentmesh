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
