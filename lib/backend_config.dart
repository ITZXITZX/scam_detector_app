import 'dart:io';

import 'package:shared_preferences/shared_preferences.dart';

class BackendConfig {
  static const defaultHost = '10.0.2.2';
  static const port = 8000;
  static const preferenceKey = 'backend.host';

  static String? _savedHost;

  static String get host => _savedHost ?? defaultHost;

  static String get baseUrl {
    final urlHost = host.contains(':') ? '[$host]' : host;
    return 'http://$urlHost:$port';
  }

  static String? validate(String value) {
    final input = value.trim();
    if (input.isEmpty || InternetAddress.tryParse(input) != null) return null;
    return 'Enter a valid IPv4 or IPv6 address';
  }

  static Future<void> initialize() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(preferenceKey)?.trim();
    _savedHost = stored == null || stored.isEmpty ? null : stored;
  }

  static Future<void> save(String value) async {
    final input = value.trim();
    if (validate(input) != null) {
      throw const FormatException('Invalid IP address');
    }

    final prefs = await SharedPreferences.getInstance();
    if (input.isEmpty) {
      await prefs.remove(preferenceKey);
      _savedHost = null;
    } else {
      final normalized = InternetAddress.tryParse(input)!.address;
      await prefs.setString(preferenceKey, normalized);
      _savedHost = normalized;
    }
  }
}
