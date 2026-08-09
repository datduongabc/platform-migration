import json
import logging
from typing import Any, Callable, Optional, Tuple
import httpx
from app.core.config import settings
from app.services.ai.types import BaseAIProvider, UsageCtx, UsageMetadata

logger = logging.getLogger(__name__)


class GeminiProvider(BaseAIProvider):
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
        # Delegate to existing gemini analysis helper or generate via REST
        api_key = settings.GEMINI_API_KEY
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        contents = [{"role": "user", "parts": [{"text": messages}]}]
        body: dict = {
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }

        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(url, json=body)
            res.raise_for_status()
            res_json = res.json()

        candidates = res_json.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned empty candidates response.")

        raw_text = candidates[0]["content"]["parts"][0]["text"]
        usage_data = res_json.get("usageMetadata", {})

        meta = UsageMetadata(
            input_tokens=usage_data.get("promptTokenCount", 0),
            output_tokens=usage_data.get("candidatesTokenCount", 0),
            total_tokens=usage_data.get("totalTokenCount", 0),
            key_id="gemini_default",
        )

        parsed_data = parse_fn(raw_text) if parse_fn else json.loads(raw_text)
        return parsed_data, raw_text, meta

    async def generate_text(
        self,
        messages: str,
        model: str,
        system_instruction: Optional[str] = None,
    ) -> Tuple[str, UsageMetadata]:
        api_key = settings.GEMINI_API_KEY
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        contents = [{"role": "user", "parts": [{"text": messages}]}]
        body: dict = {"contents": contents}

        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(url, json=body)
            res.raise_for_status()
            res_json = res.json()

        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        usage_data = res_json.get("usageMetadata", {})

        meta = UsageMetadata(
            input_tokens=usage_data.get("promptTokenCount", 0),
            output_tokens=usage_data.get("candidatesTokenCount", 0),
            total_tokens=usage_data.get("totalTokenCount", 0),
            key_id="gemini_default",
        )

        return raw_text, meta
