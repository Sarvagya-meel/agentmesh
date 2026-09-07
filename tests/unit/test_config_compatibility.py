from agentmesh.config import Settings as CompatibilitySettings
from agentmesh.config import get_settings as compatibility_get_settings
from agentmesh.core.config import Settings, get_settings


def test_root_config_reexports_core_settings() -> None:
    assert CompatibilitySettings is Settings
    assert compatibility_get_settings is get_settings
