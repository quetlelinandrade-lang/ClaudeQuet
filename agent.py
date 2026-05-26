import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
SYSTEM_PROMPT = """Você é um assistente prestativo, direto e honesto.
Responda sempre em português, de forma clara e concisa.
Quando não souber algo, diga claramente."""

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def chat(messages: list) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                # Prompt caching: o system prompt é estável entre turnos,
                # então é cacheado para reduzir custo e latência.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )

    usage = response.usage
    cache_hit = getattr(usage, "cache_read_input_tokens", 0) or 0
    if cache_hit:
        print(f"  [cache: {cache_hit} tokens lidos do cache]\n")

    for block in response.content:
        if block.type == "text":
            return block.text

    return ""


def main() -> None:
    print("=== Assistente Claude ===")
    print("Digite 'sair' ou pressione Ctrl+C para encerrar.\n")

    messages: list = []

    while True:
        try:
            user_input = input("Você: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando. Até logo!")
            break

        if not user_input:
            continue

        if user_input.lower() in {"sair", "exit", "quit"}:
            print("Até logo!")
            break

        messages.append({"role": "user", "content": user_input})

        try:
            reply = chat(messages)
        except anthropic.AuthenticationError:
            print("Erro: chave de API inválida. Verifique o arquivo .env.")
            break
        except anthropic.RateLimitError:
            print("Erro: limite de requisições atingido. Tente novamente em instantes.")
            messages.pop()
            continue
        except anthropic.APIError as exc:
            print(f"Erro da API: {exc}")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})
        print(f"\nAssistente: {reply}\n")


if __name__ == "__main__":
    main()
