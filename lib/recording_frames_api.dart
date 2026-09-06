import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'backend_config.dart';

/// One extracted preview frame returned by the backend.
class FramePreview {
  final String id;
  final double timestampSeconds;
  final String url;

  FramePreview({
    required this.id,
    required this.timestampSeconds,
    required this.url,
  });

  factory FramePreview.fromJson(Map<String, dynamic> json) => FramePreview(
        id: json['id'] as String,
        timestampSeconds: (json['timestampSeconds'] as num).toDouble(),
        url: json['url'] as String,
      );
}

/// One reconstructed message in the merged conversation transcript.
class TranscriptMessage {
  final String text;
  final String senderHint; // "left", "right", or "unknown"
  final double confidence;
  final double firstSeenSeconds;
  final double lastSeenSeconds;
  final List<String> evidenceFrameIds;

  TranscriptMessage({
    required this.text,
    required this.senderHint,
    required this.confidence,
    required this.firstSeenSeconds,
    required this.lastSeenSeconds,
    required this.evidenceFrameIds,
  });

  factory TranscriptMessage.fromJson(Map<String, dynamic> json) => TranscriptMessage(
        text: json['text'] as String,
        senderHint: json['senderHint'] as String,
        confidence: (json['confidence'] as num).toDouble(),
        firstSeenSeconds: (json['firstSeenSeconds'] as num).toDouble(),
        lastSeenSeconds: (json['lastSeenSeconds'] as num).toDouble(),
        evidenceFrameIds: (json['evidenceFrameIds'] as List).cast<String>(),
      );
}

/// AI scam-risk verdict over the reconstructed transcript.
class ScamAnalysis {
  final String riskLevel; // "low", "medium", "high", or "unavailable"
  final int riskScore;
  final String summary;
  final List<int> flaggedMessageIndexes;
  final List<String> warnings;

  ScamAnalysis({
    required this.riskLevel,
    required this.riskScore,
    required this.summary,
    required this.flaggedMessageIndexes,
    required this.warnings,
  });

  factory ScamAnalysis.fromJson(Map<String, dynamic> json) => ScamAnalysis(
        riskLevel: json['riskLevel'] as String,
        riskScore: json['riskScore'] as int,
        summary: json['summary'] as String,
        flaggedMessageIndexes: (json['flaggedMessageIndexes'] as List).cast<int>(),
        warnings: (json['warnings'] as List).cast<String>(),
      );
}

/// Result of turning an upload into stored frames. No AI has run yet.
class FramesResult {
  final String recordingId;
  final int frameCount;
  final int duplicateFramesDropped;
  final List<FramePreview> frames;

  FramesResult({
    required this.recordingId,
    required this.frameCount,
    required this.duplicateFramesDropped,
    required this.frames,
  });

