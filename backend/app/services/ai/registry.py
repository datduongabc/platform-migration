from dataclasses import dataclass
from typing import Dict, List, Optional
from app.services.ai.types import BaseAIProvider, CapabilityFlags
from app.services.ai.providers.gemini import GeminiProvider


@dataclass
class RegistryEntry:
    provider: str
    model: str
    adapter: BaseAIProvider
    capabilities: CapabilityFlags


class ProviderRegistry:
    _instance: Optional["ProviderRegistry"] = None

    def __init__(self):
        self._map: Dict[str, RegistryEntry] = {}

    @classmethod
    def get_instance(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = ProviderRegistry()
            cls._instance._register_defaults()
        return cls._instance

    def register(
        self,
        provider: str,
        model: str,
        adapter: BaseAIProvider,
        capabilities: CapabilityFlags,
    ) -> None:
        key = f"{provider.lower()}:{model.lower()}"
        self._map[key] = RegistryEntry(
            provider=provider,
            model=model,
            adapter=adapter,
            capabilities=capabilities,
        )

    def resolve(self, provider: str, model: str) -> RegistryEntry:
        key = f"{provider.lower()}:{model.lower()}"
        entry = self._map.get(key)
        if not entry:
            available = list(self._map.keys())
            raise ValueError(
                f"Unknown AI Provider/Model: '{provider}:{model}'. Registered models: {available}"
            )
        return entry

    def list_all(self) -> List[RegistryEntry]:
        return list(self._map.values())

    def _register_defaults(self) -> None:
        # This deployment intentionally supports only Gemini (analysis/chat) and
        # Speechmatics (transcription, wired separately in services/speechmatics.py)
        # — no OpenAI/Grok. Keep both entries pointed at the same adapter/capabilities;
        # they're two model *choices* within the one supported provider.
        gemini = GeminiProvider()
        self.register(
            "gemini",
            "gemini-3.5-flash-lite",
            gemini,
            CapabilityFlags(
                hard_json_schema=True, accepts_audio=False, max_context_tokens=1000000
            ),
        )
        self.register(
            "gemini",
            "gemini-3.5-flash",
            gemini,
            CapabilityFlags(
                hard_json_schema=True, accepts_audio=False, max_context_tokens=1000000
            ),
        )


def resolve_ai_model(provider: str, model: str) -> RegistryEntry:
    return ProviderRegistry.get_instance().resolve(provider, model)


def list_registered_ai_models() -> List[RegistryEntry]:
    return ProviderRegistry.get_instance().list_all()
