import 'package:flutter/material.dart';

import '../models/app_usage.dart';
import '../usage_service.dart';

/// Tela principal do MVP: mostra o tempo de uso por app referente a hoje.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final UsageService _usage = UsageService();

  bool _loading = true;
  bool _hasPermission = false;
  List<AppUsage> _apps = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final granted = await _usage.hasUsageAccess();
    final apps = granted ? await _usage.getUsageToday() : const <AppUsage>[];
    if (!mounted) return;
    setState(() {
      _hasPermission = granted;
      _apps = apps;
      _loading = false;
    });
  }

  Future<void> _requestPermission() async {
    await _usage.openUsageAccessSettings();
    // Ao voltar das Configurações o usuário pode ter concedido a permissão;
    // recarrega quando ele tocar em "Atualizar".
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Tempo de tela — hoje'),
        actions: [
          IconButton(
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh),
            tooltip: 'Atualizar',
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (!_hasPermission) {
      return _PermissionPrompt(onGrant: _requestPermission, onRetry: _load);
    }
    if (_apps.isEmpty) {
      return ListView(
        children: const [
          SizedBox(height: 120),
          Center(child: Text('Nenhum uso registrado hoje ainda.')),
        ],
      );
    }

    final total = _apps.fold<Duration>(
      Duration.zero,
      (sum, a) => sum + a.totalTime,
    );

    return ListView.separated(
      itemCount: _apps.length + 1,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, index) {
        if (index == 0) return _TotalHeader(total: total);
        final app = _apps[index - 1];
        return ListTile(
          leading: CircleAvatar(child: Text(app.appName.characters.first)),
          title: Text(app.appName),
          subtitle: Text(app.packageName),
          trailing: Text(
            app.formattedTime,
            style: Theme.of(context).textTheme.titleMedium,
          ),
        );
      },
    );
  }
}

class _TotalHeader extends StatelessWidget {
  const _TotalHeader({required this.total});

  final Duration total;

  @override
  Widget build(BuildContext context) {
    final h = total.inHours;
    final m = total.inMinutes.remainder(60);
    final label = h > 0 ? '${h}h ${m}min' : '${m}min';
    return Container(
      color: Theme.of(context).colorScheme.primaryContainer,
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Tempo total hoje'),
          const SizedBox(height: 4),
          Text(label, style: Theme.of(context).textTheme.headlineMedium),
        ],
      ),
    );
  }
}

class _PermissionPrompt extends StatelessWidget {
  const _PermissionPrompt({required this.onGrant, required this.onRetry});

  final VoidCallback onGrant;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 80),
        const Icon(Icons.lock_clock, size: 64),
        const SizedBox(height: 16),
        Text(
          'Permissão necessária',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        const Text(
          'Para mostrar o tempo de uso por app, habilite o "Acesso ao uso" '
          'para este app nas Configurações do Android. Depois volte e toque '
          'em "Já concedi".',
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: onGrant,
          child: const Text('Abrir Configurações'),
        ),
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed: onRetry,
          child: const Text('Já concedi'),
        ),
      ],
    );
  }
}
