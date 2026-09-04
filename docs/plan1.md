# Conversation Reconstruction Plan

## Goal

Reconstruct a messaging conversation from a user-provided screen recording, including message order, approximate sender, confidence, and evidence frames.

The system should use deterministic computer-vision steps wherever possible and use LangChain for ambiguous interpretation and structured output. It must not invent unreadable or missing message text.

## Proposed Pipeline

```text
Flutter screen recording
        |
        v
MP4 upload
        |
        v
Selected video frames
        |
        v
OCR with bounding boxes
        |
        v
Message-bubble grouping
        |
        v
Duplicate removal and ordering
        |
        v
LangChain structured reconstruction
        |
        v
Transcript and uncertainty review in Flutter
```

## Iterative SDLC Plan

Each iteration should produce a testable vertical slice. Do not build the full agent before validating the preceding data transformation.

### Iteration 0: Confirm the recording baseline

**Goal:** Verify that recordings are reliable inputs.

Tasks:

- Start and stop a recording.
- Confirm that the returned MP4 path exists.
- Play the resulting video.
- Test recording permission denial and cancellation.
- Check that recordings are not retained indefinitely in cache.

**Acceptance criterion:** A short messaging conversation can be recorded and retrieved as a playable MP4 consistently.

### Iteration 1: Extract frames from a recording

**Goal:** Prove that the MP4 contains useful screenshots.

Do not introduce LangChain or OCR yet.

Tasks:

- Create a small Python backend.
- Add `POST /recordings/analyze`.
- Accept an MP4 upload.
- Extract one JPEG frame approximately every 500 milliseconds using FFmpeg or PyAV.
- Store frames in a temporary directory.
- Return frame IDs, timestamps, and preview URLs.
- Add a Flutter action to upload a completed recording.
- Display extracted frames in a scrollable preview.
- Delete temporary files after processing or a short retention period.

Example response:

```json
{
  "recordingId": "abc123",
  "frameCount": 18,
  "frames": [
    {
      "id": "frame_0001",
      "timestampSeconds": 0.0,
      "url": "/frames/abc123/frame_0001.jpg"
    }
  ]
}
```

**Acceptance criterion:** Uploading a short recording produces readable frame previews at the expected timestamps.

This is the next implementation step. It tests whether the screen recording preserves enough visual information for later OCR.

### Iteration 2: Add OCR

**Status:** Implemented as a backend OCR service using `rapidocr` (ONNX models downloaded
and cached on first use, then run fully offline). A new `POST /recordings/{recordingId}/ocr`
endpoint OCRs the frames already extracted in Iteration 1 and returns text with bounding
boxes. The Flutter app adds an "Extract text (OCR)" action after frames are previewed.

**Goal:** Convert frames into text while preserving coordinates.

Possible implementations:

- Google ML Kit Text Recognition on Android.
- Apple Vision on iOS.
- A backend OCR service if the privacy and network tradeoffs are acceptable.

Each OCR result should include text, confidence, and a bounding box:

```json
{
  "frameId": "frame_0008",
  "texts": [
    {
      "text": "Can you send the report?",
      "left": 48,
      "top": 812,
      "right": 612,
      "bottom": 876,
      "confidence": 0.96
    }
  ]
}
```

Build a small fixture set containing one-to-one conversations, long wrapped messages, scrolling, emojis, links, edited messages, and light and dark mode.

**Acceptance criterion:** At least 90 percent of clearly visible message text is recognized correctly in representative recordings.

### Iteration 3: Group OCR text into message bubbles

**Goal:** Convert OCR lines into message candidates.

Use deterministic grouping based on:

- Vertical proximity.
- Horizontal overlap.
- Line spacing.
- Approximate bubble position.
- Frame timestamp.

Initially classify senders only as `left`, `right`, or `unknown`.

Example:

