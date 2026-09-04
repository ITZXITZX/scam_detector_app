"""Iteration 1 backend: extract preview frames from an uploaded screen recording.

Run with:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import imageio_ffmpeg
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Frames are extracted every FRAME_INTERVAL_SECONDS seconds.
FRAME_INTERVAL_SECONDS = 0.5
# Recording directories older than this are deleted by the background sweep.
RETENTION_SECONDS = 15 * 60
SWEEP_INTERVAL_SECONDS = 60

STORAGE_DIR = Path(__file__).parent / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Recording Frame Extractor")
app.mount("/frames", StaticFiles(directory=STORAGE_DIR), name="frames")


class FramePreview(BaseModel):
    id: str
    timestampSeconds: float
    url: str


class AnalyzeResponse(BaseModel):
    recordingId: str
    frameCount: int
    frames: list[FramePreview]


def _extract_frames(video_path: Path, output_dir: Path) -> list[Path]:
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    fps = 1 / FRAME_INTERVAL_SECONDS
    pattern = str(output_dir / "frame_%04d.jpg")
    result = subprocess.run(
        [
            ffmpeg_exe,
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps}",
            "-qscale:v",
            "3",
            pattern,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")
    return sorted(output_dir.glob("frame_*.jpg"))


@app.post("/recordings/analyze", response_model=AnalyzeResponse)
async def analyze_recording(file: UploadFile) -> AnalyzeResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    recording_id = uuid.uuid4().hex[:12]
    recording_dir = STORAGE_DIR / recording_id
    recording_dir.mkdir(parents=True)

    video_path = recording_dir / "source.mp4"
    with video_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        frame_paths = await asyncio.to_thread(_extract_frames, video_path, recording_dir)
    except RuntimeError as exc:
        shutil.rmtree(recording_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        # The source video is only needed for frame extraction, not for preview.
        video_path.unlink(missing_ok=True)

    frames = [
        FramePreview(
            id=path.stem,
            timestampSeconds=round(index * FRAME_INTERVAL_SECONDS, 3),
            url=f"/frames/{recording_id}/{path.name}",
        )
        for index, path in enumerate(frame_paths)
    ]

    return AnalyzeResponse(recordingId=recording_id, frameCount=len(frames), frames=frames)


async def _sweep_old_recordings() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        now = time.time()
        for child in STORAGE_DIR.iterdir():
            if child.is_dir() and now - child.stat().st_mtime > RETENTION_SECONDS:
                shutil.rmtree(child, ignore_errors=True)


@app.on_event("startup")
async def _start_sweeper() -> None:
    asyncio.create_task(_sweep_old_recordings())
