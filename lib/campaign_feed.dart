import 'package:flutter/material.dart';

import 'recording_frames_api.dart';

/// "Scams going around" — the same list for everyone, with a dot on the ones
/// that match this device.
///
/// Everyone sees every card. Ordering is newest first and identical for all
/// users: a feed that silently reorders itself per person is harder to trust
/// than a dot, and harder to explain when someone asks why they saw something.
class CampaignFeed extends StatefulWidget {
  final String userId;

  const CampaignFeed({super.key, required this.userId});

  @override
  State<CampaignFeed> createState() => _CampaignFeedState();
}

class _CampaignFeedState extends State<CampaignFeed> {
  late Future<List<ScamCampaign>> _campaigns;

  @override
  void initState() {
    super.initState();
    _campaigns = RecordingFramesApi.fetchCampaigns(userId: widget.userId);
  }

  void _refresh() {
    setState(() {
      _campaigns = RecordingFramesApi.fetchCampaigns(userId: widget.userId);
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return FutureBuilder<List<ScamCampaign>>(
      future: _campaigns,
      builder: (context, snapshot) {
        // A feed that cannot load is not worth an error banner above the thing
        // the user actually came to do.
        if (snapshot.connectionState != ConnectionState.done ||
            snapshot.hasError ||
            (snapshot.data?.isEmpty ?? true)) {
          return const SizedBox.shrink();
        }
        final campaigns = snapshot.data!;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text('Scams going around',
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.bold)),
                ),
                IconButton(
                  icon: const Icon(Icons.refresh, size: 18),
                  tooltip: 'Refresh',
                  visualDensity: VisualDensity.compact,
                  onPressed: _refresh,
                ),
              ],
            ),
            const SizedBox(height: 4),
            for (final campaign in campaigns) _card(campaign),
          ],
        );
      },
    );
  }

  Widget _card(ScamCampaign campaign) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: () => _openDetail(campaign),
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // The dot is the whole personalisation. The reason behind it
              // stays out of view until the card is opened.
              Padding(
                padding: const EdgeInsets.only(top: 5, right: 10),
                child: Icon(
                  campaign.matchedToYou ? Icons.circle : Icons.circle_outlined,
                  size: 9,
                  color: campaign.matchedToYou
                      ? theme.colorScheme.error
                      : theme.colorScheme.outlineVariant,
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(campaign.title,
                        style: theme.textTheme.bodyLarge
                            ?.copyWith(fontWeight: FontWeight.w600)),
                    const SizedBox(height: 3),
                    Text(
                      [
                        if (campaign.publishedOn != null) campaign.publishedOn!,
                        'Singapore Police Force',
                      ].join(' · '),
                      style: theme.textTheme.labelSmall,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, size: 18),
            ],
          ),
        ),
      ),
    );
  }

  void _openDetail(ScamCampaign campaign) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) {
        final theme = Theme.of(context);
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(campaign.title, style: theme.textTheme.titleLarge),
                const SizedBox(height: 4),
                Text(
                  [
                    if (campaign.publishedOn != null) campaign.publishedOn!,
                    'Singapore Police Force advisory',
                  ].join(' · '),
                  style: theme.textTheme.labelMedium,
                ),
                const SizedBox(height: 14),
                Text(campaign.body, style: theme.textTheme.bodyLarge),
                if (campaign.matchedToYou && campaign.matchReason.isNotEmpty) ...[
                  const SizedBox(height: 18),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Why you are seeing this',
                            style: theme.textTheme.labelLarge),
                        const SizedBox(height: 4),
                        Text(campaign.matchReason,
                            style: theme.textTheme.bodyMedium),
                      ],
                    ),
                  ),
                ],
                if (campaign.source.isNotEmpty) ...[
                  const SizedBox(height: 18),
                  Text('Read the original advisory at',
                      style: theme.textTheme.labelMedium),
                  const SizedBox(height: 2),
                  // Shown rather than opened. The app tells people not to follow
                  // links they did not go looking for; a police.gov.sg address
                  // they can type or check themselves is the honest version.
                  SelectableText(campaign.source,
                      style: theme.textTheme.bodySmall),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}
