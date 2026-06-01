"""
Agente de Publicidade — Suporte Prime
Gera conteúdo para redes sociais, campanhas e comunicação com clientes.
Uso: python agente_publicidade.py
"""

import os
import json
from datetime import date
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
from rich.markdown import Markdown

load_dotenv()

# ─── Paleta Suporte Prime ─────────────────────────────────────────────────────
AZUL    = "#0a1f5c"
AZUL2   = "#1a3a8f"
LARANJA = "#ff6b00"
CINZA   = "#a0aec0"

MODEL = "claude-sonnet-4-6"

console = Console()

# ─── Identidade da marca ──────────────────────────────────────────────────────

MARCA = {
    "nome": "Suporte Prime",
    "slogan": "Conforto que faz a diferença.",
    "servicos": ["Ar Condicionado", "Instalação", "Manutenção", "Termoacumuladores"],
    "zonas": ["Lisboa e arredores", "Sintra · Cascais · Oeiras",
              "Loures · Amadora · Odivelas", "Setúbal · Almada · Seixal",
              "Torres Vedras · Mafra · Alenquer"],
    "telefone": "+351 912 464 874",
    "valores": ["Conforto", "Serviço", "Qualidade", "Profissionalismo", "Confiança"],
    "tom": "profissional mas próximo, direto, confiante, sem exageros",
    "emojis_marca": ["❄️", "🔧", "✅", "🏠", "⚡"],
}

SYSTEM_PROMPT = f"""És o agente de publicidade e marketing da {MARCA['nome']}.

IDENTIDADE DA MARCA:
- Nome: {MARCA['nome']}
- Slogan: "{MARCA['slogan']}"
- Serviços: {', '.join(MARCA['servicos'])}
- Zonas de cobertura: {', '.join(MARCA['zonas'])}
- Contacto: {MARCA['telefone']}
- Valores: {', '.join(MARCA['valores'])}
- Tom de comunicação: {MARCA['tom']}
- Emojis da marca: {' '.join(MARCA['emojis_marca'])}

REGRAS DE COMUNICAÇÃO:
- Sempre em português europeu (não brasileiro)
- Tom profissional mas acessível e próximo
- Destacar qualidade, confiança e rapidez
- Incluir sempre o contacto quando relevante
- Nunca prometer o que não se pode cumprir
- Adaptar o conteúdo à plataforma pedida

Quando gerares conteúdo, usa ferramentas para estruturar a resposta adequadamente."""


# ─── UI ───────────────────────────────────────────────────────────────────────

def banner() -> None:
    console.print()
    console.print(Panel(
        Text.from_markup(
            f"  [bold {LARANJA}]⬡[/]  [bold white]SUPORTE PRIME[/]"
            f"  [dim {CINZA}]·[/]  [bold {AZUL2}]Agente de Publicidade[/]"
        ),
        border_style=AZUL2,
        padding=(0, 2),
        expand=False,
    ))
    console.print(
        f"  [{CINZA}]Gera posts, campanhas e conteúdo para as redes sociais[/]\n"
    )


def mostrar_conteudo(titulo: str, conteudo: str, plataforma: str = "") -> None:
    sub = f"[{CINZA}]{plataforma}[/]" if plataforma else ""
    console.print()
    console.print(Panel(
        Markdown(conteudo),
        title=f"[bold {LARANJA}]{titulo}[/]",
        subtitle=sub,
        border_style=AZUL2,
        padding=(1, 2),
    ))


def mostrar_assistente(texto: str) -> None:
    if not texto.strip():
        return
    console.print(Panel(
        Markdown(texto),
        title=f"[bold {LARANJA}]◆ Assistente[/]",
        border_style=AZUL2,
        padding=(0, 1),
    ))


def cabecalho(titulo: str) -> None:
    console.print(Rule(f"[bold {LARANJA}]{titulo}[/]", style=AZUL2))


# ─── Ferramentas ──────────────────────────────────────────────────────────────

def _gerar_post(
    plataforma: str,
    servico: str,
    tema: str,
    incluir_cta: bool,
    tom: str,
) -> dict:
    """Estrutura o pedido — o conteúdo real é gerado pelo LLM na resposta."""
    plataformas_config = {
        "instagram": {"max_chars": 2200, "hashtags": True,  "emojis": True},
        "facebook":  {"max_chars": 500,  "hashtags": False, "emojis": True},
        "story":     {"max_chars": 150,  "hashtags": False, "emojis": True},
        "linkedin":  {"max_chars": 700,  "hashtags": True,  "emojis": False},
        "whatsapp":  {"max_chars": 300,  "hashtags": False, "emojis": True},
    }
    cfg = plataformas_config.get(plataforma.lower(), plataformas_config["instagram"])

    return {
        "plataforma": plataforma,
        "servico": servico,
        "tema": tema,
        "tom": tom,
        "incluir_cta": incluir_cta,
        "config": cfg,
        "marca": MARCA,
        "instrucao": (
            f"Gera um post para {plataforma} sobre '{servico}' com tema '{tema}'. "
            f"Tom: {tom}. CTA: {'sim' if incluir_cta else 'não'}. "
            f"Máx {cfg['max_chars']} caracteres. "
            f"{'Com hashtags. ' if cfg['hashtags'] else ''}"
            f"{'Com emojis da marca. ' if cfg['emojis'] else 'Sem emojis.'}"
        ),
    }


