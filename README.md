# scam_detector_app

A new Flutter project.

## Quickstart

This iteration is a Flutter app that records the screen, uploads the recording
to a local FastAPI service, and displays preview frames extracted by the
service.

### Prerequisites

- Flutter SDK 3.x with Dart SDK 3.13.2 or later
- Python 3.10 or later
- Android Studio with an Android emulator, or Xcode with an iOS simulator
- Git

### 1. Get the code

From the repository root (the folder containing `pubspec.yaml`):

```powershell
git clone <repository-url>
cd scam_detector_app
```

If you already cloned the repository, just open a terminal at its root.

### 2. Set up and start the backend

The backend needs the Tesseract OCR binary on PATH:

- macOS: `brew install tesseract`
- Windows: install from https://github.com/UB-Mannheim/tesseract/wiki
- Linux: `sudo apt install tesseract-ocr`

Open a terminal and run (Windows PowerShell):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Keep this terminal running. The API is available at
`http://localhost:8000`; the app uses `http://10.0.2.2:8000` automatically
when it runs on an Android emulator.

### 3. Start an emulator and run the Flutter app

Start an Android emulator from Android Studio's Device Manager, or start an
iOS simulator from Xcode. In a second terminal, from the repository root, run:

```powershell
flutter pub get
flutter devices
flutter run
```

If more than one device is listed, choose one explicitly:

```powershell
flutter run -d <device-id>
```

Tap **Start recording**, grant the requested permission, tap **Stop
recording**, and then tap **Process recording** to upload the MP4 and view the
extracted frames.

### 3a. Test with a physical Android phone

This is an alternative to using an Android emulator. The phone and the computer running the backend must be connected to the same Wi-Fi network.

#### Enable USB debugging

1. On the phone, open **Settings > About phone** and tap **Build number** seven times to enable Developer options. The exact menu may vary by phone.
2. Open **Settings > System > Developer options** (or search Settings for “Developer options”).
3. Enable **Developer options**. Then within **Developer options**, enable **USB debugging**.
4. Connect the phone by USB, unlock it, and accept the **Allow USB debugging?** prompt. Verify that Flutter can see it:
   ```powershell
   flutter devices
   ```

#### Configure and test the local backend connection

Find the computer's Wi-Fi IPv4 address with:

```powershell
ipconfig
```

Use the IPv4 address under the connected **Wireless LAN adapter Wi-Fi** (for example, `192.168.1.14`). Do not use the WSL/Hyper-V address, `localhost`, or `10.0.2.2`; those addresses are for other environments.

Start the backend from the `backend` directory and bind it to the local network:

```powershell
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Keep this terminal running. Before installing or running the Flutter app, verify the backend on the computer:

```text
http://127.0.0.1:8000/docs
```

You can also verify that the port is listening:

```powershell
Test-NetConnection 127.0.0.1 -Port 8000
Test-NetConnection <computer-wifi-ip> -Port 8000
```

Both checks should report `TcpTestSucceeded : True`. If the first check fails, the backend is not running successfully. If the first succeeds but the second fails, check the Windows Firewall instructions below (you need to allow the backend through the Frewall).

On the phone's browser, open:

```text
http://<computer-wifi-ip>:8000/docs
```

The FastAPI documentation page should load. If it does not, confirm that the phone and computer are on the same Wi-Fi network and tthen check the Windows Firewall instructions below.

Finally, update `RecordingFramesApi.baseUrl` in
`lib/recording_frames_api.dart` to use the computer's Wi-Fi IP address:

```dart
return 'http://<computer-wifi-ip>:8000';
```

Then run the app on the connected phone:

```powershell
flutter run -d <phone-device-id>
```

#### Allow the backend through Windows Firewall

Only do this if the computer's `127.0.0.1` test succeeds but the phone cannot open `<wifi_ipv4_addr>/docs`.

1. Press `Win + R`, enter `control firewall.cpl`, and press **Enter**.
2. Select **Allow an app or feature through Windows Defender Firewall**.
3. Select **Change settings** and approve the administrator prompt.
4. If `Python` or `python.exe` is listed, enable **Private** and leave
   **Public** disabled.
5. If it is not listed, choose **Allow another app... > Browse...**, select the
   `python.exe` used to start Uvicorn, and add it. Then enable **Private** only.
6. Click **OK**, restart Uvicorn if necessary, and repeat the phone `/docs`
   test.

After testing, remove the exception: return to **Allow an app or feature through Windows Defender Firewall**, select **Change settings**, clear the **Private** checkbox for Python (or select the Python entry and click **Remove** if it was manually added), then click **OK**. Keep **Public**
unchecked throughout.

### Troubleshooting

- **Backend connection failed:** confirm the backend terminal is still running
    on port 8000. Android emulators must use `10.0.2.2`, which the app is already
    configured to do.
- **Using a physical phone:** the current client defaults to localhost or
    `10.0.2.2`. Update `RecordingFramesApi.baseUrl` in
    `lib/recording_frames_api.dart` to your computer's LAN IP, keep port 8000
    open on the computer, and put both devices on the same network.
- **Recording permission denied:** allow screen recording and notifications in
    the emulator/device settings, then restart the flow.



## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## Backend (frame extraction + OCR service)

The `backend/` folder contains a small FastAPI service that extracts preview
frames from an uploaded screen recording and runs Tesseract OCR on each frame,
returning per-line text with bounding boxes and confidence (Iterations 1 and 2
of `docs/plan1.md`).

### Setup

Follow the backend setup in [Quickstart](#2-set-up-and-start-the-backend).

### Run

PowerShell:

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Git Bash / WSL (the venv's executables live under `Scripts/`, not `bin/`, and
need an explicit `./` prefix):

```bash
cd backend
./.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

The server listens on `http://localhost:8000` (or `http://10.0.2.2:8000` from
the Android emulator). See [Quickstart](#3-start-an-emulator-and-run-the-flutter-app)
for the Flutter client flow and physical-device note.

### Test it without the Flutter app

From another terminal, generate a short synthetic video and upload it:

```powershell
cd backend
$ffmpeg = (.venv\Scripts\python.exe -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
& $ffmpeg -f lavfi -i "testsrc=duration=4:size=320x240:rate=10" -pix_fmt yuv420p test_input.mp4 -y
Invoke-RestMethod -Uri http://127.0.0.1:8000/recordings/analyze -Method Post -Form @{ file = Get-Item test_input.mp4 }
```

The JSON response lists `frameCount` and, for each frame, its `url` plus a
`texts` array of OCR results (`text`, `left`/`top`/`right`/`bottom` bounding
box, and `confidence` from 0 to 1). Confirm the
files exist on disk under `backend/storage/<recordingId>/`, or open
`http://127.0.0.1:8000/frames/<recordingId>/frame_0001.jpg` in a browser.

Recording folders are deleted automatically after 15 minutes (see
`RETENTION_SECONDS` in `backend/main.py`), so no manual cleanup is required.

