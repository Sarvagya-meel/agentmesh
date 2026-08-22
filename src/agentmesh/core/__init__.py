"""AgentMesh core — domain models, exceptions, event types, providers, and database.

Package layout:
  core/
    models/         ← Pydantic domain models, exceptions, event types, AgentCard
    database/       ← event/claim repositories and LangGraph checkpointer
    providers/      ← LLM provider clients (Groq, etc.)
"""
