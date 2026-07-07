import 'package:flutter/services.dart';

import 'models/app_usage.dart';

/// Ponte entre o Flutter (Dart) e o código nativo Android (Kotlin) que lê o
/// tempo de uso via UsageStatsManager.
///
/// No iOS este serviço não funciona: a Apple não expõe o uso de outros apps a
/// terceiros fora da Screen Time API (ver PLANEJAMENTO.md, Fase 4). Os métodos
/// retornam valores vazios/false em plataformas não suportadas.
class UsageService {
  static const MethodChannel _channel =
      MethodChannel('parental_monitor/usage');

  /// Verifica se o usuário já concedeu a permissão de "Acesso ao uso"
  /// (PACKAGE_USAGE_STATS). No Android ela não pode ser pedida via diálogo
  /// comum — o usuário precisa habilitar nas Configurações do sistema.
  Future<bool> hasUsageAccess() async {
    try {
      final granted = await _channel.invokeMethod<bool>('hasUsageAccess');
      return granted ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      // Plataforma sem implementação nativa (ex.: iOS).
      return false;
    }
  }

  /// Abre a tela de "Acesso ao uso" nas Configurações do Android para o
  /// usuário conceder a permissão.
  Future<void> openUsageAccessSettings() async {
    try {
      await _channel.invokeMethod<void>('openUsageAccessSettings');
    } on PlatformException {
      // Silencioso: a UI já orienta o usuário.
    } on MissingPluginException {
      // Plataforma não suportada.
    }
  }

  /// Retorna o uso por app referente ao dia de hoje (da meia-noite até agora),
  /// ordenado do maior para o menor tempo. Lista vazia se a permissão não foi
  /// concedida ou a plataforma não é suportada.
  Future<List<AppUsage>> getUsageToday() async {
    try {
      final raw = await _channel.invokeMethod<List<dynamic>>('getUsageToday');
      if (raw == null) return const [];
      final list = raw
          .map((e) => AppUsage.fromMap(e as Map<dynamic, dynamic>))
          .where((u) => u.totalTime.inSeconds > 0)
          .toList()
        ..sort((a, b) => b.totalTime.compareTo(a.totalTime));
      return list;
    } on PlatformException {
      return const [];
    } on MissingPluginException {
      return const [];
    }
  }
}
