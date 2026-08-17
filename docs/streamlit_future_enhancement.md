Streamlit enhancement: independent startup and Docker-level agent control

Goal

Make the Streamlit UI fully independent at startup (no compose-level depends_on on agents) and add a UI capability to:

- Start a local PostgreSQL instance (if not already running) and connect to it.
- Read the registry table to show the current agents list and metadata.
- Provide Start / Stop controls for agent containers (docker-level control) so operators can bring up/down agents from the UI.

Rationale

- UX: developers should be able to open the Streamlit UI even if agents are not started; the UI should display live status and allow operator actions.
- Decoupling: the UI is a client of the control plane and the DB, not a hard runtime dependency. Compose-level depends_on was forcing an order that made the UI unavailable unless agents were healthy.

High-level design

1. Independent startup
   - Remove compose-level depends_on for streamlit (already implemented in compose.yml).
   - Streamlit should be resilient: show a friendly empty state and retry logic when registry/agents are not reachable.

2. DB connectivity and migration
   - Option A (recommended): let deployment orchestration keep Postgres and migrations in compose. Streamlit connects to the same DATABASE_URL and reads the agents table.
   - Option B (optional): Streamlit can start its own Postgres instance using Docker (see below), but this is only recommended for local dev/test, not production.

3. Agent list UI
   - On load, Streamlit queries the registry endpoint (or reads DB) and renders a table of AgentCard entries (agent_id, name, status, endpoint, capabilities).
   - Implement polling or a manual refresh button.

4. Start / Stop agent containers
   - Use the Docker Engine SDK for Python (docker-py) inside Streamlit (only in dev/local mode) to list, start, and stop containers.
   - Expose Start / Stop buttons per agent, which call server-side helper functions in Streamlit that invoke docker.from_env().containers.get(container_name).start() / .stop().
   - Optionally implement a safety confirmation and a toggle to restrict control to authorized users.

Security and constraints

- Running Docker commands from a web UI is a powerful capability and must be restricted to local development or protected operations. Avoid enabling Docker control in public or untrusted installs.
- If Streamlit runs inside a container and must control sibling containers, it must be granted access to the Docker socket (e.g., -v /var/run/docker.sock:/var/run/docker.sock). This is an invasive permission and should be optional and documented.
- Starting a Postgres instance from Streamlit (docker-py) is only for local convenience. Rely on the compose/migrations workflow for consistent schema management.

Implementation notes and code snippets

- Connect to Postgres and read agents (psycopg or HTTP API):

  import psycopg
  from pydantic import BaseModel

  conn = psycopg.connect(os.environ['DATABASE_URL'])
  with conn.cursor() as cur:
      cur.execute('SELECT agent_id, name, status, endpoint, metadata FROM registry_agents')
      rows = cur.fetchall()

- Docker control (docker-py) example:

  import docker
  client = docker.from_env()
  container = client.containers.get('agentmesh-agent-langgraph-copilot')
  container.start()  # or container.stop()

- Streamlit UI behavior:
  - Show connectivity status to DB and/or registry API.
  - If DB not available: show instructions and a button "Start local Postgres for dev" (calls the docker-py flow to create/run the postgres container and run migrations).
  - Show agent rows with Start/Stop buttons and current container status.

Suggested Compose / permission changes for local dev only

- When the user opts-in to allow Streamlit to control Docker, mount the Docker socket into the streamlit container in compose (local-only):

  streamlit:
    # ... other fields
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # local-only, opt-in

- Add a small permission/feature-flag in Streamlit settings (ENV var) that enables docker control code paths.

Backwards compatibility

- Removing the relies-on-agents compose ordering does not change API endpoints or DB schema; Streamlit will still work, just with a more tolerant startup.
- Keep the existing migration service and recommend using it for the canonical DB creation path.

Next steps for an implementation task

- Add a Streamlit page (src/agentmesh/services/service_agentmesh_ui/agents_control.py) that implements the UI, DB queries, and optional docker control.
- Add unit and integration tests (mock docker client) for the control flows.
- Add docs and an opt-in flag that documents the security implications of mounting the Docker socket.

If you'd like, I can:
- Implement the Streamlit UI skeleton and the DB/registry read in this repo as a follow-up task (I will keep the Docker control behind a feature flag and document the socket mount requirements), or
- Create a small prototype streamlit app file and tests that demonstrate listing agents and issuing start/stop commands (dev-only).