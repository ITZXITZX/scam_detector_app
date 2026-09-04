import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_screen_recording/flutter_screen_recording.dart';
import 'package:permission_handler/permission_handler.dart';

import 'recording_frames_api.dart';

void main() {
  runApp(const ScamDetectorApp());
}

class ScamDetectorApp extends StatelessWidget {
  const ScamDetectorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Scam Detector',
      theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
      home: const RecordingHomePage(),
    );
  }
}

enum _Stage { idle, recording, recorded, uploading, done }

class RecordingHomePage extends StatefulWidget {
  const RecordingHomePage({super.key});

  @override
  State<RecordingHomePage> createState() => _RecordingHomePageState();
}

class _RecordingHomePageState extends State<RecordingHomePage> {
  _Stage _stage = _Stage.idle;
  String? _recordingPath;
  String? _errorMessage;
  AnalyzeResult? _result;

  Future<bool> _ensurePermissions() async {
    // Android 13+ requires explicit notification permission for the
    // foreground service that keeps the recording alive.
    if (Platform.isAndroid) {
      final status = await Permission.notification.request();
      if (!status.isGranted) {
        setState(() => _errorMessage = 'Notification permission is required to record the screen.');
        return false;
      }
    }
    return true;
  }

  Future<void> _startRecording() async {
    setState(() => _errorMessage = null);

    if (!await _ensurePermissions()) return;

    final name = 'recording_${DateTime.now().millisecondsSinceEpoch}';
    final started = await FlutterScreenRecording.startRecordScreen(name);
    if (!started) {
      setState(() => _errorMessage = 'Failed to start screen recording.');
      return;
    }
    setState(() => _stage = _Stage.recording);
  }

  Future<void> _stopRecording() async {
    final path = await FlutterScreenRecording.stopRecordScreen;
    if (path.isEmpty || !File(path).existsSync()) {
      setState(() {
        _stage = _Stage.idle;
        _errorMessage = 'Recording did not produce a playable file.';
      });
      return;
    }
    setState(() {
      _stage = _Stage.recorded;
      _recordingPath = path;
    });
  }

  Future<void> _processRecording() async {
    if (_recordingPath == null) return;
    setState(() {
      _stage = _Stage.uploading;
      _errorMessage = null;
    });

    try {
      final result = await RecordingFramesApi.analyzeRecording(File(_recordingPath!));
      setState(() {
        _stage = _Stage.done;
        _result = result;
      });
    } catch (err) {
      setState(() {
        _stage = _Stage.recorded;
        _errorMessage = 'Processing failed: $err';
      });
    }
  }

  void _reset() {
    setState(() {
      _stage = _Stage.idle;
      _recordingPath = null;
      _result = null;
      _errorMessage = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Conversation Recorder')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _buildControls(),
            if (_errorMessage != null) ...[
              const SizedBox(height: 12),
              Text(_errorMessage!, style: const TextStyle(color: Colors.red)),
            ],
            const SizedBox(height: 24),
            if (_result != null) Expanded(child: _buildFramePreview(_result!)),
          ],
        ),
      ),
    );
  }

  Widget _buildControls() {
    switch (_stage) {
      case _Stage.idle:
        return ElevatedButton.icon(
          onPressed: _startRecording,
          icon: const Icon(Icons.fiber_manual_record),
          label: const Text('Start recording'),
        );
      case _Stage.recording:
        return ElevatedButton.icon(
          onPressed: _stopRecording,
          icon: const Icon(Icons.stop),
          label: const Text('Stop recording'),
        );
      case _Stage.recorded:
        return Row(
          children: [
            Expanded(
              child: ElevatedButton.icon(
                onPressed: _processRecording,
                icon: const Icon(Icons.upload),
                label: const Text('Process recording'),
              ),
            ),
            const SizedBox(width: 8),
            TextButton(onPressed: _reset, child: const Text('Discard')),
          ],
        );
      case _Stage.uploading:
        return const Row(
          children: [
            SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: 12),
            Text('Extracting frames...'),
          ],
        );
      case _Stage.done:
        return ElevatedButton.icon(
          onPressed: _reset,
          icon: const Icon(Icons.refresh),
          label: const Text('Record another'),
        );
    }
  }

  Widget _buildFramePreview(AnalyzeResult result) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('${result.frameCount} frames extracted', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        SizedBox(
          // Fixed row height keeps every thumbnail's aspect ratio consistent
          // instead of stretching to whatever space happens to be left.
          height: 400,
          child: ListView.builder(
            scrollDirection: Axis.horizontal,
            itemCount: result.frames.length,
            itemBuilder: (context, index) {
              final frame = result.frames[index];
              return Padding(
                padding: const EdgeInsets.only(right: 8),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 160,
                      height: 284,
                      decoration: BoxDecoration(
                        color: Colors.black12,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      clipBehavior: Clip.antiAlias,
                      child: Image.network(
                        RecordingFramesApi.resolveFrameUrl(frame.url),
                        fit: BoxFit.contain,
                        errorBuilder: (context, error, stackTrace) =>
                            const Icon(Icons.broken_image),
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text('${frame.timestampSeconds.toStringAsFixed(1)}s'),
                    if (frame.texts.isNotEmpty)
                      SizedBox(
                        width: 160,
                        child: Text(
                          frame.texts.map((t) => t.text).join('\n'),
                          maxLines: 4,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}
