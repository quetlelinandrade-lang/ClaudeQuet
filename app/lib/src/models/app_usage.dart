/// Representa o tempo de uso de um app em um período.
class AppUsage {
  const AppUsage({
    required this.packageName,
    required this.appName,
    required this.totalTime,
  });

  /// Identificador do pacote (ex.: com.instagram.android).
  final String packageName;

  /// Nome legível do app (ex.: Instagram). Cai para o packageName se
  /// o nome não puder ser resolvido.
  final String appName;

  /// Tempo total de uso no período.
  final Duration totalTime;

  factory AppUsage.fromMap(Map<dynamic, dynamic> map) {
    return AppUsage(
      packageName: map['packageName'] as String? ?? 'desconhecido',
      appName: map['appName'] as String? ?? 'Desconhecido',
      totalTime: Duration(milliseconds: (map['totalTimeMs'] as num?)?.toInt() ?? 0),
    );
  }

  /// Formata a duração como "2h 15min" ou "43min".
  String get formattedTime {
    final hours = totalTime.inHours;
    final minutes = totalTime.inMinutes.remainder(60);
    if (hours > 0) return '${hours}h ${minutes}min';
    if (minutes > 0) return '${minutes}min';
    return '${totalTime.inSeconds}s';
  }
}
