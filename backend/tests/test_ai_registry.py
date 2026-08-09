import pytest
from app.services.ai.registry import resolve_ai_model, list_registered_ai_models


def test_ai_registry_resolution():
    gemini_entry = resolve_ai_model("gemini", "gemini-3.5-flash-lite")
    assert gemini_entry.provider == "gemini"
    assert gemini_entry.model == "gemini-3.5-flash-lite"
    assert gemini_entry.capabilities.max_context_tokens == 1000000


def test_ai_registry_list():
    # This deployment supports only Gemini for analysis/chat (Speechmatics handles
    # transcription separately) — no OpenAI/Grok.
    models = list_registered_ai_models()
    assert len(models) >= 1
    providers = {m.provider for m in models}
    assert providers == {"gemini"}


def test_ai_registry_unknown_model_raises():
    with pytest.raises(ValueError, match="Unknown AI Provider/Model"):
        resolve_ai_model("unknown_provider", "unknown_model")
