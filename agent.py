"""
Agente Claude — Suporte Prime / Fecho de OS
Uso: python agent.py
"""

import os
import sys
import json
import base64
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.table import Table
from rich import box
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.live import Live

load_dotenv()

# ─── Paleta Suporte Prime ─────────────────────────────────────────────────────
AZUL    = "#0a1f5c"   # azul escuro
AZUL2   = "#1a3a8f"   # azul médio
LARANJA = "#ff6b00"   # laranja
BRANCO  = "#ffffff"
CINZA   = "#a0aec0"

MODEL       = "claude-sonnet-4-6"
PASTA_FECHO = Path.home() / "Documents" / "FECHO"

console = Console()

SYSTEM_PROMPT = """Você é o assistente da Suporte Prime especializado na automação de fecho de OS.

Pode ajudar a:
- Verificar quais OS precisam ser fechadas hoje ou ontem
- Iniciar a automação AWO → Worten
- Consultar relatórios e erros anteriores
- Analisar screenshots de diagnóstico
- Explicar o estado atual do processo

Responda sempre em português europeu, de forma clara e direta.
Quando sugerir uma ação que requer confirmação do utilizador, aguarde antes de executar."""

MENSAGEM_CLIENTE = (
    "Caro/a Cliente,\n"
    "O serviço de instalação foi concluído. Foi-lhe enviado um sms/e-mail para avaliação, "
    "pedimos a gentileza de responder com base no serviço prestado pelo técnico em sua morada, "
    "pois sua opinião é muito importante para nós.\n"
    "Com os melhores cumprimentos."
)


# ─── UI helpers ───────────────────────────────────────────────────────────────

def banner() -> None:
    logo = Text()
    logo.append("  ⬡  ", style=f"bold {LARANJA}")
    logo.append("SUPORTE PRIME", style=f"bold white")
    logo.append("  ·  Agente de Fecho de OS", style=CINZA)

    console.print()
    console.print(Panel(
        logo,
        border_style=AZUL2,
        padding=(0, 2),
        expand=False,
    ))
    console.print(
        f"  [dim]Ar condicionado · Instalação · Manutenção[/dim]  "
        f"[{CINZA}]912 464 874[/]"
    )
    console.print()


def cabecalho_secao(titulo: str) -> None:
    console.print(Rule(f"[bold {LARANJA}]{titulo}[/]", style=AZUL2))


def imprimir_assistente(texto: str) -> None:
    if not texto.strip():
        return
    console.print(Panel(
        texto,
        title=f"[bold {LARANJA}]◆ Assistente[/]",
        border_style=AZUL2,
        padding=(0, 1),
    ))


def imprimir_ferramenta(nome: str) -> None:
    console.print(f"  [dim {CINZA}]› ferramenta:[/] [{LARANJA}]{nome}[/]")


def imprimir_relatorio(dados: dict) -> None:
    t = Table(box=box.ROUNDED, border_style=AZUL2, show_header=True, header_style=f"bold {LARANJA}")
    t.add_column("Estado", style="white", min_width=14)
    t.add_column("Total", justify="right", style="bold white")

    t.add_row("Concluídas ✓",  f"[bold green]{dados.get('concluidas', 0)}[/]")
    t.add_row("Saltadas",       str(dados.get("saltadas", 0)))
    t.add_row("Erros",          f"[bold red]{dados.get('erros', 0)}[/]")

    console.print()
    cabecalho_secao(f"Relatório · {dados.get('data', '—')}")
    console.print(t)

    erros = dados.get("processos_com_erro", [])
    if erros:
        console.print(f"\n  [{LARANJA}]Processos com erro:[/]")
        for e in erros:
            console.print(f"    [red]·[/] {e['numero']}  →  [dim]{e['motivo']}[/]")
    console.print()


# ─── Ferramentas ──────────────────────────────────────────────────────────────

def _ver_relatorio(data_str: str | None) -> dict:
    if not data_str:
        data_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    caminho = PASTA_FECHO / f"dados_{data_str}.json"
    if not caminho.exists():
        return {"erro": f"Sem relatório para {data_str}. Execute a automação primeiro."}

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    concluidas = sum(1 for d in dados if d.get("status") == "concluida")
    saltadas   = sum(1 for d in dados if d.get("status") == "awo_ok" and not d.get("trabalhos_realizados"))
    erros      = [d for d in dados if d.get("status") == "erro"]

    resultado = {
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
            {"numero": d.get("numero_processo", "?"), "tecnico": d.get("tecnico", ""),
             "status": d.get("status", ""), "data_visita": d.get("data_visita", "")}
            for d in dados
        ],
    }
    imprimir_relatorio(resultado)
    return resultado


