# Phase 12: AWS Agent Registry client — syncs agent metadata when AWS_AGENT_REGISTRY_ENABLED=true
# Implements RegistryRepository interface. Never called when flag is false.
# Never syncs workflow events or payload data — metadata only.
