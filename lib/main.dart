import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_screen_recording/flutter_screen_recording.dart';
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';

import 'recording_frames_api.dart';

/// Bundled screen recording used by the "Use sample recording" test button.
const _sampleRecordingAsset = 'assets/sample/authority-scam-01.mp4';

void main() {
  runApp(const ScamDetectorApp());
}

class ScamDetectorApp extends StatelessWidget {
  const ScamDetectorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Scam Detector',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
      home: const RecordingHomePage(),
    );
  }
}

enum _Stage { idle, recording, recorded, uploading, framesReady, analysing, done }

class RecordingHomePage extends StatefulWidget {
  const RecordingHomePage({super.key});

  @override
  State<RecordingHomePage> createState() => _RecordingHomePageState();
}

class _RecordingHomePageState extends State<RecordingHomePage> {
  _Stage _stage = _Stage.idle;
  String? _recordingPath;
  String? _errorMessage;
  FramesResult? _frames;
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
      final frames = await RecordingFramesApi.createRecordingFromVideo(File(_recordingPath!));
      setState(() {
        _stage = _Stage.framesReady;
        _frames = frames;
      });
    } catch (err) {
      setState(() {
        _stage = _Stage.recorded;
        _errorMessage = 'Processing failed: $err';
      });
    }
  }

  /// Step 2, and the only step that spends API calls, so the user triggers it
  /// after seeing which frames were actually captured.
  Future<void> _analyseConversation() async {
    final recordingId = _frames?.recordingId;
    if (recordingId == null) return;
    setState(() {
      _stage = _Stage.analysing;
      _errorMessage = null;
    });

    try {
      final result = await RecordingFramesApi.analyzeRecording(recordingId);
      setState(() {
        _stage = _Stage.done;
        _result = result;
      });
    } catch (err) {
      setState(() {
        _stage = _Stage.framesReady;
        _errorMessage = 'Analysis failed: $err';
      });
    }
  }

  /// Alternative to recording: analyse screenshots already on the phone.
  Future<void> _uploadImages() async {
    setState(() => _errorMessage = null);
    final picked = await ImagePicker().pickMultiImage();
    if (picked.isEmpty) return;

    setState(() => _stage = _Stage.uploading);
    try {
      final frames = await RecordingFramesApi.createRecordingFromImages(
        picked.map((x) => File(x.path)).toList(),
      );
      setState(() {
        _stage = _Stage.framesReady;
        _frames = frames;
      });
    } catch (err) {
      setState(() {
        _stage = _Stage.idle;
        _errorMessage = 'Upload failed: $err';
      });
    }
  }

  /// Copies the bundled sample recording to a temp file and treats it exactly
  /// like a fresh screen recording, so the normal upload path is exercised.
  Future<void> _useSampleRecording() async {
    setState(() => _errorMessage = null);
    try {
      final data = await rootBundle.load(_sampleRecordingAsset);
      final file = File(
        '${Directory.systemTemp.path}/sample_recording_'
        '${DateTime.now().millisecondsSinceEpoch}.mp4',
      );
      await file.writeAsBytes(data.buffer.asUint8List(), flush: true);
      setState(() {
        _recordingPath = file.path;
        _stage = _Stage.recorded;
      });
    } catch (err) {
      setState(() => _errorMessage = 'Could not load sample recording: $err');
    }
  }

  void _reset() {
    setState(() {
      _stage = _Stage.idle;
      _recordingPath = null;
      _frames = null;
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
            if (_frames != null) Expanded(child: _buildResults(_frames!, _result)),
          ],
        ),
      ),
    );
  }

  Widget _buildControls() {
    switch (_stage) {
      case _Stage.idle:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ElevatedButton.icon(
              onPressed: _startRecording,
              icon: const Icon(Icons.fiber_manual_record),
              label: const Text('Start recording'),
            ),
            // Test affordance: runs the analyze pipeline on a bundled sample
            // recording, so it can be exercised without recording first.
            // TODO: wrap in `if (kDebugMode)` before shipping a release build.
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _uploadImages,
              icon: const Icon(Icons.photo_library_outlined),
              label: const Text('Upload images'),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _useSampleRecording,
              icon: const Icon(Icons.play_circle_outline),
              label: const Text('Use sample recording'),
            ),
          ],
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
      case _Stage.framesReady:
        return Row(
          children: [
            Expanded(
              child: ElevatedButton.icon(
                onPressed: _analyseConversation,
                icon: const Icon(Icons.auto_awesome),
                label: const Text('Analyse conversation'),
              ),
            ),
            const SizedBox(width: 8),
            TextButton(onPressed: _reset, child: const Text('Discard')),
          ],
        );
      case _Stage.analysing:
        return const Row(
          children: [
            SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: 12),
            Text('Reading conversation & assessing risk...'),
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

  Widget _buildRiskBanner(ScamAnalysis analysis) {
    if (analysis.riskLevel == 'unavailable') {
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Text(
          'AI scam analysis unavailable (no API key configured)',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      );
    }
    final (color, icon, label) = switch (analysis.riskLevel) {
      'high' => (Colors.red.shade100, Icons.warning_amber_rounded, 'LIKELY SCAM'),
      'medium' => (Colors.amber.shade100, Icons.help_outline, 'SUSPICIOUS'),
      _ => (Colors.green.shade100, Icons.check_circle_outline, 'LOOKS SAFE'),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(12)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 20),
              const SizedBox(width: 8),
              Text(label, style: Theme.of(context).textTheme.titleMedium),
              const Spacer(),
              Text('risk ${analysis.riskScore}/100'),
            ],
          ),
          const SizedBox(height: 4),
          Text(analysis.summary),
          for (final warning in analysis.warnings)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('• $warning', style: Theme.of(context).textTheme.bodySmall),
            ),
        ],
      ),
    );
  }

  Widget _buildTranscriptBubble(TranscriptMessage message, {required bool flagged}) {
    final isRight = message.senderHint == 'right';
    final isUnknown = message.senderHint == 'unknown';
    final colorScheme = Theme.of(context).colorScheme;
    return Align(
      alignment: isUnknown
          ? Alignment.center
          : (isRight ? Alignment.centerRight : Alignment.centerLeft),
      child: Container(
        constraints: const BoxConstraints(maxWidth: 280),
        margin: const EdgeInsets.symmetric(vertical: 3),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: isUnknown
              ? colorScheme.surfaceContainerHighest
              : (isRight ? colorScheme.primaryContainer : colorScheme.secondaryContainer),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(flagged ? '🚩 ${message.text}' : message.text),
            Text(
              '${message.firstSeenSeconds.toStringAsFixed(1)}s · '
              '${message.evidenceFrameIds.length} frame${message.evidenceFrameIds.length == 1 ? '' : 's'}',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildResults(FramesResult frames, AnalyzeResult? result) {
    final flagged = result?.analysis?.flaggedMessageIndexes.toSet() ?? const <int>{};
    return ListView(
      children: [
        if (result?.analysis != null) _buildRiskBanner(result!.analysis!),
        if (result != null && result.transcript.isNotEmpty) ...[
          Text('Reconstructed conversation', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          for (final (index, message) in result.transcript.indexed)
            _buildTranscriptBubble(message, flagged: flagged.contains(index)),
          const SizedBox(height: 24),
        ],
        Text(
          '${frames.frameCount} unique frames'
          '${frames.duplicateFramesDropped > 0 ? ' (${frames.duplicateFramesDropped} duplicates removed)' : ''}',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        SizedBox(
          // Fixed row height keeps every thumbnail's aspect ratio consistent
          // instead of stretching to whatever space happens to be left.
          height: 400,
          child: ListView.builder(
            scrollDirection: Axis.horizontal,
            itemCount: frames.frames.length,
            itemBuilder: (context, index) {
              final frame = frames.frames[index];
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