def _listar_relatorios() -> dict:
    if not PASTA_FECHO.exists():
        return {"relatorios": [], "aviso": "Pasta FECHO ainda não existe."}
    ficheiros = sorted(PASTA_FECHO.glob("dados_*.json"), reverse=True)
    datas = [f.stem.replace("dados_", "") for f in ficheiros[:10]]

    t = Table(box=box.SIMPLE, border_style=AZUL2, show_header=False)
    t.add_column("Data", style=f"bold {LARANJA}")
    t.add_column("Ficheiro", style=CINZA)
    for d in datas:
        t.add_row(d, f"dados_{d}.json")
    console.print()
    cabecalho_secao("Relatórios disponíveis")
    console.print(t)
    console.print()

    return {"relatorios": datas, "pasta": str(PASTA_FECHO)}


def _executar_automacao(modo: str, data: str | None) -> dict:
    cmd_partes = ["py -3.12 fechar_os.py"]
    if modo == "dry_run":    cmd_partes.append("--dry-run")
    elif modo == "so_awo":   cmd_partes.append("--so-awo")
    elif modo == "so_worten":cmd_partes.append("--so-worten")
    elif modo == "debug":    cmd_partes.append("--debug")
    if data == "hoje":       cmd_partes.append("--hoje")
    cmd = " ".join(cmd_partes)

    console.print()
    cabecalho_secao("Comando de Automação")
    console.print(Panel(
        f"[bold white]{cmd}[/]",
        subtitle=f"[{CINZA}]Copie e execute num terminal[/]",
        border_style=LARANJA,
        padding=(0, 2),
    ))
    console.print(
        f"  [{CINZA}]O browser abre e aguarda o login manual "
        f"antes de iniciar a automação.[/]\n"
    )

    return {
        "comando": cmd,
        "instrucao": "Execute o comando acima num terminal. O script abre o browser e aguarda login manual.",
    }


def _analisar_screenshot(caminho: str, client: anthropic.Anthropic) -> dict:
    p = Path(caminho) if caminho else None
    if not p or not p.exists():
        shots = sorted(Path(".").glob("debug_*.png"))
        if not shots:
            return {"erro": "Nenhum screenshot de diagnóstico encontrado."}
        p = shots[-1]

    console.print(f"  [{CINZA}]A analisar:[/] [bold]{p.name}[/]")
    dados_b64 = base64.standard_b64encode(p.read_bytes()).decode()

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": dados_b64}},
                {"type": "text", "text": (
                    "Este screenshot foi gerado pelo script fechar_os.py quando falhou. "
                    "Analisa o que está visível na página e explica o provável problema "
                    "(botão não encontrado, estado inesperado, campo em falta, etc.)."
                )},
            ],
        }],
    )
    analise = next((b.text for b in resp.content if b.type == "text"), "Sem análise.")
    return {"caminho": str(p), "analise": analise}


def _diagnosticar_script(url: str) -> dict:
    cmd = f'py -3.12 fechar_os.py --scan-form "{url}"'
    console.print()
    cabecalho_secao("Diagnóstico de Formulário")
    console.print(Panel(f"[bold white]{cmd}[/]", border_style=LARANJA, padding=(0, 2)))
    console.print(f"  [{CINZA}]Execute após fazer login no AWO. Imprime todos os campos da página.[/]\n")
    return {"comando": cmd}


# ─── Definição das ferramentas para a API ────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "ver_relatorio",
        "description": "Lê e resume o relatório JSON de uma execução anterior. Mostra OS concluídas, saltadas e erros.",
        "input_schema": {
            "type": "object",
            "properties": {"data": {"type": "string", "description": "YYYY-MM-DD. Se omitida, usa ontem."}},
            "required": [],
        },
    },
    {
        "name": "listar_relatorios",
        "description": "Lista os relatórios disponíveis na pasta FECHO (últimas 10 execuções).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "executar_automacao",
        "description": "Gera o comando para executar a automação de fecho de OS.",
        "input_schema": {
            "type": "object",
            "properties": {
                "modo": {
                    "type": "string",
                    "enum": ["completo", "dry_run", "so_awo", "so_worten", "debug"],
                    "description": "completo=AWO+Worten | dry_run=só lista | so_awo=só AWO | so_worten=só Worten | debug=eventos",
                },
                "data": {"type": "string", "enum": ["ontem", "hoje"]},
            },
            "required": ["modo"],
        },
    },
    {
        "name": "analisar_screenshot",
        "description": "Analisa um debug_*.png com visão do Claude para identificar falhas na automação.",
        "input_schema": {
            "type": "object",
            "properties": {"caminho": {"type": "string", "description": "Caminho PNG. Se omitido, usa o mais recente."}},
            "required": [],
        },
    },
    {
        "name": "diagnosticar_script",
        "description": "Gera comando --scan-form para inspecionar campos de um formulário AWO.",
        "input_schema": {
            "type": "object",
            "properties": {"url_relativa": {"type": "string", "description": "Ex: /work-orders/edit/12345"}},
            "required": ["url_relativa"],
        },
    },
]


