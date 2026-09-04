import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// One extracted preview frame returned by the backend.
class FramePreview {
  final String id;
  final double timestampSeconds;
  final String url;

  FramePreview({required this.id, required this.timestampSeconds, required this.url});

  factory FramePreview.fromJson(Map<String, dynamic> json) => FramePreview(
        id: json['id'] as String,
        timestampSeconds: (json['timestampSeconds'] as num).toDouble(),
        url: json['url'] as String,
      );
}

/// Result of a `/recordings/analyze` call.
class AnalyzeResult {
  final String recordingId;
  final int frameCount;
  final List<FramePreview> frames;

  AnalyzeResult({required this.recordingId, required this.frameCount, required this.frames});

  factory AnalyzeResult.fromJson(Map<String, dynamic> json) => AnalyzeResult(
        recordingId: json['recordingId'] as String,
        frameCount: json['frameCount'] as int,
        frames: (json['frames'] as List)
            .map((e) => FramePreview.fromJson(e as Map<String, dynamic>))
            .toList(),
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

  static Future<OCRResult> runOcr(String recordingId) async {
    final uri = Uri.parse('$baseUrl/recordings/$recordingId/ocr');
    final response = await http.post(uri);

    if (response.statusCode != 200) {
      throw Exception('Backend returned ${response.statusCode}: ${response.body}');
    }

    return OCRResult.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }
}