def _gerar_campanha(servico: str, epoca: str, num_posts: int) -> dict:
    return {
        "servico": servico,
        "epoca": epoca,
        "num_posts": num_posts,
        "marca": MARCA,
        "instrucao": (
            f"Cria uma campanha de {num_posts} posts para '{servico}' "
            f"adequada à época '{epoca}'. "
            f"Cada post deve ter uma abordagem diferente: problema→solução, "
            f"testemunho fictício, benefício técnico, urgência, confiança."
        ),
    }


def _gerar_mensagem_cliente(
    tipo: str,
    nome_cliente: str,
    servico: str,
    detalhe: str,
) -> dict:
    tipos = {
        "agendamento": "Confirmar agendamento de serviço",
        "conclusao":   "Informar conclusão do serviço",
        "followup":    "Follow-up pós-serviço / pedir avaliação",
        "orcamento":   "Enviar orçamento",
        "lembrete":    "Lembrete de manutenção",
    }
    return {
        "tipo": tipo,
        "descricao_tipo": tipos.get(tipo, tipo),
        "nome_cliente": nome_cliente,
        "servico": servico,
        "detalhe": detalhe,
        "marca": MARCA,
        "instrucao": (
            f"Escreve uma mensagem de WhatsApp para o cliente '{nome_cliente}' "
            f"do tipo '{tipos.get(tipo, tipo)}' relativa a '{servico}'. "
            f"Detalhe adicional: {detalhe}. "
            f"Tom: profissional, cordial, breve. Assinar como Suporte Prime."
        ),
    }


def _gerar_hashtags(servico: str, zona: str) -> dict:
    return {
        "servico": servico,
        "zona": zona,
        "marca": MARCA,
        "instrucao": (
            f"Gera 20-30 hashtags relevantes para posts sobre '{servico}' "
            f"na zona '{zona}' em Portugal. Mistura hashtags de nicho, "
            f"localização e marca. Em português e inglês."
        ),
    }


def _ideias_conteudo(mes: str, num_ideias: int) -> dict:
    return {
        "mes": mes,
        "num_ideias": num_ideias,
        "marca": MARCA,
        "instrucao": (
            f"Gera {num_ideias} ideias de conteúdo para o mês de '{mes}' "
            f"para a Suporte Prime (ar condicionado, instalação, manutenção). "
            f"Para cada ideia: título, plataforma sugerida, tipo de conteúdo "
            f"(post, story, reel, carrossel) e gancho principal."
        ),
    }


# ─── Schema das ferramentas ───────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "gerar_post",
        "description": (
            "Gera um post para redes sociais da Suporte Prime. "
            "Adapta o conteúdo à plataforma (Instagram, Facebook, Story, LinkedIn, WhatsApp)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plataforma": {
                    "type": "string",
                    "enum": ["instagram", "facebook", "story", "linkedin", "whatsapp"],
                    "description": "Plataforma de destino do post.",
                },
                "servico": {
                    "type": "string",
                    "description": "Serviço a promover (ex: 'ar condicionado', 'termoacumulador').",
                },
                "tema": {
                    "type": "string",
                    "description": "Tema ou ângulo do post (ex: 'calor do verão', 'eficiência energética', 'instalação rápida').",
                },
                "incluir_cta": {
                    "type": "boolean",
                    "description": "Incluir chamada para ação (contacto, ligação, mensagem).",
                },
                "tom": {
                    "type": "string",
                    "enum": ["profissional", "urgente", "informativo", "emocional", "promocional"],
                    "description": "Tom da mensagem.",
                },
            },
            "required": ["plataforma", "servico", "tema"],
        },
    },
    {
        "name": "gerar_campanha",
        "description": "Cria uma campanha completa com múltiplos posts para uma época específica.",
        "input_schema": {
            "type": "object",
            "properties": {
                "servico": {"type": "string", "description": "Serviço ou produto a promover."},
                "epoca": {
                    "type": "string",
                    "description": "Época ou contexto (ex: 'verão', 'volta às aulas', 'natal', 'primavera').",
                },
                "num_posts": {
                    "type": "integer",
                    "description": "Número de posts na campanha (1-5).",
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["servico", "epoca"],
        },
    },
    {
        "name": "gerar_mensagem_cliente",
        "description": "Escreve uma mensagem para enviar a um cliente via WhatsApp ou email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {
                    "type": "string",
                    "enum": ["agendamento", "conclusao", "followup", "orcamento", "lembrete"],
                    "description": "Tipo de mensagem.",
                },
                "nome_cliente": {"type": "string", "description": "Nome do cliente."},
                "servico": {"type": "string", "description": "Serviço prestado ou a prestar."},
                "detalhe": {
                    "type": "string",
                    "description": "Informação adicional (data, hora, valor, equipamento, etc.).",
                },
            },
            "required": ["tipo", "servico"],
        },
    },
    {
        "name": "gerar_hashtags",
        "description": "Gera um conjunto de hashtags otimizadas para as redes sociais.",
        "input_schema": {
            "type": "object",
            "properties": {
                "servico": {"type": "string", "description": "Serviço ou tema do post."},
                "zona": {
                    "type": "string",
                    "description": "Zona geográfica (ex: 'Lisboa', 'Sintra', 'Grande Lisboa').",
                },
            },
            "required": ["servico"],
        },
    },
    {
        "name": "ideias_conteudo",
        "description": "Gera ideias de conteúdo para o calendário editorial do mês.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mes": {
                    "type": "string",
                    "description": "Mês (ex: 'junho', 'julho 2026').",
                },
                "num_ideias": {
                    "type": "integer",
                    "description": "Número de ideias a gerar (3-10).",
                    "minimum": 3,
                    "maximum": 10,
                },
            },
            "required": ["mes"],
        },
    },
]


