import json
import os
from typing import Any, Dict, Optional

import httpx
from app.core.config import settings

SPEECHMATICS_BASE_URL = "https://asr.api.speechmatics.com"


def get_speechmatics_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.SPEECHMATICS_API_KEY}"}


async def submit_speechmatics_job(
    audio_file_path: str, speaker_count: Optional[int] = None
) -> str:
    """
    Submits an audio file to Speechmatics Batch ASR API and returns job_id.
    """
    url = f"{SPEECHMATICS_BASE_URL}/v2/jobs"

    config: Dict[str, Any] = {
        "type": "transcription",
        "transcription_config": {
            "language": "auto",
            "operating_point": "enhanced",
            "diarization": "speaker",
        },
    }

    if speaker_count and speaker_count > 0:
        config["transcription_config"]["speaker_diarization_config"] = {
            "max_speakers": speaker_count
        }

    headers = get_speechmatics_headers()
    filename = os.path.basename(audio_file_path)

    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(audio_file_path, "rb") as audio_file:
            files = {
                "data_file": (filename, audio_file, "audio/mpeg"),
                "config": (None, json.dumps(config), "application/json"),
            }
            res = await client.post(url, headers=headers, files=files)
            res.raise_for_status()
            data = res.json()
            return data["id"]


async def get_speechmatics_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get job status from Speechmatics API.
    """
    url = f"{SPEECHMATICS_BASE_URL}/v2/jobs/{job_id}"
    headers = get_speechmatics_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.get(url, headers=headers)
        res.raise_for_status()
        return res.json()


async def get_speechmatics_transcript(job_id: str) -> Dict[str, Any]:
    """
    Fetch completed transcript JSON from Speechmatics API.
    """
    url = f"{SPEECHMATICS_BASE_URL}/v2/jobs/{job_id}/transcript?format=json-v2"
    headers = get_speechmatics_headers()

    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.get(url, headers=headers)
        res.raise_for_status()
        return res.json()
