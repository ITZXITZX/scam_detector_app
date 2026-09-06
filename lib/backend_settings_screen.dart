import 'package:flutter/material.dart';

import 'backend_config.dart';

class BackendSettingsScreen extends StatefulWidget {
  const BackendSettingsScreen({super.key});

  static const unlockTapCount = 7;

  @override
  State<BackendSettingsScreen> createState() => _BackendSettingsScreenState();
}

class _BackendSettingsScreenState extends State<BackendSettingsScreen> {
  late final TextEditingController _controller;
  String? _error;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(
      text: BackendConfig.host == BackendConfig.defaultHost
          ? ''
          : BackendConfig.host,
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _validate(String value) =>
      setState(() => _error = BackendConfig.validate(value));

  Future<void> _save() async {
    await BackendConfig.save(_controller.text);
    if (!mounted) return;
    setState(() {
      _controller.text = BackendConfig.host == BackendConfig.defaultHost
          ? ''
          : BackendConfig.host;
      _error = null;
    });
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('Backend address saved')));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Backend settings')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Current backend',
              style: Theme.of(context).textTheme.labelLarge,
            ),
            const SizedBox(height: 4),
            SelectableText(BackendConfig.baseUrl),
            const SizedBox(height: 24),
            TextField(
              controller: _controller,
              autocorrect: false,
              keyboardType: TextInputType.url,
              onChanged: _validate,
              decoration: InputDecoration(
                border: const OutlineInputBorder(),
                labelText: 'Backend IP address',
                hintText: BackendConfig.defaultHost,
                helperText: 'Leave empty to use the Android emulator address.',
                errorText: _error,
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _error == null ? _save : null,
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
  }
}
