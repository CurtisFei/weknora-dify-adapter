import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_normalizes_existing_api_prefix() -> None:
    settings = Settings(
        weknora_base_url="https://kb.example/api/v1/",
        weknora_api_key="wk-secret",
        dify_adapter_api_key="adapter-secret",
    )

    assert settings.weknora_api_url == "https://kb.example/api/v1"


def test_settings_appends_api_prefix_once() -> None:
    settings = Settings(
        weknora_base_url="https://kb.example/",
        weknora_api_key="wk-secret",
        dify_adapter_api_key="adapter-secret",
    )

    assert settings.weknora_api_url == "https://kb.example/api/v1"


def test_settings_rejects_missing_required_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEKNORA_BASE_URL", raising=False)
    monkeypatch.delenv("WEKNORA_API_KEY", raising=False)
    monkeypatch.delenv("DIFY_ADAPTER_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("weknora_api_key", ""),
        ("weknora_api_key", "   "),
        ("dify_adapter_api_key", ""),
        ("dify_adapter_api_key", "   "),
    ],
)
def test_settings_rejects_blank_secrets(field: str, value: str) -> None:
    values = {
        "weknora_base_url": "https://kb.example",
        "weknora_api_key": "wk-secret",
        "dify_adapter_api_key": "adapter-secret",
        field: value,
    }

    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("timeout", [0, 121])
def test_settings_rejects_timeout_outside_range(timeout: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            weknora_base_url="https://kb.example",
            weknora_api_key="wk-secret",
            dify_adapter_api_key="adapter-secret",
            weknora_timeout_seconds=timeout,
        )
