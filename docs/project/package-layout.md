# Python Package Layout

AgentMesh keeps deployable code under `src/agentmesh` and test-only support code
under `tests`. Shared runtime infrastructure belongs under `agentmesh.core`.

## Import migration

| Legacy import | Current import | Compatibility policy |
|---|---|---|
| `agentmesh.config` | `agentmesh.core.config` | Strict replacement; the legacy module is removed. |
| `agentmesh.database` | `agentmesh.core.database` | No facade. Consumers must migrate to the explicit core package. |
| `agentmesh.database.postgres.repository` | `agentmesh.core.database.postgres.repository` | Strict replacement; the legacy module is removed. |
| `agentmesh.database.postgres.checkpoint` | `agentmesh.core.database.postgres.checkpoint` | Strict replacement; the legacy module is removed. |
| `agentmesh.testing.sanity_catalog` | `tests.support.sanity_catalog` | Test-only helper; it is no longer shipped in the runtime package. |

The service-local `agentmesh.services.service_agentmesh_server.database` modules
remain narrow facades for the server boundary. Shared repository and checkpoint
implementations live in `agentmesh.core.database.postgres`.
