"""
Agente Claude — Suporte Prime / Fecho de OS
Uso: python agent.py
"""

import os
import sys
import json
import base64
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL        = "claude-sonnet-4-6"
PASTA_FECHO  = Path.home() / "Documents" / "FECHO"
DEBUG_SHOTS  = [p for p in Path(".").glob("debug_*.png")]

SYSTEM_PROMPT = """Você é o assistente da Suporte Prime especializado na automação de fecho de OS.

Pode ajudar a:
- Verificar quais OS precisam ser fechadas hoje ou ontem
- Iniciar a automação AWO → Worten
- Consultar relatórios e erros anteriores
- Analisar screenshots de diagnóstico
- Explicar o estado atual do processo

Responda sempre em português europeu, de forma clara e direta.
Quando sugerir uma ação que requer confirmação do utilizador, aguarde antes de executar."""


# ─── Implementações das ferramentas ─────────────────────────────────────────

def _ver_relatorio(data_str: str | None) -> dict:
    if not data_str:
        alvo = date.today() - timedelta(days=1)
        data_str = alvo.strftime("%Y-%m-%d")

    caminho = PASTA_FECHO / f"dados_{data_str}.json"
    if not caminho.exists():
        return {"erro": f"Sem relatório para {data_str}. Execute a automação primeiro."}

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    concluidas = sum(1 for d in dados if d.get("status") == "concluida")
    saltadas   = sum(1 for d in dados if d.get("status") in ("awo_ok",) and not d.get("trabalhos_realizados"))
    erros      = [d for d in dados if d.get("status") == "erro"]

    return {
        "data": data_str,
        "total": len(dados),
        "concluidas": concluidas,
        "saltadas": saltadas,
        "erros": len(erros),
        "processos_com_erro": [
            {"numero": d.get("numero_processo", "?"), "motivo": d.get("motivo", "")}
            for d in erros
        ],
        "todos": [
            {
                "numero": d.get("numero_processo", "?"),
                "tecnico": d.get("tecnico", ""),
                "status": d.get("status", ""),
                "data_visita": d.get("data_visita", ""),
            }
            for d in dados
        ],
    }


def _listar_relatorios() -> dict:
    if not PASTA_FECHO.exists():
        return {"relatorios": [], "aviso": "Pasta FECHO ainda não existe."}
    ficheiros = sorted(PASTA_FECHO.glob("dados_*.json"), reverse=True)
    return {
        "relatorios": [f.stem.replace("dados_", "") for f in ficheiros[:10]],
        "pasta": str(PASTA_FECHO),
    }


def _executar_automacao(modo: str, data: str | None) -> dict:
    cmd = [sys.executable, "fechar_os.py"]
    if modo == "dry_run":
        cmd.append("--dry-run")
    elif modo == "so_awo":
        cmd.append("--so-awo")
    elif modo == "so_worten":
        cmd.append("--so-worten")
    elif modo == "debug":
        cmd.append("--debug")

    if data == "hoje":
        cmd.append("--hoje")

    return {
        "comando": " ".join(cmd),
        "instrucao": (
            "O script abre um navegador e aguarda o login manual. "
            "Execute o comando acima num terminal. "
            "O script termina sozinho e imprime o relatório final."
        ),
        "aviso": "Este agente não executa o browser diretamente. Copie o comando para o terminal.",
    }


def _analisar_screenshot(caminho: str) -> dict:
    p = Path(caminho)
    if not p.exists():
        shots = list(Path(".").glob("debug_*.png"))
        if shots:
            p = sorted(shots)[-1]
        else:
            return {"erro": "Screenshot não encontrado."}

    dados = base64.standard_b64encode(p.read_bytes()).decode()
    return {"_imagem_base64": dados, "_caminho": str(p)}


def _diagnosticar_script(url_relativa: str) -> dict:
    return {
        "comando": f'py -3.12 fechar_os.py --scan-form "{url_relativa}"',
        "instrucao": (
            "Execute este comando no terminal após fazer login no AWO. "
            "O script imprime todos os selects, inputs, labels e textareas da página."
        ),
    }