# ─── Execução das ferramentas ─────────────────────────────────────────────────

def executar_ferramenta(nome: str, inputs: dict) -> Any:
    if nome == "gerar_post":
        return _gerar_post(
            plataforma   = inputs.get("plataforma", "instagram"),
            servico      = inputs.get("servico", "ar condicionado"),
            tema         = inputs.get("tema", ""),
            incluir_cta  = inputs.get("incluir_cta", True),
            tom          = inputs.get("tom", "profissional"),
        )
    if nome == "gerar_campanha":
        return _gerar_campanha(
            servico   = inputs.get("servico", "ar condicionado"),
            epoca     = inputs.get("epoca", "verão"),
            num_posts = inputs.get("num_posts", 3),
        )
    if nome == "gerar_mensagem_cliente":
        return _gerar_mensagem_cliente(
            tipo          = inputs.get("tipo", "conclusao"),
            nome_cliente  = inputs.get("nome_cliente", "Cliente"),
            servico       = inputs.get("servico", ""),
            detalhe       = inputs.get("detalhe", ""),
        )
    if nome == "gerar_hashtags":
        return _gerar_hashtags(
            servico = inputs.get("servico", "ar condicionado"),
            zona    = inputs.get("zona", "Lisboa"),
        )
    if nome == "ideias_conteudo":
        return _ideias_conteudo(
            mes       = inputs.get("mes", "junho"),
            num_ideias = inputs.get("num_ideias", 5),
        )
    return {"erro": f"Ferramenta desconhecida: {nome}"}


# ─── Loop principal ───────────────────────────────────────────────────────────

def ajuda() -> None:
    t = Table(box=box.SIMPLE, border_style=AZUL2, show_header=False, padding=(0, 1))
    t.add_column("Pedido", style=f"bold {LARANJA}")
    t.add_column("Exemplo", style=CINZA)
    t.add_row("Post Instagram",  "faz um post de Instagram sobre ar condicionado no verão")
    t.add_row("Post Story",      "cria um story urgente sobre instalação rápida")
    t.add_row("Campanha",        "faz uma campanha de 3 posts para termoacumuladores no inverno")
    t.add_row("Mensagem cliente","escreve mensagem de conclusão de serviço para a Sra. Maria")
    t.add_row("Hashtags",        "gera hashtags para ar condicionado em Sintra")
    t.add_row("Ideias do mês",   "dá-me 5 ideias de conteúdo para julho")
    console.print(t)


def run_agent() -> None:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    messages: list[dict] = []

    banner()
    console.print(f"  [{CINZA}]Digite [bold white]?[/] para ver exemplos · [bold white]sair[/] para encerrar[/]\n")

    while True:
        try:
            user_input = Prompt.ask(f"[bold {LARANJA}]Você[/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n  [{LARANJA}]◆[/] Até logo! — Suporte Prime\n")
            break

        if not user_input:
            continue
        if user_input.lower() in {"sair", "exit", "quit"}:
            console.print(f"\n  [{LARANJA}]◆[/] Até logo! — Suporte Prime\n")
            break
        if user_input == "?":
            ajuda()
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            while True:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=8192,
                    system=[{
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    tools=TOOLS,
                    messages=messages,
                )

                assistant_content: list[dict] = []
                tool_calls: list[dict] = []

                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                        mostrar_assistente(block.text)
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": block.input,
                        })
                        tool_calls.append(block)
                        console.print(
                            f"  [dim {CINZA}]› a gerar:[/] [{LARANJA}]{block.name}[/]"
                        )

                messages.append({"role": "assistant", "content": assistant_content})

                if response.stop_reason != "tool_use" or not tool_calls:
                    break

                tool_results: list[dict] = []
                for call in tool_calls:
                    resultado = executar_ferramenta(call.name, call.input)
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
            console.print(f"  [{LARANJA}]Aviso:[/] limite atingido. Tente novamente.")
            messages.pop()
        except anthropic.APIError as exc:
            console.print(f"  [bold red]Erro da API:[/] {exc}")
            messages.pop()


if __name__ == "__main__":
    run_agent()
