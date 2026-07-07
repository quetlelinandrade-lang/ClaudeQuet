# Planejamento — App de Monitoramento Infantil (estilo Family Link)

> Documento de arquitetura e decisões. Nenhum código de app foi escrito ainda —
> esta é a base para guiar o desenvolvimento.

## 1. Objetivo

Criar um aplicativo de controle parental, publicável na **App Store (iOS)** e na
**Google Play (Android)**, com funcionalidades no estilo do Google Family Link:

- Tempo de tela (total e por app)
- Limites de uso e "hora de dormir"
- Bloqueio de apps
- Relatórios para os pais
- Vínculo entre o dispositivo da criança e a conta dos pais

---

## 2. A restrição mais importante (leia antes de tudo)

Family Link (Google) e Screen Time (Apple) funcionam tão bem porque são feitos
**pelas donas do sistema operacional**. Elas usam APIs privilegiadas que apps de
terceiros **não têm**. Isso define todo o projeto:

### iOS — muito restritivo
- A Apple **não permite** que apps de terceiros leiam livremente o uso de outros
  apps, histórico de navegação ou teclado. Apps assim são **removidos da loja**.
- A **única via oficial** é a **Screen Time API** da Apple, composta por três
  frameworks:
  - `FamilyControls` — autorização e seleção de apps a gerenciar
  - `ManagedSettings` — aplicar restrições (bloquear apps, limites)
  - `DeviceActivity` — monitorar uso e disparar eventos (ex.: passou do limite)
- Essa API exige um **entitlement especial** (`com.apple.developer.family-controls`)
  que precisa ser **solicitado à Apple** com justificativa. **Este é o maior risco
  do projeto — validar isso deve ser o passo 1.**

### Android — mais aberto, mas com regras
- Ler tempo por app: `UsageStatsManager` (requer permissão especial do usuário).
- Bloquear / aplicar políticas: `DevicePolicyManager` (Device Admin) ou
  `AccessibilityService` para detectar/bloquear apps em primeiro plano.
- A Play Store **restringe** apps que usam `AccessibilityService` para monitoramento.
  É permitido **quando enquadrado como controle parental** — você precisa declarar
  isso na ficha do app e na política de privacidade.

**Conclusão:** dá para fazer, mas SEMPRE pelas APIs oficiais de cada plataforma.
Hacks levam a banimento das lojas.

---

## 3. Stack recomendada (a decisão)

Como você vai manter o projeto e quer publicar nas duas lojas, a recomendação é:

| Camada | Escolha | Por quê |
|---|---|---|
| **UI / apps** | **Flutter** | Um só código Dart para iOS e Android. A UI (app dos pais e telas da criança) fica 100% compartilhada. Ótima ponte para código nativo. |
| **Monitoramento Android** | Módulo **Kotlin** (plugin Flutter) | `UsageStatsManager`, `DevicePolicyManager`, overlay para bloqueio. |
| **Monitoramento iOS** | Módulo **Swift** (plugin Flutter) | Screen Time API (`FamilyControls`/`ManagedSettings`/`DeviceActivity`). |
| **Backend (MVP)** | **Firebase** | Auth, Firestore (dados), Cloud Messaging (push), Cloud Functions. Mais rápido para chegar a um MVP. |
| **Backend (futuro)** | Node/Python + PostgreSQL | Migrar quando precisar de controle total / custo previsível. |

### Por que Flutter e não React Native ou nativo puro?
- **vs. Nativo (Swift + Kotlin):** nativo dá o melhor acesso às APIs de Screen Time,
  mas dobra o trabalho de UI. Como quase toda a "parte difícil" (monitoramento) já
  precisa de código nativo em **ambos** os caminhos, Flutter economiza na UI sem
  perder o acesso nativo (via plugins/platform channels).
- **vs. React Native:** ambos servem. Flutter tende a ter tooling mais consistente
  e melhor performance de UI. Se você já domina JavaScript/React, RN é válido.

---

## 4. Arquitetura

Todo app de controle parental tem **dois lados** + backend:

```
┌──────────────────┐        ┌────────────────┐        ┌──────────────────┐
│  App da Criança  │ ─────► │    Backend     │ ◄───── │   App dos Pais   │
│  (iOS/Android)   │  uso,  │  Auth + DB +   │ regras │  (iOS/Android)   │
│                  │ status │  Push (FCM)    │        │                  │
│ - coleta uso     │        │                │        │ - vê relatórios  │
│ - aplica limites │        └────────────────┘        │ - define regras  │
│ - bloqueia apps  │                                  │ - aprova pedidos │
└──────────────────┘                                  └──────────────────┘
```

