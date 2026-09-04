//import 'file:D:/Workspace/flutter_screen_recording/flutter_screen_recording_platform_interface/lib/flutter_screen_recording_platform_interface.dart';
import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_screen_recording_platform_interface/flutter_screen_recording_platform_interface.dart';

class FlutterScreenRecording {
  static Future<bool> startRecordScreen(String name, {String? titleNotification, String? messageNotification}) async {
    try {
      titleNotification ??= "";
      messageNotification ??= "";

      // Android needs a foreground service while screen capture is running.
      if (!kIsWeb) {
        _maybeStartFGS(titleNotification, messageNotification);
      }
      // The platform interface forwards the request to the native plugin.
      final bool start = await FlutterScreenRecordingPlatform.instance.startRecordScreen(
        name,
        notificationTitle: titleNotification,
        notificationMessage: messageNotification,
      );

      return start;
    } catch (err) {
      print("startRecordScreen err");
      print(err);
    }

    return false;
  }

  static Future<bool> startRecordScreenAndAudio(String name, {String? titleNotification, String? messageNotification}) async {
    try {
      titleNotification ??= "";
      messageNotification ??= "";
      // The same foreground service keeps the process alive while recording audio.
      if (!kIsWeb) {
        _maybeStartFGS(titleNotification, messageNotification);
      }
      // This native method captures both the screen and audio.
      final bool start = await FlutterScreenRecordingPlatform.instance.startRecordScreenAndAudio(
        name,
        notificationTitle: titleNotification,
        notificationMessage: messageNotification,
      );
      return start;
    } catch (err) {
      print("startRecordScreenAndAudio err");
      print(err);
    }
    return false;
  }

  static Future<String> get stopRecordScreen async {
    try {
      // Stop native capture and return the path of the saved video.
      final String path = await FlutterScreenRecordingPlatform.instance.stopRecordScreen;
      if (!kIsWeb && Platform.isAndroid) {
        // The foreground service is only needed while recording.
        FlutterForegroundTask.stopService();
      }
      return path;
    } catch (err) {
      print("stopRecordScreen err");
      print(err);
    }
    return "";
  }

  static void _maybeStartFGS(String titleNotification, String messageNotification) {
    try {
      if (!kIsWeb && Platform.isAndroid) {
        // Configure the ongoing Android notification and service behavior.
        FlutterForegroundTask.init(
          androidNotificationOptions: AndroidNotificationOptions(
            channelId: 'notification_channel_id',
            channelName: titleNotification,
            channelDescription: messageNotification,
            channelImportance: NotificationChannelImportance.LOW,
            priority: NotificationPriority.LOW,
            // iconData: const NotificationIconData(
            //   resType: ResourceType.mipmap,
            //   resPrefix: ResourcePrefix.ic,
            //   name: 'launcher',
            // ),
          ),
          iosNotificationOptions: const IOSNotificationOptions(
            showNotification: true,
            playSound: false,
          ),
          foregroundTaskOptions: ForegroundTaskOptions(
            eventAction: ForegroundTaskEventAction.repeat(5000),
            autoRunOnBoot: true,
            autoRunOnMyPackageReplaced: true,
            allowWakeLock: true,
            allowWifiLock: true,
          ),
        );
      }
    } catch (err) {
      print("_maybeStartFGS err");
      print(err);
    }
  }
}
