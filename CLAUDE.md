# scam_detector_app

Flutter app + FastAPI backend that reconstructs a messaging conversation from
a screen recording (record → extract frames → dedup → OCR → bubble grouping →
merged transcript JSON). The roadmap lives in `docs/plan1.md`; iterations 1–4
are implemented.

## Design-first workflow (required)

Before writing or changing any code that affects what the user sees or how
they operate the app (new screens, new buttons, changed flows, new API
response shapes that drive UI), you MUST first present a design for review
and wait for explicit approval:

1. Show a wireframe of the affected screen(s) — an ASCII mockup or a design
   artifact is fine — plus a short step-by-step of how the user operates the
   feature (what they tap, what happens next).
2. If the backend API changes, include the proposed JSON shape.
3. Only start implementing after the user approves or amends the design.

Pure bug fixes, refactors, and backend-internal changes with no visible
behavior change do not need a design pass — but say so explicitly when
skipping it.

## Running the project

- Backend: `cd backend && ./.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000`
  (needs `brew install tesseract`; Android emulator reaches it at `http://10.0.2.2:8000`)
- App: `flutter run` (an Android 35 AVD named `scam_detector_pixel` exists;
  start it with `$ANDROID_HOME/emulator/emulator -avd scam_detector_pixel`,
  SDK at `/opt/homebrew/share/android-commandlinetools`)
- `third_party/flutter_screen_recording_patched/` is a vendored copy of the
  recording plugin (published package still references jcenter) — don't
  replace it with the pub.dev version.
