from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple


@dataclass
class UsageCtx:
    meeting_id: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class UsageMetadata:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    key_id: Optional[str] = None


@dataclass
class CapabilityFlags:
    hard_json_schema: bool = True
    accepts_audio: bool = False
    max_context_tokens: int = 128000


class BaseAIProvider(ABC):
    @abstractmethod
    async def generate_structured(
        self,
        messages: str,
        schema: Any,
        model: str,
        system_instruction: Optional[str] = None,
        parse_fn: Optional[Callable[[str], Any]] = None,
        retry_messages: Optional[str] = None,
        operation: str = "analysis",
        ctx: Optional[UsageCtx] = None,
    ) -> Tuple[Any, str, UsageMetadata]:
        """
        Generates structured JSON data from prompt.
        Returns: (parsed_data, raw_text, usage_metadata)
        """
        pass

    @abstractmethod
    async def generate_text(
        self,
        messages: str,
        model: str,
        system_instruction: Optional[str] = None,
    ) -> Tuple[str, UsageMetadata]:
        """
        Generates plain text response.
        Returns: (text, usage_metadata)
        """
        pass
