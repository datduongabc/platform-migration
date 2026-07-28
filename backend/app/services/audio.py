import asyncio
import json

import os
import shutil
import subprocess
from typing import Optional


_FFPROBE_AVAILABLE: Optional[bool] = None
_FFMPEG_AVAILABLE: Optional[bool] = None


# Check if ffprobe executable is available in system PATH
def is_ffprobe_available() -> bool:
    global _FFPROBE_AVAILABLE
    if _FFPROBE_AVAILABLE is None:
        _FFPROBE_AVAILABLE = shutil.which("ffprobe") is not None
    return _FFPROBE_AVAILABLE


# Check if ffmpeg executable is available in system PATH
def is_ffmpeg_available() -> bool:
    global _FFMPEG_AVAILABLE
    if _FFMPEG_AVAILABLE is None:
        _FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
    return _FFMPEG_AVAILABLE


async def get_audio_duration_seconds(file_path: str) -> float:
    if not is_ffprobe_available():
        print("[audio] ffprobe is not available on this system.")
        return 0.0

    if not os.path.exists(file_path):
        print(f"[audio] Input file for ffprobe does not exist: {file_path}")
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

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            print(f"[audio] ffprobe timed out for file: {file_path}")
            try:
                proc.kill()
            except Exception:
                pass
            return 0.0

        if proc.returncode == 0 and stdout:
            data = json.loads(stdout.decode("utf-8"))
            duration_str = data.get("format", {}).get("duration")
            if duration_str:
                return float(duration_str)
        elif stderr:
            print(f"[audio] ffprobe stderr: {stderr.decode('utf-8')[:200]}")
    except Exception as e:
        print(f"[audio] get_audio_duration_seconds error: {e}")

    return 0.0


async def transcode_to_mp3(input_path: str, output_path: str) -> Optional[str]:
    if not is_ffmpeg_available():
        print("[audio] ffmpeg is not available on this system.")
        return None

    if not os.path.exists(input_path):
        print(f"[audio] Input file for ffmpeg transcode does not exist: {input_path}")
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

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            print(f"[audio] ffmpeg transcode timed out for file: {input_path}")
            try:
                proc.kill()
            except Exception:
                pass
            return None

        if proc.returncode == 0 and stdout and os.path.exists(output_path):
            return output_path
        elif stderr:
            print(f"[audio] ffmpeg transcode stderr: {stderr.decode('utf-8')[:200]}")
    except Exception as e:
        print(f"[audio] transcode_to_mp3 error: {e}")

    return None