  factory FramesResult.fromJson(Map<String, dynamic> json) => FramesResult(
        recordingId: json['recordingId'] as String,
        frameCount: json['frameCount'] as int,
        duplicateFramesDropped: json['duplicateFramesDropped'] as int? ?? 0,
        frames: (json['frames'] as List)
            .map((e) => FramePreview.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// The taxonomy labels the deterministic checks ran against.
///
/// Exposed so a verdict can be reproduced from the response alone, rather than
/// taken on trust.
class SignalSummary {
  final String lureType;
  final List<String> pressureTactics;
  final List<String> requestedActions;
  final String claimedIdentity;
  final String channel;
  final String engagementDepth;
  final List<String> urls;

  SignalSummary({
    required this.lureType,
    required this.pressureTactics,
    required this.requestedActions,
    required this.claimedIdentity,
    required this.channel,
    required this.engagementDepth,
    required this.urls,
  });

  factory SignalSummary.fromJson(Map<String, dynamic> json) => SignalSummary(
        lureType: json['lureType'] as String? ?? 'none',
        pressureTactics:
            (json['pressureTactics'] as List? ?? const []).cast<String>(),
        requestedActions:
            (json['requestedActions'] as List? ?? const []).cast<String>(),
        claimedIdentity: json['claimedIdentity'] as String? ?? 'none',
        channel: json['channel'] as String? ?? 'unknown',
        engagementDepth: json['engagementDepth'] as String? ?? 'no_reply',
        urls: (json['urls'] as List? ?? const []).cast<String>(),
      );
}

/// One deterministic check and whether it fired.
class CheckOutcome {
  final String id;
  final bool fired;
  final String detail;

  CheckOutcome({required this.id, required this.fired, required this.detail});

  factory CheckOutcome.fromJson(Map<String, dynamic> json) => CheckOutcome(
        id: json['id'] as String,
        fired: json['fired'] as bool,
        detail: json['detail'] as String? ?? '',
      );
}

/// What the user should do, and where it came from.
///
/// `whatToDo` is verbatim official wording: the model chooses which published
/// steps apply, the backend renders their text. That is why the helpline does
/// not change between runs.
class Advice {
  final String headline;
  final List<String> whatToDo;
  final String source;

  Advice({required this.headline, required this.whatToDo, required this.source});

  factory Advice.fromJson(Map<String, dynamic> json) => Advice(
        headline: json['headline'] as String? ?? '',
        whatToDo: (json['whatToDo'] as List? ?? const []).cast<String>(),
        source: json['source'] as String? ?? '',
      );
}

/// The outcome the checks decided. Never "safe": only SCAM or COULDNT_CONFIRM.
class VerdictSummary {
  final String outcome;
  final int score;
  final List<String> hardTriggered;

  VerdictSummary({
    required this.outcome,
    required this.score,
    required this.hardTriggered,
  });

  factory VerdictSummary.fromJson(Map<String, dynamic> json) => VerdictSummary(
        outcome: json['outcome'] as String,
        score: json['score'] as int,
        hardTriggered: (json['hardTriggered'] as List? ?? const []).cast<String>(),
      );
}

/// One scam wave currently circulating.
///
/// Everyone sees the same cards in the same order. [matchedToYou] marks the
/// ones this device would also be notified about; [matchReason] stays off the
/// card and appears only after a tap, so a glance over someone's shoulder does
/// not read their history back to them.
class ScamCampaign {
  final String id;
  final String title;
  final String body;
  final String? publishedOn;
  final String source;
  final String severity;
  final bool matchedToYou;
  final String matchReason;

  ScamCampaign({
    required this.id,
    required this.title,
    required this.body,
    required this.publishedOn,
    required this.source,
    required this.severity,
    required this.matchedToYou,
    required this.matchReason,
  });

  factory ScamCampaign.fromJson(Map<String, dynamic> json) => ScamCampaign(
        id: json['id'] as String,
        title: json['title'] as String,
        body: json['body'] as String,
        publishedOn: json['publishedOn'] as String?,
        source: json['source'] as String? ?? '',
        severity: json['severity'] as String? ?? 'normal',
        matchedToYou: json['matchedToYou'] as bool? ?? false,
        matchReason: json['matchReason'] as String? ?? '',
      );
}

/// What a user has turned out to be vulnerable to.
///
/// Scores are counts: how many times this person has been approached with each
/// kind of scam.
class RiskProfile {
  final String userId;
  final int encounterCount;
  final Map<String, int> vulnerability;
  final Map<String, int> tacticSensitivity;
  final Map<String, int> channels;
  final Map<String, int> lureCounts;
  final String? topLure;
  final String? usualChannel;

  RiskProfile({
    required this.userId,
    required this.encounterCount,
    required this.vulnerability,
    required this.tacticSensitivity,
    required this.channels,
    required this.lureCounts,
    required this.topLure,
    required this.usualChannel,
  });

  factory RiskProfile.fromJson(Map<String, dynamic> json) => RiskProfile(
        userId: json['userId'] as String,
        encounterCount: json['encounterCount'] as int,
        vulnerability: (json['vulnerability'] as Map)
            .map((k, v) => MapEntry(k as String, (v as num).toInt())),
        tacticSensitivity: (json['tacticSensitivity'] as Map)
            .map((k, v) => MapEntry(k as String, (v as num).toInt())),
        channels: (json['channels'] as Map)
            .map((k, v) => MapEntry(k as String, v as int)),
        lureCounts: (json['lureCounts'] as Map? ?? const {})
            .map((k, v) => MapEntry(k as String, v as int)),
        topLure: json['topLure'] as String?,
        usualChannel: json['usualChannel'] as String?,
      );

  bool get isEmpty => encounterCount == 0;
}

/// Result of running Claude over an existing recording's frames.
class AnalyzeResult {
  final String recordingId;
  final List<TranscriptMessage> transcript;
  final SignalSummary? signals;
  final List<CheckOutcome> checks;
  final VerdictSummary? verdict;
  final Advice? advice;
  final ScamAnalysis? analysis;

  AnalyzeResult({
    required this.recordingId,
    required this.transcript,
    required this.signals,
    required this.checks,
    required this.verdict,
    required this.advice,
    required this.analysis,
  });

  factory AnalyzeResult.fromJson(Map<String, dynamic> json) => AnalyzeResult(
        recordingId: json['recordingId'] as String,
        transcript: (json['transcript'] as List? ?? const [])
            .map((e) => TranscriptMessage.fromJson(e as Map<String, dynamic>))
            .toList(),
        signals: json['signals'] == null
            ? null
            : SignalSummary.fromJson(json['signals'] as Map<String, dynamic>),
        checks: (json['checks'] as List? ?? const [])
            .map((e) => CheckOutcome.fromJson(e as Map<String, dynamic>))
            .toList(),
        verdict: json['verdict'] == null
            ? null
            : VerdictSummary.fromJson(json['verdict'] as Map<String, dynamic>),
        advice: json['advice'] == null
            ? null
            : Advice.fromJson(json['advice'] as Map<String, dynamic>),
        analysis: json['analysis'] == null
            ? null
            : ScamAnalysis.fromJson(json['analysis'] as Map<String, dynamic>),
      );
}

/// A single recognized line of text with its bounding box, from `/recordings/{id}/ocr`.
class OCRText {
  final String text;
  final double left;
  final double top;
  final double right;
  final double bottom;
  final double confidence;

  OCRText({
    required this.text,
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
    required this.confidence,
  });

  factory OCRText.fromJson(Map<String, dynamic> json) => OCRText(
        text: json['text'] as String,
        left: (json['left'] as num).toDouble(),
        top: (json['top'] as num).toDouble(),
        right: (json['right'] as num).toDouble(),
        bottom: (json['bottom'] as num).toDouble(),
        confidence: (json['confidence'] as num).toDouble(),
      );
}

/// OCR output for a single frame.
class FrameOCRResult {
  final String frameId;
  final List<OCRText> texts;

  FrameOCRResult({required this.frameId, required this.texts});

  factory FrameOCRResult.fromJson(Map<String, dynamic> json) => FrameOCRResult(
        frameId: json['frameId'] as String,
        texts: (json['texts'] as List)
            .map((e) => OCRText.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// Result of a `/recordings/{id}/ocr` call.
class OCRResult {
  final String recordingId;
  final List<FrameOCRResult> frames;

  OCRResult({required this.recordingId, required this.frames});

  factory OCRResult.fromJson(Map<String, dynamic> json) => OCRResult(
        recordingId: json['recordingId'] as String,
        frames: (json['frames'] as List)
            .map((e) => FrameOCRResult.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class RecordingFramesApi {
  static String get baseUrl => BackendConfig.baseUrl;

  static String resolveFrameUrl(String relativeUrl) => '$baseUrl$relativeUrl';

  /// Step 1a: turn a screen recording into deduplicated frames. No AI runs.
  static Future<FramesResult> createRecordingFromVideo(File videoFile) async {
    final uri = Uri.parse('$baseUrl/recordings/frames');
    final request = http.MultipartRequest('POST', uri)
      ..files.add(await http.MultipartFile.fromPath('file', videoFile.path));
    return FramesResult.fromJson(await _send(request));
  }

  /// Step 1b: same, but from images the user picked instead of a recording.
  static Future<FramesResult> createRecordingFromImages(List<File> images) async {
    final uri = Uri.parse('$baseUrl/recordings/images');
    final request = http.MultipartRequest('POST', uri);
    for (final image in images) {
      request.files.add(await http.MultipartFile.fromPath('files', image.path));
    }
    return FramesResult.fromJson(await _send(request));
  }

  /// Step 2: read the conversation out of stored frames and judge scam risk.
  ///
  /// Passing [userId] records the result against that device's profile. Every
  /// analysis is recorded, not only the scams.
  static Future<AnalyzeResult> analyzeRecording(
    String recordingId, {
    String? userId,
  }) async {
    final query = (userId == null || userId.isEmpty) ? '' : '?userId=$userId';
    final uri = Uri.parse('$baseUrl/recordings/$recordingId/analyze$query');
    final response = await http.post(uri);

    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }

    return AnalyzeResult.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// What this device has been targeted with so far.
  static Future<RiskProfile> fetchProfile(String userId) async {
    final response = await http.get(Uri.parse('$baseUrl/users/$userId/profile'));
    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }
    return RiskProfile.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// Scam waves circulating now, newest first.
  ///
  /// Passing [userId] marks which ones this device would be warned about. The
  /// server computes that for the response and keeps no record of it.
  static Future<List<ScamCampaign>> fetchCampaigns({String? userId}) async {
    final query = (userId == null || userId.isEmpty) ? '' : '?userId=$userId';
    final response = await http.get(Uri.parse('$baseUrl/campaigns$query'));
    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }
    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    return (decoded['campaigns'] as List? ?? const [])
        .map((e) => ScamCampaign.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Development only: fill this profile with fabricated encounters.
  ///
  /// The screen is meant to show a vulnerability fading over months and a
  /// habitual channel, which real testing cannot produce - analyses are all
  /// seconds old and the channel is usually "unknown".
  static Future<RiskProfile> loadSampleProfile(String userId) async {
    final response =
        await http.post(Uri.parse('$baseUrl/users/$userId/profile/demo'));
    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }
    return RiskProfile.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// Forget everything recorded for this device.
  static Future<RiskProfile> clearProfile(String userId) async {
    final response = await http.delete(Uri.parse('$baseUrl/users/$userId/profile'));
    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }
    return RiskProfile.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  static Future<Map<String, dynamic>> _send(http.MultipartRequest request) async {
    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  static Future<OCRResult> runOcr(String recordingId) async {
    final uri = Uri.parse('$baseUrl/recordings/$recordingId/ocr');
    final response = await http.post(uri);

    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }

    return OCRResult.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }
}
