"""Iteration 1-2 backend: extract preview frames and OCR text from an uploaded
screen recording.

Run with:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Note: RapidOCR downloads its ONNX detection/classification/recognition models
(a few MB) on first use and caches them under the rapidocr package directory,
so the first OCR request needs network access; later requests run offline.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import imageio_ffmpeg
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if TYPE_CHECKING:
    from rapidocr import RapidOCR

# Recording ids are generated as uuid4().hex[:12]; reject anything else to
# avoid path traversal through the recording_id path parameter.
_RECORDING_ID_PATTERN = re.compile(r"^[0-9a-f]{8,32}$")

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


class OCRText(BaseModel):
    text: str
    left: float
    top: float
    right: float
    bottom: float
    confidence: float


class FrameOCRResult(BaseModel):
    frameId: str
    texts: list[OCRText]


class OCRResponse(BaseModel):
    recordingId: str
    frames: list[FrameOCRResult]


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


_ocr_engine: "RapidOCR | None" = None
_ocr_engine_lock = threading.Lock()


def _get_ocr_engine() -> "RapidOCR":
    # RapidOCR loads its onnx models on first use, so build it lazily once
    # instead of slowing down every server startup.
    global _ocr_engine
    if _ocr_engine is None:
        with _ocr_engine_lock:
            if _ocr_engine is None:
                from rapidocr import RapidOCR

                _ocr_engine = RapidOCR()
    return _ocr_engine


def _run_ocr_on_frame(frame_path: Path) -> list[OCRText]:
    engine = _get_ocr_engine()
    result = engine(str(frame_path))
    if result.boxes is None or result.txts is None or result.scores is None:
        return []

    texts: list[OCRText] = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        texts.append(
            OCRText(
                text=text,
                left=round(float(min(xs)), 1),
                top=round(float(min(ys)), 1),
                right=round(float(max(xs)), 1),
                bottom=round(float(max(ys)), 1),
                confidence=round(float(score), 4),
            )
        )
    return texts


@app.post("/recordings/{recording_id}/ocr", response_model=OCRResponse)
async def ocr_recording(recording_id: str) -> OCRResponse:
    if not _RECORDING_ID_PATTERN.match(recording_id):
        raise HTTPException(status_code=400, detail="Invalid recording id")

    recording_dir = STORAGE_DIR / recording_id
    if not recording_dir.is_dir():
        raise HTTPException(status_code=404, detail="Recording not found")

    frame_paths = sorted(recording_dir.glob("frame_*.jpg"))
    if not frame_paths:
        raise HTTPException(status_code=404, detail="No extracted frames for this recording")

    results = await asyncio.gather(
        *(asyncio.to_thread(_run_ocr_on_frame, path) for path in frame_paths)
    )
    frames = [
        FrameOCRResult(frameId=path.stem, texts=texts)
        for path, texts in zip(frame_paths, results)
    ]
    return OCRResponse(recordingId=recording_id, frames=frames)


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
