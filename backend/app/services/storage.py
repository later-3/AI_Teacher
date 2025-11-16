from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Tuple

from fastapi import UploadFile
from yt_dlp import YoutubeDL

from ..config import get_settings
from ..logging_utils import log_event

settings = get_settings()


def get_resource_dir(resource_id: int) -> Path:
    root = settings.storage_root
    root.mkdir(parents=True, exist_ok=True)
    resource_dir = root / f"resource_{resource_id}"
    resource_dir.mkdir(parents=True, exist_ok=True)
    return resource_dir


def download_audio_from_url(resource_id: int, url: str) -> Path:
    """Download audio using yt-dlp and return audio file path."""
    resource_dir = get_resource_dir(resource_id)
    output_template = str(resource_dir / "source.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "noplaylist": True,
    }
    log_event(resource_id, "downloading", "yt-dlp download", url=url)
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded_path = Path(ydl.prepare_filename(info))
    return downloaded_path


def convert_to_wav(resource_id: int, input_path: Path) -> Path:
    wav_path = input_path.with_suffix(".wav")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(wav_path),
    ]
    log_event(resource_id, "audio_extracting", "ffmpeg convert", cmd=" ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True)
    return wav_path


def save_uploaded_file(resource_id: int, upload: UploadFile) -> Path:
    """Save an uploaded file to the resource directory."""
    resource_dir = get_resource_dir(resource_id)
    target_path = resource_dir / upload.filename
    with target_path.open("wb") as out_file:
        shutil.copyfileobj(upload.file, out_file)
    return target_path
