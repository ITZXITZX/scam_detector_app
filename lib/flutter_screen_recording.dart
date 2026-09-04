import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_screen_recording_platform_interface/flutter_screen_recording_platform_interface.dart';

class FlutterScreenRecording {
  /// Start video-only screen recording
  static Future<bool> startRecordScreen(
      String name, {
        String? titleNotification,
        String? messageNotification,
      }) async {
    try {
      final title = (titleNotification == null || titleNotification.isEmpty)
          ? "Screen Recording"
          : titleNotification;
      final message = (messageNotification == null || messageNotification.isEmpty)
          ? "Recording screen in progress..."
          : messageNotification;

      // Android requires a foreground service while the app records the screen.
      // Web and iOS use different platform implementations, so skip this step there.
      if (!kIsWeb && Platform.isAndroid) {
        final serviceStarted = await _startForegroundService(title, message);
        if (!serviceStarted) {
          print("Failed to start Foreground Service on Android.");
          return false;
        }
      }

      // The platform interface forwards this request to the native recording plugin.
      final bool start = await FlutterScreenRecordingPlatform.instance.startRecordScreen(
        name,
        notificationTitle: title,
        notificationMessage: message,
      );

      // Do not leave a foreground service running if the capture request failed.
      if (!start && !kIsWeb && Platform.isAndroid) {
        await FlutterForegroundTask.stopService();
      }

      return start;
    } catch (err) {
      print("startRecordScreen err: $err");
      // Audio recording uses the same Android service; the native plugin handles
      // the actual screen and audio capture.
      if (!kIsWeb && Platform.isAndroid) {
        await FlutterForegroundTask.stopService();
      }
    }

    return false;
  }

  /// Start video + audio screen recording
  static Future<bool> startRecordScreenAndAudio(
      String name, {
        String? titleNotification,
        String? messageNotification,
      }) async {
    try {
      final title = (titleNotification == null || titleNotification.isEmpty)
          ? "Screen & Audio Recording"
          : titleNotification;
      final message = (messageNotification == null || messageNotification.isEmpty)
          ? "Recording screen and audio in progress..."
          : messageNotification;

      if (!kIsWeb && Platform.isAndroid) {
        final serviceStarted = await _startForegroundService(title, message);
        if (!serviceStarted) {
          print("Failed to start Foreground Service on Android.");
          return false;
        }
      }

      // Ask the native plugin to capture both the screen and audio.
      final bool start = await FlutterScreenRecordingPlatform.instance.startRecordScreenAndAudio(
        name,
        notificationTitle: title,
        notificationMessage: message,
      );

      if (!start && !kIsWeb && Platform.isAndroid) {
        await FlutterForegroundTask.stopService();
      }

      return start;
    } catch (err) {
      print("startRecordScreenAndAudio err: $err");
      if (!kIsWeb && Platform.isAndroid) {
        await FlutterForegroundTask.stopService();
      }
    }

    return false;
  }

  /// Stop recording and return the saved output path
  static Future<String> get stopRecordScreen async {
    try {
      // Stop the native capture and get the path of the saved video.
      final String path = await FlutterScreenRecordingPlatform.instance.stopRecordScreen;

      // The service is only needed during recording, so stop it as well.
      if (!kIsWeb && Platform.isAndroid) {
        await FlutterForegroundTask.stopService();
      }

      return path;
    } catch (err) {
      print("stopRecordScreen err: $err");
      if (!kIsWeb && Platform.isAndroid) {
        await FlutterForegroundTask.stopService();
      }
    }
    return "";
  }

  /// Helper to initialize and actually START the foreground service on Android
  static Future<bool> _startForegroundService(String title, String message) async {
    try {
      // Android requires an ongoing notification for foreground services.
      // init() configures that notification and how the service should run.
      FlutterForegroundTask.init(
        androidNotificationOptions: AndroidNotificationOptions(
          channelId: 'screen_recording_channel',
          channelName: title,
          channelDescription: message,
          channelImportance: NotificationChannelImportance.LOW,
          priority: NotificationPriority.LOW,
        ),
        iosNotificationOptions: const IOSNotificationOptions(
          showNotification: false,
        ),
        foregroundTaskOptions: ForegroundTaskOptions(
          eventAction: ForegroundTaskEventAction.repeat(5000),
          autoRunOnBoot: false,
          allowWakeLock: true,
          allowWifiLock: false,
        ),
      );

      // Android 13 and newer require notification permission before showing it.
      final NotificationPermission notificationPermission =
      await FlutterForegroundTask.checkNotificationPermission();
      if (notificationPermission != NotificationPermission.granted) {
        await FlutterForegroundTask.requestNotificationPermission();
      }

      // Start the service before asking the native recorder to begin capturing.
      final ServiceRequestResult result = await FlutterForegroundTask.startService(
        serviceId: 256,
        notificationTitle: title,
        notificationText: message,
      );

      return result is ServiceRequestSuccess;
    } catch (err) {
      print("_startForegroundService err: $err");
      return false;
    }
  }
}