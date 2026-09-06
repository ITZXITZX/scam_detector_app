import 'package:flutter/material.dart';

import 'recording_frames_api.dart';

/// What this device keeps being targeted with.
///
/// Deliberately describes the scammers' behaviour rather than the user's
/// weakness: "what you've been targeted with", not "what you are vulnerable
/// to". Someone who has just been shown a scam aimed at them does not need to
/// be told they are the sort of person who falls for it.
class ProfileScreen extends StatefulWidget {
  final String userId;

  const ProfileScreen({super.key, required this.userId});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late Future<RiskProfile> _profile;

  @override
  void initState() {
    super.initState();
    _profile = RecordingFramesApi.fetchProfile(widget.userId);
  }

  /// Replace the profile with fabricated data, or wipe it.
  ///
  /// Both re-point the future rather than mutating state, so the screen shows
  /// its normal loading and error paths instead of a special case.
  void _runAction(String action) {
    setState(() {
      _profile = action == 'sample'
          ? RecordingFramesApi.loadSampleProfile(widget.userId)
          : RecordingFramesApi.clearProfile(widget.userId);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your risk pattern'),
        actions: [
          // Development affordance, like "Use sample recording" on the home
          // screen. TODO: hide behind kDebugMode before shipping a release.
          PopupMenuButton<String>(
            onSelected: _runAction,
            itemBuilder: (context) => const [
              PopupMenuItem(value: 'sample', child: Text('Load sample data')),
              PopupMenuItem(value: 'clear', child: Text('Clear profile')),
            ],
          ),
        ],
      ),
      body: FutureBuilder<RiskProfile>(
        future: _profile,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _message('Could not load your pattern.\n${snapshot.error}');
          }
          final profile = snapshot.data!;
          if (profile.isEmpty) {
            return _message(
              'Nothing checked yet.\n\n'
              'Your pattern appears after your first check.',
            );
          }
          return _body(profile);
        },
      ),
    );
  }

  Widget _message(String text) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(text, textAlign: TextAlign.center),
        ),
      );

  Widget _body(RiskProfile profile) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          '${profile.encounterCount} '
          '${profile.encounterCount == 1 ? "conversation" : "conversations"} checked',
          style: theme.textTheme.titleMedium,
        ),
        const SizedBox(height: 24),

        if (profile.vulnerability.isNotEmpty) ...[
          Text("What you've been targeted with", style: theme.textTheme.titleSmall),
          const SizedBox(height: 8),
          ..._bars(profile.vulnerability),
          const SizedBox(height: 24),
        ],

        if (profile.tacticSensitivity.isNotEmpty) ...[
          Text('Tactics used on you', style: theme.textTheme.titleSmall),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              for (final tactic in _byCount(profile.tacticSensitivity))
                Chip(
                  label: Text(
                    '${_label(tactic)} · ${profile.tacticSensitivity[tactic]}',
                  ),
                  visualDensity: VisualDensity.compact,
                ),
            ],
          ),
          const SizedBox(height: 24),
        ],

        if (profile.usualChannel != null) ...[
          Text('Usually reaches you on', style: theme.textTheme.titleSmall),
          const SizedBox(height: 4),
          Text(_label(profile.usualChannel!)),
          const SizedBox(height: 24),
        ],

        const Divider(),
        const SizedBox(height: 8),
        Text(
          'Sentry never stores your messages — only the pattern.',
          style: theme.textTheme.bodySmall,
        ),
      ],
    );
  }

  /// One bar per scam type, with the count beside it.
  ///
  /// Bars are scaled to the largest count so the shape is readable at a glance,
  /// and the number is shown because a count is a fact the person can check:
  /// "3 times" means three conversations they remember.
  List<Widget> _bars(Map<String, int> counts) {
    final ordered = _byCount(counts);
    final highest = counts.values.reduce((a, b) => a > b ? a : b);
    return [
      for (final key in ordered)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Row(
            children: [
              SizedBox(width: 110, child: Text(_label(key))),
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: highest == 0 ? 0 : counts[key]! / highest,
                    minHeight: 10,
                  ),
                ),
              ),
              SizedBox(
                width: 64,
                child: Text(
                  '  ${counts[key]}${counts[key] == 1 ? " time" : " times"}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            ],
          ),
        ),
    ];
  }

  List<String> _byCount(Map<String, int> counts) {
    final keys = counts.keys.toList();
    keys.sort((a, b) => counts[b]!.compareTo(counts[a]!));
    return keys;
  }

  /// "tech_support" -> "Tech support".
  String _label(String raw) {
    final spaced = raw.replaceAll('_', ' ');
    return spaced[0].toUpperCase() + spaced.substring(1);
  }
}
