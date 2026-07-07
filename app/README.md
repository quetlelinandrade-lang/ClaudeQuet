# App — Fase 1 (MVP Android: tempo de tela por app)

Este diretório contém o **código do app Flutter** e o **módulo nativo Android**
(Kotlin) que lê o tempo de uso por app via `UsageStatsManager`.

> ⚠️ **Por que não há a pasta `android/` completa aqui?**
> O boilerplate de build do Flutter (Gradle, AGP, Kotlin) é sensível a versões.
> Gerá-lo à mão levaria a erros de build no seu ambiente. Em vez disso, você o
> gera com o **seu próprio SDK** (garantindo compatibilidade) e adiciona os dois
> arquivos nativos que estão em `android_native/`.

## Pré-requisitos

- [Flutter SDK](https://docs.flutter.dev/get-started/install) (3.3+), com
  `flutter doctor` sem erros para Android.
- Android Studio + um dispositivo/emulador Android.
- Um **aparelho Android físico** é ideal (o emulador tem pouco histórico de uso).

## Setup (uma vez)

A partir da pasta `app/`:

```bash
# 1. Gera o boilerplate de plataforma (android/ e ios/) SEM sobrescrever lib/.
#    Escolha o applicationId com --org (ex.: com.seunome -> com.seunome.parental_monitor).
flutter create --org com.seunome --platforms=android,ios --project-name parental_monitor .

# 2. Baixa as dependências.
flutter pub get
```

### Adicionar o módulo nativo

1. **MainActivity.kt** — o `flutter create` gerou um em
   `android/app/src/main/kotlin/<seu/pacote>/MainActivity.kt`.
   Substitua o conteúdo dele pelo de `android_native/MainActivity.kt`,
   **mantendo a linha `package ...` original** (ela reflete o `--org` que você usou).

2. **AndroidManifest.xml** — abra
   `android/app/src/main/AndroidManifest.xml` e aplique as adições descritas em
   `android_native/AndroidManifest.snippet.xml` (permissão `PACKAGE_USAGE_STATS`,
   namespace `tools` e bloco `<queries>`).

## Rodar

```bash
flutter run
```

Na primeira execução o app vai pedir para você habilitar o **"Acesso ao uso"**
nas Configurações do Android (essa permissão não pode ser concedida por diálogo
comum). Toque em **Abrir Configurações**, habilite o app, volte e toque em
**Já concedi**.

## O que este MVP faz

- Lê o tempo de uso por app **de hoje** (meia-noite → agora).
- Mostra o **total do dia** e a lista de apps ordenada por tempo.
- Trata o fluxo de permissão do Android.

## O que ele NÃO faz ainda (próximas fases — ver ../PLANEJAMENTO.md)

- Não envia dados a um backend (Fase 2).
- Não aplica limites nem bloqueios (Fase 3).
- Não funciona no iOS — lá o uso de outros apps só é acessível via Screen Time
  API, com entitlement da Apple (Fase 4). Neste MVP, no iOS a tela aparece vazia.

## Estrutura

```
app/
├── pubspec.yaml
├── analysis_options.yaml
├── lib/
│   ├── main.dart
│   └── src/
│       ├── usage_service.dart          # ponte Dart <-> Kotlin (MethodChannel)
│       ├── models/app_usage.dart
│       └── screens/home_screen.dart
└── android_native/                     # aplicar após o flutter create
    ├── MainActivity.kt
    └── AndroidManifest.snippet.xml
```
