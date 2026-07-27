import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def is_ffmpeg_available() -> bool:
    """
    Check if ffmpeg executable is available in system PATH.
    """
    return shutil.which("ffmpeg") is not None


def is_ffprobe_available() -> bool:
    """
    Check if ffprobe executable is available in system PATH.
    """
    return shutil.which("ffprobe") is not None


async def get_audio_duration_seconds(file_path: str) -> float:
    """
    Probe an audio file using ffprobe and return duration in seconds.
    Returns 0.0 if probe fails or ffprobe is not installed.
    """
    if not is_ffprobe_available():
        return 0.0

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        file_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0 and stdout:
            data = json.loads(stdout.decode("utf-8"))
            duration_str = data.get("format", {}).get("duration")
            if duration_str:
                return float(duration_str)
        elif stderr:
            logger.warning(f"[audio] ffprobe stderr: {stderr.decode('utf-8')[:200]}")
    except Exception as e:
        logger.warning(f"[audio] get_audio_duration_seconds error: {e}")

    return 0.0


async def transcode_to_mp3(input_path: str, output_path: str) -> Optional[str]:
    """
    Transcode input audio file to MP3 using ffmpeg.
    Returns output_path if successful, None otherwise.
    """
    if not is_ffmpeg_available():
        return None

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-b:a",
        "96k",
        output_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode == 0 and os.path.exists(output_path):
            return output_path
        elif stderr:
            logger.warning(f"[audio] ffmpeg transcode stderr: {stderr.decode('utf-8')[:200]}")
    except Exception as e:
        logger.warning(f"[audio] transcode_to_mp3 error: {e}")

    return None
