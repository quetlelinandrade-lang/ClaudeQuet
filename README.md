# ⬡ Suporte Prime — Automação de Fecho de OS

> **Ar Condicionado · Instalação · Manutenção**  
> Sobral de Monte Agraço · Grande Lisboa · 912 464 874

---

## O que faz

Automatiza o fecho diário das Ordens de Serviço realizadas pelos técnicos:

1. **AWO Soft** — lê as OS com estado *Realizado* e descrição preenchida, descarrega imagens e exporta PDF
2. **Worten Resolve** — preenche o relatório de serviço, anexa o PDF e conclui o processo
3. **Mensagem ao cliente** — envia automaticamente o texto de avaliação

---

## Ficheiros

| Ficheiro | Função |
|---|---|
| `fechar_os.py` | Script principal de automação (Playwright) |
| `agent.py` | Agente Claude com ferramentas de diagnóstico |
| `.env` | Credenciais e URL da plataforma |

---

## Instalação

```bash
pip install -r requirements.txt
playwright install chromium
```

Criar o ficheiro `.env` (ver `.env.example`):

```env
ANTHROPIC_API_KEY=sk-ant-...
PLATFORM_URL=https://suporteprime.awo-soft.com
```

---

## Uso — Script de automação

```bash
# Fluxo completo AWO + Worten (processa ontem)
py -3.12 fechar_os.py

# Simular sem alterar nada
py -3.12 fechar_os.py --dry-run

# Só fechar no AWO (pular Worten)
py -3.12 fechar_os.py --so-awo

# Só processar na Worten (relê dados AWO)
py -3.12 fechar_os.py --so-worten

# Processar o dia de hoje
py -3.12 fechar_os.py --hoje

# Diagnóstico de uma OS específica
py -3.12 fechar_os.py --scan-form /work-orders/edit/XXXXX
```

> O script abre o browser e aguarda o **login manual** antes de iniciar.

---

## Uso — Agente Claude

```bash
python agent.py
```

O agente responde em linguagem natural e tem acesso a ferramentas:

| Ferramenta | O que faz |
|---|---|
| `ver_relatorio` | Resume OS concluídas, saltadas e erros de uma data |
| `listar_relatorios` | Lista execuções disponíveis |
| `executar_automacao` | Gera o comando correto para o terminal |
| `analisar_screenshot` | Analisa `debug_*.png` com visão do Claude |
| `diagnosticar_script` | Inspeciona campos de formulário AWO |

---

## Fluxo completo

```
AWO  ▶ Verificar Estado = Realizado + "Trabalhos Realizados" preenchido
AWO  ▶ Copiar: nº processo (antes da /) · data · técnico · texto TR
AWO  ▶ Descarregar imagens · Exportar OS como PDF

WORTEN ▶ Pesquisar número do processo
WORTEN ▶ JUSTIFICAR → Sim + data + "Atualizei ao final do dia" → AVANÇAR
WORTEN ▶ ATUALIZAR PEDIDO
WORTEN ▶ Modal: Concluir Serviço → Serviço concluído ✓
WORTEN ▶ PREENCHER RELATÓRIO → campos + fotos → ENVIAR RELATÓRIO
WORTEN ▶ ANEXOS → upload PDF → GUARDAR
WORTEN ▶ ATUALIZAR PEDIDO (2ª vez) → Concluir → Confirmar
WORTEN ▶ CONCLUIR SERVIÇO → FECHAR modal
WORTEN ▶ ENVIAR MENSAGEM AO CLIENTE → mensagem fixa → Enviar

FIM  ▶ OS concluída · avançar para a próxima
```

---

## Regras do script

| Regra | Detalhe |
|---|---|
| Número do processo | Sempre a parte **antes** do `/` |
| Motivo de check-in | Sempre *"Atualizei o pedido ao final do dia"* |
| OS sem descrição | Saltar e continuar — nunca parar o script |
| Erro num processo | Registar e continuar — nunca parar o script |
| Login | Aguardar login manual antes de iniciar |

---

*Suporte Prime © 2026 · Conforto que faz a diferença.*