```json
{
  "frameId": "frame_0008",
  "messages": [
    {
      "text": "Can you send the report?",
      "senderHint": "right",
      "box": {
        "left": 48,
        "top": 812,
        "right": 612,
        "bottom": 876
      }
    }
  ]
}
```

**Acceptance criterion:** Text belonging to one visible message is grouped together without incorrectly merging separate messages.

### Iteration 4: Merge duplicates across frames

**Goal:** Produce a timeline instead of repeating the same message for every frame.

Merge candidates using:

- Normalized text.
- Approximate position.
- Sender hint.
- Nearby timestamps.
- Text similarity.

Preserve evidence frames:

```json
{
  "text": "Can you send the report?",
  "senderHint": "right",
  "firstSeenSeconds": 12.4,
  "lastSeenSeconds": 15.8,
  "evidenceFrameIds": [
    "frame_0025",
    "frame_0026",
    "frame_0027"
  ]
}
```

**Acceptance criterion:** A message visible across multiple frames appears once in the reconstructed transcript.

### Iteration 5: Introduce LangChain

**Goal:** Use an LLM only for interpretation that benefits from context.

LangChain may help with:

- Correcting obvious OCR errors.
- Deciding whether similar candidates are duplicates.
- Resolving ambiguous message boundaries.
- Assigning human-readable participant labels when evidence exists.
- Generating warnings and uncertainty explanations.

LangChain should receive compact, processed message candidates rather than the entire video or every raw frame.

Use structured output similar to:

```python
class Message(BaseModel):
    sender: str
    text: str
    timestamp_seconds: float | None
    confidence: float
    evidence_frame_ids: list[str]


class Conversation(BaseModel):
    participants: list[str]
    messages: list[Message]
    warnings: list[str]
```

The model instructions should state:

- Reconstruct only text supported by OCR candidates.
- Do not invent unreadable words.
- Preserve message order.
- Use `unknown` when the sender cannot be determined.
- Report conflicts and uncertainty.

**Acceptance criterion:** The model returns schema-valid output and does not hallucinate missing content in the test recordings.

### Iteration 6: Integrate the transcript into Flutter

**Goal:** Make the feature usable in the application.

Add:

- A `Process recording` action after recording stops.
- Upload progress.
- Processing and failure states.
- A transcript view.
- Confidence and warning indicators.
- Retry handling.
- Recording deletion behavior.

Target workflow:

```text
Start recording
    -> Stop recording
    -> Preview recording
    -> Process recording
    -> Review reconstructed conversation
```

**Acceptance criterion:** A user can record, process, and review a conversation without developer tools.

### Iteration 7: Privacy and reliability hardening

Before production use:

- Encrypt uploads in transit.
- Delete temporary videos and extracted frames after processing.
- Avoid logging raw message text.
- Add explicit consent and privacy messaging.
- Handle network failures and retries.
- Limit recording duration and upload size.
- Test recordings containing sensitive information.
- Display uncertainty instead of presenting guesses as facts.

## What Not to Build Yet

Avoid these until frame extraction and OCR are validated:

- A fully autonomous LangChain agent.
- OCR on every video frame.
- Automatic identity claims based only on color or position.
- Direct accessibility scraping as the primary strategy.
- Sending the complete video to an LLM.

The existing recorder produces an MP4, not a frame stream or text stream. Post-processing the saved MP4 is the simplest first implementation and is easier to retry and debug than live OCR during recording.

## Immediate Next Task

Implement Iteration 1 as a narrow prototype:

1. Create the backend upload endpoint.
2. Accept a completed MP4 from Flutter.
3. Extract one frame every 500 milliseconds.
4. Return frame timestamps and preview URLs.
5. Display the frames in Flutter.
6. Manually inspect whether message text is readable.

The milestone is complete when the team can answer:

> Do the extracted screenshots contain enough readable information to reconstruct the conversation?

That result determines whether to proceed with OCR, improve recording resolution and frame selection, or investigate another capture method.
