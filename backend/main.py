"""Iteration 2 backend: extract preview frames and OCR them with bounding boxes.

Requires the Tesseract binary on PATH (macOS: `brew install tesseract`).

Run with:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import difflib
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import imageio_ffmpeg
import pytesseract
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

# Frames are extracted every FRAME_INTERVAL_SECONDS seconds.
FRAME_INTERVAL_SECONDS = 0.5
# Difference-hash grid size; the hash has DHASH_SIZE^2 bits.
DHASH_SIZE = 16
# Consecutive frames whose hashes differ by at most this many bits are
# considered duplicates (tolerates clock ticks and status-bar noise while
# still catching a single new chat bubble).
DUPLICATE_MAX_BIT_DISTANCE = 3
# Lines on the same side closer than this many line-heights merge into one bubble.
BUBBLE_MAX_GAP_FACTOR = 1.2
# Normalized-text similarity at or above which two bubbles are the same message.
MERGE_SIMILARITY_THRESHOLD = 0.88
# Recording directories older than this are deleted by the background sweep.
RETENTION_SECONDS = 15 * 60
SWEEP_INTERVAL_SECONDS = 60

STORAGE_DIR = Path(__file__).parent / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Recording Frame Extractor")
app.mount("/frames", StaticFiles(directory=STORAGE_DIR), name="frames")


class OcrText(BaseModel):
    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float


class FramePreview(BaseModel):
    id: str
    timestampSeconds: float
    url: str
    texts: list[OcrText]


class TranscriptMessage(BaseModel):
    text: str
    senderHint: str  # "left", "right", or "unknown"
    confidence: float
    firstSeenSeconds: float
    lastSeenSeconds: float
    evidenceFrameIds: list[str]


class AnalyzeResponse(BaseModel):
    recordingId: str
    frameCount: int
    duplicateFramesDropped: int
    frames: list[FramePreview]
    transcript: list[TranscriptMessage]


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


def _dhash(image_path: Path) -> int:
    """Difference hash: 1 bit per adjacent-pixel brightness comparison."""
    with Image.open(image_path) as img:
        small = img.convert("L").resize((DHASH_SIZE + 1, DHASH_SIZE), Image.LANCZOS)
        pixels = list(small.getdata())
    bits = 0
    for row in range(DHASH_SIZE):
        for col in range(DHASH_SIZE):
            left = pixels[row * (DHASH_SIZE + 1) + col]
            right = pixels[row * (DHASH_SIZE + 1) + col + 1]
            bits = (bits << 1) | (left > right)
    return bits


def _drop_duplicate_frames(frame_paths: list[Path]) -> list[tuple[int, Path]]:
    """Keep only frames that differ visually from the last kept frame.

    Returns (original_index, path) pairs so timestamps stay accurate;
    dropped frame files are deleted from disk.
    """
    kept: list[tuple[int, Path]] = []
    last_hash: int | None = None
    for index, path in enumerate(frame_paths):
        frame_hash = _dhash(path)
        if last_hash is not None and (frame_hash ^ last_hash).bit_count() <= DUPLICATE_MAX_BIT_DISTANCE:
            path.unlink()
            continue
        last_hash = frame_hash
        kept.append((index, path))
    return kept


def _ocr_frame(image_path: Path) -> list[OcrText]:
    """Recognize text in one frame, grouped into visual lines with merged boxes."""
    data = pytesseract.image_to_data(str(image_path), output_type=pytesseract.Output.DICT)

    lines: dict[tuple[int, int, int], dict] = {}
    for i, raw_word in enumerate(data["text"]):
        word = raw_word.strip()
        confidence = float(data["conf"][i])
        # Tesseract emits structural rows (blocks/paragraphs) with conf -1.
        if not word or confidence < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left, top = data["left"][i], data["top"][i]
        right, bottom = left + data["width"][i], top + data["height"][i]
        line = lines.setdefault(
            key,
            {"words": [], "confs": [], "left": left, "top": top, "right": right, "bottom": bottom},
        )
        line["words"].append(word)
        line["confs"].append(confidence)
        line["left"] = min(line["left"], left)
        line["top"] = min(line["top"], top)
        line["right"] = max(line["right"], right)
        line["bottom"] = max(line["bottom"], bottom)

    return [
        OcrText(
            text=" ".join(line["words"]),
            left=line["left"],
            top=line["top"],
            right=line["right"],
            bottom=line["bottom"],
            confidence=round(sum(line["confs"]) / len(line["confs"]) / 100, 3),
        )
        for _, line in sorted(lines.items())
    ]


def _line_side(line: OcrText, frame_width: int) -> str:
    """Classify a text line as a left or right chat bubble by its margins."""
    left_margin = line.left
    right_margin = frame_width - line.right
    # Full-width text (headers, timestamps, system notices) has no clear side.
    if line.right - line.left > frame_width * 0.85:
        return "unknown"
    if left_margin < right_margin * 0.66:
        return "left"
    if right_margin < left_margin * 0.66:
        return "right"
    return "unknown"


def _group_bubbles(texts: list[OcrText], frame_width: int) -> list[dict]:
    """Group OCR lines into message-bubble candidates (Iteration 3).

    Consecutive lines on the same side separated by less than
    BUBBLE_MAX_GAP_FACTOR line-heights are treated as one wrapped message.
    """
    bubbles: list[dict] = []
    for line in sorted(texts, key=lambda t: t.top):
        side = _line_side(line, frame_width)
        line_height = line.bottom - line.top
        prev = bubbles[-1] if bubbles else None
        if (
            prev is not None
            and side == prev["side"]
            and line.top - prev["bottom"] < line_height * BUBBLE_MAX_GAP_FACTOR
        ):
            prev["parts"].append(line.text)
            prev["confs"].append(line.confidence)
            prev["bottom"] = max(prev["bottom"], line.bottom)
            continue
        bubbles.append(
            {
                "parts": [line.text],
                "confs": [line.confidence],
                "side": side,
                "top": line.top,
                "bottom": line.bottom,
            }
        )
    return [
        {
            "text": " ".join(b["parts"]),
            "senderHint": b["side"],
            "confidence": round(sum(b["confs"]) / len(b["confs"]), 3),
            "top": b["top"],
        }
        for b in bubbles
    ]


def _normalize(text: str) -> str:
    return " ".join("".join(c.lower() for c in text if c.isalnum() or c.isspace()).split())


def _merge_into_transcript(
    transcript: list[dict], bubbles: list[dict], frame_id: str, timestamp: float
) -> None:
    """Fold one frame's bubbles into the running transcript (Iteration 4).

    A bubble matches an existing message when the sender hints are
    compatible and the normalized texts are near-identical, which absorbs
    small OCR differences between frames of the same on-screen message.
    """
    for bubble in bubbles:
        normalized = _normalize(bubble["text"])
        if not normalized:
            continue
        match = None
        for message in transcript:
            if bubble["senderHint"] != "unknown" != message["senderHint"] and (
                bubble["senderHint"] != message["senderHint"]
            ):
                continue
            similarity = difflib.SequenceMatcher(None, normalized, message["normalized"]).ratio()
            if similarity >= MERGE_SIMILARITY_THRESHOLD:
                match = message
                break
        if match is None:
            transcript.append(
                {
                    "text": bubble["text"],
                    "normalized": normalized,
                    "senderHint": bubble["senderHint"],
                    "confidence": bubble["confidence"],
                    "firstSeenSeconds": timestamp,
                    "lastSeenSeconds": timestamp,
                    "evidenceFrameIds": [frame_id],
                }
            )
            continue
        match["lastSeenSeconds"] = timestamp
        match["evidenceFrameIds"].append(frame_id)
        if bubble["confidence"] > match["confidence"]:
            # Prefer the cleanest OCR reading of this message seen so far.
            match["text"] = bubble["text"]
            match["normalized"] = normalized
            match["confidence"] = bubble["confidence"]
        if match["senderHint"] == "unknown":
            match["senderHint"] = bubble["senderHint"]


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

    kept_frames = await asyncio.to_thread(_drop_duplicate_frames, frame_paths)

    frames: list[FramePreview] = []
    transcript: list[dict] = []
    for index, path in kept_frames:
        timestamp = round(index * FRAME_INTERVAL_SECONDS, 3)
        texts = await asyncio.to_thread(_ocr_frame, path)
        frames.append(
            FramePreview(
                id=path.stem,
                timestampSeconds=timestamp,
                url=f"/frames/{recording_id}/{path.name}",
                texts=texts,
            )
        )
        with Image.open(path) as img:
            frame_width = img.width
        bubbles = _group_bubbles(texts, frame_width)
        _merge_into_transcript(transcript, bubbles, path.stem, timestamp)

    return AnalyzeResponse(
        recordingId=recording_id,
        frameCount=len(frames),
        duplicateFramesDropped=len(frame_paths) - len(frames),
        frames=frames,
        transcript=[TranscriptMessage(**{k: v for k, v in m.items() if k != "normalized"}) for m in transcript],
    )


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