# ─── Loop do agente ───────────────────────────────────────────────────────────

def executar_ferramenta(nome: str, inputs: dict, client: anthropic.Anthropic) -> Any:
    if nome == "ver_relatorio":
        return _ver_relatorio(inputs.get("data"))
    if nome == "listar_relatorios":
        return _listar_relatorios()
    if nome == "executar_automacao":
        return _executar_automacao(inputs.get("modo", "completo"), inputs.get("data"))
    if nome == "analisar_screenshot":
        return _analisar_screenshot(inputs.get("caminho", ""), client)
    if nome == "diagnosticar_script":
        return _diagnosticar_script(inputs.get("url_relativa", ""))
    return {"erro": f"Ferramenta desconhecida: {nome}"}


def run_agent() -> None:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    messages: list[dict] = []

    banner()

    shots = list(Path(".").glob("debug_*.png"))
    contexto_extra = ""
    if shots:
        nomes = ", ".join(p.name for p in sorted(shots)[-3:])
        contexto_extra = f"\n\nScreenshots de diagnóstico disponíveis: {nomes}"
        console.print(f"  [{LARANJA}]⚠[/]  {len(shots)} screenshot(s) de diagnóstico encontrado(s).\n")

    console.print(f"  [{CINZA}]Digite [bold white]sair[/] para encerrar · [bold white]?[/] para ajuda[/]\n")

    while True:
        try:
            user_input = Prompt.ask(f"[bold {LARANJA}]Você[/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n  [{CINZA}]Até logo! — Suporte Prime[/]\n")
            break

        if not user_input:
            continue
        if user_input.lower() in {"sair", "exit", "quit"}:
            console.print(f"\n  [{LARANJA}]◆[/] Até logo! — Suporte Prime\n")
            break
        if user_input == "?":
            t = Table(box=box.SIMPLE, border_style=AZUL2, show_header=False, padding=(0, 1))
            t.add_column("Pergunta", style=f"bold {LARANJA}")
            t.add_column("Exemplo", style=CINZA)
            t.add_row("Ver relatório",    "quais OS foram fechadas ontem?")
            t.add_row("Iniciar automação","como inicio a automação de hoje?")
            t.add_row("Ver erros",        "houve erros na última execução?")
            t.add_row("Analisar falha",   "analisa o screenshot de erro")
            t.add_row("Diagnosticar",     "diagnostica /work-orders/edit/12345")
            console.print(t)
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            with Live(Spinner("dots", text=f"[{CINZA}]A processar...[/]"), console=console, transient=True):
                pass

            while True:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    system=[{"type": "text", "text": SYSTEM_PROMPT + contexto_extra,
                              "cache_control": {"type": "ephemeral"}}],
                    tools=TOOLS,
                    messages=messages,
                )

                assistant_content: list[dict] = []
                tool_calls: list[dict] = []

                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                        imprimir_assistente(block.text)
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": block.input,
                        })
                        tool_calls.append(block)
                        imprimir_ferramenta(block.name)

                messages.append({"role": "assistant", "content": assistant_content})

                if response.stop_reason != "tool_use" or not tool_calls:
                    break

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
            console.print(f"  [bold red]Erro:[/] chave de API inválida. Verifique o [bold].env[/].")
            break
        except anthropic.RateLimitError:
            console.print(f"  [{LARANJA}]Aviso:[/] limite de requisições atingido. Tente novamente.")
            messages.pop()
        except anthropic.APIError as exc:
            console.print(f"  [bold red]Erro da API:[/] {exc}")
            messages.pop()


if __name__ == "__main__":
    run_agent()
