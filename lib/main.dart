import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_screen_recording/flutter_screen_recording.dart';
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';

import 'backend_config.dart';
import 'backend_settings_screen.dart';
import 'campaign_feed.dart';
import 'device_user.dart';
import 'profile_screen.dart';
import 'recording_frames_api.dart';

/// Bundled screen recording used by the "Use sample recording" test button.
const _sampleRecordingAsset = 'assets/sample/authority-scam-01.mp4';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await BackendConfig.initialize();
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

enum _Stage {
  idle,
  recording,
  recorded,
  uploading,
  framesReady,
  analysing,
  done,
}

class RecordingHomePage extends StatefulWidget {
  const RecordingHomePage({super.key});

  @override
  State<RecordingHomePage> createState() => _RecordingHomePageState();
}

class _RecordingHomePageState extends State<RecordingHomePage> {
  _Stage _stage = _Stage.idle;
  String? _deviceUserId;
  String? _recordingPath;
  String? _errorMessage;
  FramesResult? _frames;
  AnalyzeResult? _result;
  RiskProfile? _profile;
  int _titleTapCount = 0;

  @override
  void initState() {
    super.initState();
    // Resolved once so the feed can be built synchronously afterwards.
    DeviceUser.id().then((id) {
      if (mounted) setState(() => _deviceUserId = id);
    });
  }

  Future<bool> _ensurePermissions() async {
    // Android 13+ requires explicit notification permission for the
    // foreground service that keeps the recording alive.
    if (Platform.isAndroid) {
      final status = await Permission.notification.request();
      if (!status.isGranted) {
        setState(
          () => _errorMessage =
              'Notification permission is required to record the screen.',
        );
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
      final frames = await RecordingFramesApi.createRecordingFromVideo(
        File(_recordingPath!),
      );
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
      final userId = await DeviceUser.id();
      final result = await RecordingFramesApi.analyzeRecording(
        recordingId,
        userId: userId,
      );
      // Read the profile back so the result screen can say what changed. A
      // failure here must not cost the user their verdict, so it is swallowed.
      RiskProfile? profile;
      try {
        profile = await RecordingFramesApi.fetchProfile(userId);
      } catch (_) {
        profile = null;
      }
      setState(() {
        _stage = _Stage.done;
        _result = result;
        _profile = profile;
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
      _profile = null;
      _errorMessage = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: _handleTitleTap,
          child: const Text('Conversation Recorder'),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_outline),
            tooltip: 'Your risk pattern',
            onPressed: _openProfile,
          ),
        ],
      ),
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
            if (_frames != null)
              Expanded(child: _buildResults(_frames!, _result))
            // The feed sits under the buttons on the idle screen, so what is
            // going around is visible without going looking for it.
            else if (_stage == _Stage.idle && _deviceUserId != null)
              Expanded(
                child: SingleChildScrollView(
                  child: CampaignFeed(userId: _deviceUserId!),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _openProfile() async {
    final userId = await DeviceUser.id();
    if (!mounted) return;
    await Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => ProfileScreen(userId: userId)));
  }

  void _handleTitleTap() {
    _titleTapCount++;
    if (_titleTapCount < BackendSettingsScreen.unlockTapCount) return;
    _titleTapCount = 0;
    Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => const BackendSettingsScreen()));
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
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
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
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
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

  /// The verdict, what to do about it, and - folded away - why.
  ///
  /// What to do comes first and stays open. Someone deciding whether to hang up
  /// needs the instruction, not the evidence for it; the reasons are
  /// justification they can ask for. The previous version showed eight bullets
  /// mixing both, which is how a warning stops being read.
  ///
  /// No score. The number is deterministic now, but its weights are still
  /// judgement calls, and "55" next to a threshold of 60 implies a precision
  /// that is not there.
  Widget _buildVerdictCard(AnalyzeResult result) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final isScam = result.verdict!.outcome == 'SCAM';
    final advice = result.advice;
    final fired = result.checks
        .where((c) => c.fired && c.detail.isNotEmpty)
        .toList();

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: isScam ? scheme.errorContainer : scheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isScam ? Icons.warning_amber_rounded : Icons.help_outline,
                size: 20,
              ),
              const SizedBox(width: 8),
              Text(
                isScam ? 'LIKELY SCAM' : 'COULD NOT CONFIRM',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
          if (advice != null && advice.headline.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(advice.headline, style: theme.textTheme.bodyLarge),
          ],
          if (advice != null && advice.whatToDo.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text(
              'What to do',
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 6),
            for (final (index, step) in advice.whatToDo.indexed)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(width: 22, child: Text('${index + 1}.')),
                    Expanded(child: Text(step)),
                  ],
                ),
              ),
            if (advice.source.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'Guidance from ScamShield',
                  style: theme.textTheme.labelSmall,
                ),
              ),
          ],
          if (fired.isNotEmpty) ...[
            const SizedBox(height: 8),
            Theme(
              // The default divider draws lines across the coloured card.
              data: theme.copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                title: Text(
                  'Why we flagged this',
                  style: theme.textTheme.titleSmall,
                ),
                tilePadding: EdgeInsets.zero,
                childrenPadding: const EdgeInsets.only(bottom: 8),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final check in fired)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text(
                        '• ${check.detail}',
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildPatternShift(AnalyzeResult result) {
    final profile = _profile;
    final lure = result.signals?.lureType;
    if (profile == null || lure == null || lure == 'none') {
      return const SizedBox.shrink();
    }
    final count = profile.lureCounts[lure] ?? 0;
    if (count < 2) return const SizedBox.shrink();

    final spaced = lure.replaceAll('_', ' ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: InkWell(
        onTap: _openProfile,
        child: Row(
          children: [
            const Icon(Icons.trending_up, size: 18),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '${_ordinal(count)} $spaced scam you have checked. '
                'Your risk pattern updated.',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
            const Icon(Icons.chevron_right, size: 18),
          ],
        ),
      ),
    );
  }

  String _ordinal(int n) {
    if (n % 100 >= 11 && n % 100 <= 13) return '${n}th';
    switch (n % 10) {
      case 1:
        return '${n}st';
      case 2:
        return '${n}nd';
      case 3:
        return '${n}rd';
      default:
        return '${n}th';
    }
  }

  Widget _buildTranscriptBubble(
    TranscriptMessage message, {
    required bool flagged,
  }) {
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
              : (isRight
                    ? colorScheme.primaryContainer
                    : colorScheme.secondaryContainer),
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
    final flagged =
        result?.analysis?.flaggedMessageIndexes.toSet() ?? const <int>{};
    return ListView(
      children: [
        if (result?.verdict != null) _buildVerdictCard(result!),
        if (result != null) _buildPatternShift(result),
        if (result != null && result.transcript.isNotEmpty) ...[
          Text(
            'Reconstructed conversation',
            style: Theme.of(context).textTheme.titleMedium,
          ),
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
