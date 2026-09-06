import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

/// Identifies this device to the backend so encounters accumulate into one
/// profile.
///
/// Generated locally and never leaves the device except as an opaque id: there
/// is no account, no email, and nothing here ties the profile to a person. That
/// is enough to learn what this phone keeps being targeted with, and not enough
/// for the family linking in Workflow D, which will need a real identity.
class DeviceUser {
  static const _key = 'sentry.deviceUserId';
  static String? _cached;

  /// The id for this device, creating one on first use.
  static Future<String> id() async {
    if (_cached != null) return _cached!;
    final prefs = await SharedPreferences.getInstance();
    var id = prefs.getString(_key);
    if (id == null || id.isEmpty) {
      id = _generate();
      await prefs.setString(_key, id);
    }
    _cached = id;
    return id;
  }

  /// A random 128-bit id in UUID-ish form.
  ///
  /// Random.secure() rather than the `uuid` package: this needs to be
  /// unguessable and unique, not RFC-4122 conformant, and it is not worth a
  /// dependency.
  static String _generate() {
    final random = Random.secure();
    String hex(int bytes) => List.generate(
          bytes,
          (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'),
        ).join();
    return '${hex(4)}-${hex(2)}-${hex(2)}-${hex(2)}-${hex(6)}';
  }
}
