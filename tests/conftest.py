import os

# Tests must never call paid or rate-limited model providers.
os.environ["LLM_PROVIDER"] = "mock"
