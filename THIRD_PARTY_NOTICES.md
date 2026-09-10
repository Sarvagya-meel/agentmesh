# Third-Party Notices

AgentMesh does not vendor third-party source code in this repository. Python
dependencies and Docker base images are obtained from their respective upstream
distributions and remain subject to their own license terms and notices.

Before adding or updating a dependency, container image, source snippet, model,
dataset, asset, or generated content, the contributor must:

1. confirm that its license permits the intended use and redistribution;
2. retain any required copyright, license, and NOTICE text; and
3. add the required attribution here when the material is redistributed by this
   repository or an AgentMesh release.

This file records AgentMesh-specific third-party attributions. It does not
replace the license files delivered by upstream package or container-image
distributions.

## Direct Dependency Inventory

The following direct runtime dependencies were reviewed from `pyproject.toml`
on 2026-09-10. The repository does not redistribute their source. License
metadata must be checked again whenever a dependency or image changes.

| Component | Declared source | Installed package metadata |
| --- | --- | --- |
| `fastapi`, `uvicorn`, `pydantic`, `psycopg` | Python package index | No license value reported |
| `pydantic-settings`, `langsmith` | Python package index | MIT |
| `python-dotenv`, `httpx` | Python package index | BSD-3-Clause |
| `langgraph`, `langgraph-checkpoint-postgres` | Python package index | No license value reported |
| `google-adk` | Python package index | Apache-2.0 family |
| `google-genai`, `asyncpg`, `litellm`, `streamlit` | Python package index | No license value reported |
| `python:3.11-slim` | Docker Hub official Python image | Upstream image; inspect its current SBOM and notices before redistribution |

"No license value reported" means the installed package metadata did not expose
a license field or classifier. It is not a finding that the component is
unlicensed. Consult the upstream distribution before redistributing it or
including its source in a release.