### Fluxos principais
1. **Vínculo:** pai cria conta → gera código/QR → criança insere no device → device
   fica associado à família.
2. **Coleta:** app da criança coleta uso (nativo) e envia resumos ao backend.
3. **Regras:** pai define limites → backend salva → push notifica o device → device
   aplica via API nativa.
4. **Pedidos:** criança pede "mais 15 min" → push para o pai → pai aprova/nega.

### Modelo de dados (esboço Firestore)
```
families/{familyId}
  parents/{userId}      { nome, email }
  children/{childId}    { nome, deviceId, plataforma }
  rules/{childId}       { limiteDiario, horaDeDormir, appsBloqueados[] }
  usage/{childId}/{dia} { totalMin, porApp: { pacote: min } }
  requests/{reqId}      { childId, tipo, status, timestamp }
```

---

## 5. Roadmap de desenvolvimento (MVP → produto)

### Fase 0 — Validação (fazer primeiro, é o maior risco)
- [ ] Entrar no **Apple Developer Program** (US$ 99/ano).
- [ ] **Solicitar o entitlement** `com.apple.developer.family-controls` à Apple.
- [ ] Entrar no **Google Play Console** (taxa única US$ 25).
- [ ] Ler as políticas de dados de menores das duas lojas.

### Fase 1 — MVP Android (feedback rápido)
- [ ] App Flutter básico com login (Firebase Auth).
- [ ] Plugin Kotlin lendo `UsageStatsManager` → "tempo por app hoje".
- [ ] Tela de relatório no app dos pais.

### Fase 2 — Backend e vínculo
- [ ] Modelo de dados no Firestore.
- [ ] Fluxo de vínculo pai↔filho (código/QR).
- [ ] Sincronização de uso device → backend → app dos pais.

### Fase 3 — Controles
- [ ] Limite diário + "hora de dormir" (Android via DevicePolicy/overlay).
- [ ] Bloqueio de apps específicos.
- [ ] Push (FCM) para aplicar regras e enviar pedidos.

### Fase 4 — iOS
- [ ] Plugin Swift com Screen Time API (dentro dos limites da Apple).
- [ ] Paridade possível de features (o iOS terá limitações — documentar quais).

### Fase 5 — Publicação
- [ ] Política de privacidade + tela de consentimento.
- [ ] Fichas nas lojas declarando "controle parental".
- [ ] Testes beta (TestFlight / Play Internal Testing).

---

## 6. Aspectos legais (não é opcional)

Dados de menores são fortemente regulados. Isso **decide** aprovação nas lojas e
risco de processo:

- **LGPD (Brasil):** consentimento dos responsáveis, finalidade clara, minimização.
- **COPPA (EUA):** exige consentimento parental verificável para menores de 13 anos.
- **GDPR (Europa):** consentimento e direito ao esquecimento.

Requisitos práticos:
- Política de privacidade pública e clara.
- Coletar o **mínimo** de dados necessário.
- Tela de consentimento explícito no primeiro uso.
- Transparência: a criança deve saber que está sendo monitorada (exigido pelas lojas).

---

## 7. Riscos e mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| Apple negar o entitlement | Alto — sem iOS | Validar na Fase 0, antes de investir em código |
| Rejeição na Play por AccessibilityService | Alto | Enquadrar como controle parental, declarar corretamente |
| iOS com menos features que Android | Médio | Documentar diferenças; alinhar expectativa do usuário |
| Custos de backend crescerem | Médio | Começar no Firebase free tier; migrar depois |
| Conformidade legal | Alto | Política de privacidade + consentimento desde o MVP |

---

## 8. Próximos passos sugeridos

1. **Decidir a stack** (recomendação: Flutter + Firebase).
2. **Fazer a Fase 0** — validar o entitlement da Apple é o que destrava o resto.
3. Quando quiser código, começar pela **Fase 1 (MVP Android)** — é o caminho de
   resultado visível mais rápido.

> Quando quiser sair do planejamento, é só pedir que eu monto o esqueleto do
> projeto Flutter e o primeiro módulo Android de leitura de uso.
