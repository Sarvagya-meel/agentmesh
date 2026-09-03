import tomllib
from pathlib import Path


def test_local_install_contains_every_runtime_dependency_group():
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    groups = tomllib.loads(project.read_text(encoding="utf-8"))["dependency-groups"]

    def requirements(name):
        result = set()
        for item in groups[name]:
            if isinstance(item, str):
                result.add(item)
            else:
                result.update(requirements(item["include-group"]))
        return result

    local = requirements("local")
    for runtime in ("control-plane", "supervisor", "agent-langgraph", "agent-adk", "ui"):
        # LangSmith arrives transitively through LangGraph in the local install.
        required = requirements(runtime) - {"langsmith"}
        assert required <= local, f"local is missing {runtime}: {required - local}"
