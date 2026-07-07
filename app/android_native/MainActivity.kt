// Substitua a MainActivity.kt gerada pelo `flutter create` por este arquivo.
// IMPORTANTE: mantenha a primeira linha `package ...` idêntica à do arquivo
// gerado (ela depende do applicationId que você escolheu no flutter create).
package com.example.parental_monitor

import android.app.AppOpsManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.os.Process
import android.provider.Settings
import androidx.annotation.NonNull
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.Calendar

class MainActivity : FlutterActivity() {

    private val channelName = "parental_monitor/usage"

    override fun configureFlutterEngine(@NonNull flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "hasUsageAccess" -> result.success(hasUsageAccess())
                    "openUsageAccessSettings" -> {
                        openUsageAccessSettings()
                        result.success(null)
                    }
                    "getUsageToday" -> result.success(getUsageToday())
                    else -> result.notImplemented()
                }
            }
    }

    /** Verifica se a permissão PACKAGE_USAGE_STATS foi concedida nas Configurações. */
    private fun hasUsageAccess(): Boolean {
        val appOps = getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = appOps.unsafeCheckOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            Process.myUid(),
            packageName
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    /** Abre a tela do sistema onde o usuário concede o "Acesso ao uso". */
    private fun openUsageAccessSettings() {
        val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
    }

    /**
     * Retorna o uso agregado por pacote entre a meia-noite de hoje e agora.
     * Cada item é um Map com packageName, appName e totalTimeMs.
     */
    private fun getUsageToday(): List<Map<String, Any>> {
        val usageStatsManager =
            getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager

        val end = System.currentTimeMillis()
        val start = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }.timeInMillis

        val aggregated = usageStatsManager.queryAndAggregateUsageStats(start, end)
        val pm = packageManager

        return aggregated.values
            .filter { it.totalTimeInForeground > 0 }
            .map { stat ->
                val appName = try {
                    val info = pm.getApplicationInfo(stat.packageName, 0)
                    pm.getApplicationLabel(info).toString()
                } catch (e: Exception) {
                    stat.packageName
                }
                mapOf(
                    "packageName" to stat.packageName,
                    "appName" to appName,
                    "totalTimeMs" to stat.totalTimeInForeground
                )
            }
    }
}
