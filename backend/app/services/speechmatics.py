import json
import os
import re
from typing import Any, Dict, Optional, Tuple

import httpx
from app.core.config import settings

SPEECHMATICS_BASE_URL = "https://asr.api.speechmatics.com"
PAUSE_PERIOD = 3.0

# Shared HTTP connection pool for API requests
client_session = httpx.Client(timeout=60.0)


def get_api_url_and_headers(endpoint_path: str) -> Tuple[str, Dict[str, str]]:
    url = f"{SPEECHMATICS_BASE_URL}/{endpoint_path}"
    headers = {"Authorization": f"Bearer {settings.SPEECHMATICS_API_KEY}"}
    return url, headers


# Convert a Speechmatics speaker label to the display format
def format_speaker_label(raw: str) -> str:
    if re.match(r"^S\d+$", raw):
        return f"Speaker {raw[1:]}"
    if raw == "UU":
        return "Speaker"
    return raw


# Submits an audio file to Speechmatics Batch ASR API and returns job_id
def submit_speechmatics_job(
    audio_file_path: str, speaker_count: Optional[int] = None
) -> str:
    url, headers = get_api_url_and_headers("v2/jobs")

    # Dịch từ giọng nói sang văn bản, ngôn ngữ tự động, mô hình Ai nâng cao và nhận diện speakers
    config: Dict[str, Any] = {
        "type": "transcription",
        "transcription_config": {
            "language": "auto",
            "operating_point": "enhanced",
            "diarization": "speaker",
        },
    }

    # Thêm vào config nếu người dùng có set số lượng tối đa
    if speaker_count and speaker_count > 0:
        config["transcription_config"]["speaker_diarization_config"] = {
            "max_speakers": speaker_count
        }

    filename = os.path.basename(audio_file_path)

    with open(audio_file_path, "rb") as audio_file:
        files = {
            "data_file": (filename, audio_file, "audio/mpeg"),
            "config": (None, json.dumps(config), "application/json"),
        }
        res = client_session.post(url, headers=headers, files=files)
        res.raise_for_status()
        data = res.json()
        return data["id"]


# Get job status from Speechmatics API
def get_speechmatics_job_status(job_id: str) -> Dict[str, Any]:
    url, headers = get_api_url_and_headers(f"v2/jobs/{job_id}")
    res = client_session.get(url, headers=headers)
    res.raise_for_status()
    return res.json()


# Extract language code from Speechmatics transcript
def extract_language(transcript: Dict[str, Any]) -> str:
    metadata = transcript.get("metadata", {})
    meta_lang = metadata.get("transcription_config", {}).get("language")

    if meta_lang and meta_lang != "auto":
        return meta_lang

    results = transcript.get("results", [])
    for r in results[:100]:
        if r.get("type") == "word":
            alts = r.get("alternatives", [])
            if alts and alts[0].get("language"):
                return alts[0]["language"]

    return meta_lang if meta_lang else "unknown"


# Map Speechmatics word by word results to segments
def parse_transcript_response(transcript: Dict[str, Any]) -> Dict[str, Any]:
    language = extract_language(transcript)
    segments = []

    current_speaker = None
    current_start = None
    current_end = None
    current_words = []
    conf_sum = 0.0
    conf_count = 0

    def flush_segment():
        nonlocal \
            current_speaker, \
            current_start, \
            current_end, \
            current_words, \
            conf_sum, \
            conf_count
        if current_speaker is not None and current_words:
            confidence = round(conf_sum / conf_count, 2) if conf_count > 0 else None
            segments.append(
                {
                    "speaker": format_speaker_label(current_speaker),
                    "start_ms": int(round((current_start or 0.0) * 1000)),
                    "end_ms": int(round((current_end or 0.0) * 1000)),
                    "text": " ".join(current_words),
                    "confidence": confidence,
                }
            )
        current_speaker = None
        current_start = None
        current_end = None
        current_words.clear()
        conf_sum = 0.0
        conf_count = 0

    results = transcript.get("results", [])
    for result in results:
        res_type = result.get("type")
        if res_type == "word":
            alts = result.get("alternatives", [])
            content = alts[0].get("content", "") if alts else ""
            speaker = alts[0].get("speaker") if alts else None
            if not speaker:
                speaker = result.get("speaker", "S1")
            conf = alts[0].get("confidence") if alts else None
            word_start = result.get("start_time", 0.0)

            if speaker != current_speaker:
                flush_segment()
                current_speaker = speaker
                current_start = word_start
            elif current_end is not None and (word_start - current_end > PAUSE_PERIOD):
                flush_segment()
                current_speaker = speaker
                current_start = word_start

            current_end = result.get("end_time", current_end or 0.0)
            current_words.append(content)
            if conf is not None:
                conf_sum += float(conf)
                conf_count += 1

        elif res_type == "punctuation" and result.get("attaches_to") == "previous":
            alts = result.get("alternatives", [])
            content = alts[0].get("content", "") if alts else ""
            if current_words:
                current_words[-1] += content

    flush_segment()
    return {"language": language, "segments": segments}


# Fetch completed transcript, parse it, and compute the total processed audio seconds
def fetch_speechmatics_transcript(job_id: str) -> Dict[str, Any]:
    url, headers = get_api_url_and_headers(
        f"v2/jobs/{job_id}/transcript?format=json-v2"
    )
    res = client_session.get(url, headers=headers)
    res.raise_for_status()
    raw = res.json()

    results = raw.get("results", [])
    audio_seconds = 0.0
    for r in results:
        end_time = r.get("end_time")
        if end_time is not None and end_time > audio_seconds:
            audio_seconds = end_time

    transcript = parse_transcript_response(raw)
    return {
        "transcript": transcript,
        "audio_seconds": audio_seconds,
    }