# ─── Definição das ferramentas para a API ────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "ver_relatorio",
        "description": (
            "Lê e resume o relatório JSON de uma execução anterior da automação. "
            "Mostra quantas OS foram concluídas, saltadas e com erros."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "Data no formato YYYY-MM-DD. Se omitida, usa ontem.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "listar_relatorios",
        "description": "Lista os relatórios JSON disponíveis na pasta FECHO (últimas 10 execuções).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "executar_automacao",
        "description": (
            "Gera o comando para executar a automação de fecho de OS. "
            "O agente não abre o browser, mas fornece o comando exato para copiar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "modo": {
                    "type": "string",
                    "enum": ["completo", "dry_run", "so_awo", "so_worten", "debug"],
                    "description": (
                        "completo=AWO+Worten | dry_run=só lista | "
                        "so_awo=só fecha no AWO | so_worten=só processa Worten | "
                        "debug=mostra eventos e sai"
                    ),
                },
                "data": {
                    "type": "string",
                    "enum": ["ontem", "hoje"],
                    "description": "Dia a processar. Padrão: ontem.",
                },
            },
            "required": ["modo"],
        },
    },
    {
        "name": "analisar_screenshot",
        "description": (
            "Analisa um screenshot de diagnóstico (debug_*.png) gerado pelo script "
            "para identificar o que está a falhar na página."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "caminho": {
                    "type": "string",
                    "description": "Caminho para o ficheiro PNG. Se omitido, usa o mais recente.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "diagnosticar_script",
        "description": (
            "Gera o comando --scan-form para inspecionar os campos de um formulário AWO. "
            "Útil para depurar quando o script não encontra um campo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url_relativa": {
                    "type": "string",
                    "description": "Caminho relativo da OS, ex: /work-orders/edit/12345",
                }
            },
            "required": ["url_relativa"],
        },
    },
]


# ─── Execução das ferramentas ─────────────────────────────────────────────────

def executar_ferramenta(nome: str, inputs: dict, client: anthropic.Anthropic) -> Any:
    if nome == "ver_relatorio":
        return _ver_relatorio(inputs.get("data"))
    if nome == "listar_relatorios":
        return _listar_relatorios()
    if nome == "executar_automacao":
        return _executar_automacao(inputs.get("modo", "completo"), inputs.get("data"))
    if nome == "analisar_screenshot":
        resultado = _analisar_screenshot(inputs.get("caminho", ""))
        if "_imagem_base64" in resultado:
            # Envia a imagem para o modelo analisar (visão)
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": resultado["_imagem_base64"],
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Este screenshot foi gerado pelo script fechar_os.py quando falhou. "
                                    "Analisa o que está visível na página e explica o provável problema "
                                    "de automação (botão não encontrado, estado inesperado, etc.)."
                                ),
                            },
                        ],
                    }
                ],
            )
            analise = next(
                (b.text for b in resp.content if b.type == "text"), "Sem análise."
            )
            return {"caminho": resultado["_caminho"], "analise": analise}
        return resultado
    if nome == "diagnosticar_script":
        return _diagnosticar_script(inputs.get("url_relativa", ""))
    return {"erro": f"Ferramenta desconhecida: {nome}"}


# ─── Loop principal do agente ─────────────────────────────────────────────────

def run_agent() -> None:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    messages: list[dict] = []

    shots = list(Path(".").glob("debug_*.png"))
    contexto_inicial = ""
    if shots:
        contexto_inicial = (
            f"\n\nNota: há {len(shots)} screenshot(s) de diagnóstico disponíveis: "
            + ", ".join(p.name for p in sorted(shots)[-3:])
        )

    print("=== Agente Suporte Prime — Fecho de OS ===")
    if contexto_inicial:
        print(contexto_inicial.strip())
    print("Digite 'sair' para encerrar.\n")

    while True:
        try:
            user_input = input("Você: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAté logo!")
            break

        if not user_input:
            continue
        if user_input.lower() in {"sair", "exit", "quit"}:
            print("Até logo!")
            break

        messages.append({"role": "user", "content": user_input})

        try:
            while True:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT + contexto_inicial,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=TOOLS,
                    messages=messages,
                )

                # Acumula o que o assistente disse/fez nesta volta
                assistant_content: list[dict] = []
                tool_calls: list[dict] = []

                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                        if block.text:
                            print(f"\nAssistente: {block.text}\n")
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                        tool_calls.append(block)
                        print(f"  [ferramenta: {block.name}]")

                messages.append({"role": "assistant", "content": assistant_content})

                if response.stop_reason != "tool_use" or not tool_calls:
                    break

                # Executa as ferramentas e devolve os resultados
                tool_results: list[dict] = []
                for call in tool_calls:
                    resultado = executar_ferramenta(call.name, call.input, client)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    })

                messages.append({"role": "user", "content": tool_results})

        except anthropic.AuthenticationError:
            print("Erro: chave de API inválida. Verifique o .env.")
            break
        except anthropic.RateLimitError:
            print("Limite de requisições atingido. Tente novamente.")
            messages.pop()
        except anthropic.APIError as exc:
            print(f"Erro da API: {exc}")
            messages.pop()


if __name__ == "__main__":
    run_agent()
