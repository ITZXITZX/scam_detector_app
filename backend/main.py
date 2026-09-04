"""Backend: extract frames, dedup, OCR, reconstruct the transcript, and assess scam risk.

Requires the Tesseract binary on PATH (macOS: `brew install tesseract`) for the
integrated /recordings/analyze pipeline. Set ANTHROPIC_API_KEY to enable the AI
scam-risk verdict; without it the analysis degrades gracefully.

Run with:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Note: RapidOCR downloads its ONNX detection/classification/recognition models
(a few MB) on first use and caches them under the rapidocr package directory,
so the first OCR request needs network access; later requests run offline.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
import imageio_ffmpeg
import pytesseract
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

if TYPE_CHECKING:
    from rapidocr import RapidOCR

# On Windows, tesseract.exe usually isn't on PATH after install; fall back to
# the default UB-Mannheim install location if the binary isn't otherwise found.
if os.name == "nt" and shutil.which("tesseract") is None:
    _default_tesseract = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if _default_tesseract.exists():
        pytesseract.pytesseract.tesseract_cmd = str(_default_tesseract)

# Recording ids are generated as uuid4().hex[:12]; reject anything else to
# avoid path traversal through the recording_id path parameter.
_RECORDING_ID_PATTERN = re.compile(r"^[0-9a-f]{8,32}$")

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


class ScamAnalysis(BaseModel):
    riskLevel: str  # "low", "medium", "high", or "unavailable"
    riskScore: int  # 0-100; 0 when unavailable
    summary: str
    flaggedMessageIndexes: list[int]
    warnings: list[str]


class AnalyzeResponse(BaseModel):
    recordingId: str
    frameCount: int
    duplicateFramesDropped: int
    frames: list[FramePreview]
    transcript: list[TranscriptMessage]
    analysis: ScamAnalysis


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


class _LlmCorrection(BaseModel):
    index: int
    text: str


class _LlmVerdict(BaseModel):
    riskLevel: str  # "low", "medium", or "high"
    riskScore: int
    summary: str
    flaggedMessageIndexes: list[int]
    corrections: list[_LlmCorrection]
    warnings: list[str]


_LLM_INSTRUCTIONS = """\
You are reviewing a messaging conversation reconstructed by OCR from a screen \
recording, to help the phone's owner decide whether they are being scammed.

You receive a JSON array of messages with fields index, senderHint \
("left" = other party, "right" = the user, "unknown"), text, and OCR confidence.

Rules:
- corrections: fix ONLY obvious OCR artifacts (e.g. "lam" for "I am", "|" for \
"I", "0" for "O") where the intended text is unambiguous from context. Return \
the full corrected message text. Never invent, complete, or paraphrase content \
that is not supported by the OCR text. If a message is garbled beyond confident \
repair, leave it out of corrections and add a warning instead.
- riskLevel/riskScore/summary: judge scam likelihood from classic signals \
(urgency pressure, payment or gift-card requests, unexpected fees, links to \
verify cards or credentials, impersonation of couriers/banks/officials, \
too-good-to-be-true offers). The summary is one short sentence naming the \
signals found, or stating that none were found.
- flaggedMessageIndexes: indexes of the specific messages containing those \
signals. Empty if none.
- warnings: uncertainty the user should know about (unreadable messages, \
ambiguous senders, possible missing messages). Empty if none.
"""


def _run_llm_analysis(transcript: list[dict]) -> tuple[ScamAnalysis, dict[int, str]]:
    """Ask Claude for OCR corrections and a scam verdict on the transcript.

    Returns the analysis plus {transcript index: corrected text}. Any failure
    (no API key, network, refusal) degrades to an "unavailable" analysis so the
    deterministic pipeline keeps working.
    """
    unavailable = ScamAnalysis(
        riskLevel="unavailable",
        riskScore=0,
        summary="AI analysis unavailable",
        flaggedMessageIndexes=[],
        warnings=[],
    )
    if not transcript or not os.environ.get("ANTHROPIC_API_KEY"):
        return unavailable, {}

    payload = [
        {
            "index": i,
            "senderHint": m["senderHint"],
            "text": m["text"],
            "confidence": m["confidence"],
        }
        for i, m in enumerate(transcript)
    ]
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model="claude-opus-5",
            max_tokens=16000,
            system=_LLM_INSTRUCTIONS,
            messages=[{"role": "user", "content": json.dumps(payload)}],
            output_format=_LlmVerdict,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return unavailable, {}
        verdict = response.parsed_output
    except Exception:
        return unavailable, {}

    valid = range(len(transcript))
    analysis = ScamAnalysis(
        riskLevel=verdict.riskLevel if verdict.riskLevel in ("low", "medium", "high") else "unavailable",
        riskScore=max(0, min(100, verdict.riskScore)),
        summary=verdict.summary,
        flaggedMessageIndexes=[i for i in verdict.flaggedMessageIndexes if i in valid],
        warnings=verdict.warnings,
    )
    corrections = {c.index: c.text for c in verdict.corrections if c.index in valid and c.text.strip()}
    return analysis, corrections


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

    analysis, corrections = await asyncio.to_thread(_run_llm_analysis, transcript)
    for i, corrected_text in corrections.items():
        transcript[i]["text"] = corrected_text

    return AnalyzeResponse(
        recordingId=recording_id,
        frameCount=len(frames),
        duplicateFramesDropped=len(frame_paths) - len(frames),
        frames=frames,
        transcript=[TranscriptMessage(**{k: v for k, v in m.items() if k != "normalized"}) for m in transcript],
        analysis=analysis,
    )


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
