# Security Policy

## Supported Versions

Only the latest GitHub Release is supported for public security triage. Work in
`develop` is active development and may change before release.

## Reporting A Vulnerability

Do not open a public issue for secrets, credential exposure, or exploitable
security behavior.

Report privately to the repository owner through GitHub profile contact options,
or use GitHub private vulnerability reporting if it is enabled for this
repository.

Include:

- Affected version or commit.
- Steps to reproduce.
- Expected and actual behavior.
- Whether credentials, personal data, or external services are involved.

## Security Boundaries

AgentMesh is local-first. Authentication is currently deferred, and published
ports are intended only for local development or trusted networks. Do not expose
the stack directly to the public internet without adding authentication,
authorization, TLS, secret management, and deployment hardening.
