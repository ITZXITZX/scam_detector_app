import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// One line of text recognized in a frame, with its bounding box.
class OcrText {
  final String text;
  final int left;
  final int top;
  final int right;
  final int bottom;
  final double confidence;

  OcrText({
    required this.text,
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
    required this.confidence,
  });

  factory OcrText.fromJson(Map<String, dynamic> json) => OcrText(
        text: json['text'] as String,
        left: json['left'] as int,
        top: json['top'] as int,
        right: json['right'] as int,
        bottom: json['bottom'] as int,
        confidence: (json['confidence'] as num).toDouble(),
      );
}

/// One extracted preview frame returned by the backend.
class FramePreview {
  final String id;
  final double timestampSeconds;
  final String url;
  final List<OcrText> texts;

  FramePreview({
    required this.id,
    required this.timestampSeconds,
    required this.url,
    required this.texts,
  });

  factory FramePreview.fromJson(Map<String, dynamic> json) => FramePreview(
        id: json['id'] as String,
        timestampSeconds: (json['timestampSeconds'] as num).toDouble(),
        url: json['url'] as String,
        texts: (json['texts'] as List? ?? const [])
            .map((e) => OcrText.fromJson(e as Map<String, dynamic>))
            .toList(),
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

/// Result of a `/recordings/analyze` call.
class AnalyzeResult {
  final String recordingId;
  final int frameCount;
  final int duplicateFramesDropped;
  final List<FramePreview> frames;
  final List<TranscriptMessage> transcript;

  AnalyzeResult({
    required this.recordingId,
    required this.frameCount,
    required this.duplicateFramesDropped,
    required this.frames,
    required this.transcript,
  });

  factory AnalyzeResult.fromJson(Map<String, dynamic> json) => AnalyzeResult(
        recordingId: json['recordingId'] as String,
        frameCount: json['frameCount'] as int,
        duplicateFramesDropped: json['duplicateFramesDropped'] as int? ?? 0,
        frames: (json['frames'] as List)
            .map((e) => FramePreview.fromJson(e as Map<String, dynamic>))
            .toList(),
        transcript: (json['transcript'] as List? ?? const [])
            .map((e) => TranscriptMessage.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class RecordingFramesApi {
  /// The Android emulator maps 10.0.2.2 to the host machine's localhost.
  /// For a real device, replace this with your machine's LAN IP.
  static String get baseUrl {
    if (!kIsWeb && Platform.isAndroid) return 'http://10.0.2.2:8000';
    return 'http://localhost:8000';
  }

  static String resolveFrameUrl(String relativeUrl) => '$baseUrl$relativeUrl';

  static Future<AnalyzeResult> analyzeRecording(File videoFile) async {
    final uri = Uri.parse('$baseUrl/recordings/analyze');
    final request = http.MultipartRequest('POST', uri)
      ..files.add(await http.MultipartFile.fromPath('file', videoFile.path));

    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }

    return AnalyzeResult.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }
}
