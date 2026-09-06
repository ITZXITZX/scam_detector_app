import 'package:flutter_test/flutter_test.dart';
import 'package:scam_detector_app/backend_config.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await BackendConfig.initialize();
  });

  test('uses the emulator address by default and after clearing', () async {
    expect(BackendConfig.baseUrl, 'http://10.0.2.2:8000');
    await BackendConfig.save('192.168.1.14');
    await BackendConfig.save('');
    expect(BackendConfig.baseUrl, 'http://10.0.2.2:8000');
  });

  test('persists IPv4 and formats IPv6 URLs', () async {
    await BackendConfig.save('192.168.1.14');
    await BackendConfig.initialize();
    expect(BackendConfig.baseUrl, 'http://192.168.1.14:8000');

    await BackendConfig.save('2001:db8::1');
    expect(BackendConfig.baseUrl, 'http://[2001:db8::1]:8000');
  });

  test('rejects invalid addresses', () {
    expect(BackendConfig.validate('backend.local'), isNotNull);
    expect(BackendConfig.validate('192.168.1.999'), isNotNull);
    expect(BackendConfig.validate(''), isNull);
  });
}
