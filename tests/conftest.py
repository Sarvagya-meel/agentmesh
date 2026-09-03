import os

# In-process tests must not inherit provider or tracing credentials from .env.
# Opt-in live tests call the separately configured Docker services over HTTP.
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
