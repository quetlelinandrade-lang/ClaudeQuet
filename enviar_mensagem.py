"""
Agente Worten - Envio automático de mensagem ao cliente
Uso: python enviar_mensagem.py 3139910 3293728 ...
"""

import sys
import asyncio
from playwright.async_api import async_playwright

MENSAGEM = """Caro/a Cliente,

O serviço de instalação foi concluído. Foi-lhe enviado um sms/e-mail para avaliação, pedimos a gentileza de responder com base no serviço prestado pelo técnico em sua morada, pois sua opinião é muito importante para nós.

Com os melhores cumprimentos."""

LOGIN_URL = "https://www.worten.pt/cliente/conta#/myLogin"
SERVICOS_URL = "https://www.worten.pt/resolve/servicos"


async def enviar_mensagem_processo(page, numero_processo: str) -> bool:
    print(f"\n[{numero_processo}] A navegar para a lista de serviços...")
    await page.goto(SERVICOS_URL, wait_until="networkidle")

    # Pesquisar processo
    search = page.locator("input[placeholder*='Pesquisar'], input[type='search']").first
    await search.fill(numero_processo)
    await page.wait_for_timeout(1500)

    # Clicar no processo
    processo_card = page.locator(f"text=#{numero_processo}").first
    if not await processo_card.is_visible():
        print(f"[{numero_processo}] Processo não encontrado!")
        return False

    await processo_card.click()
    await page.wait_for_load_state("networkidle")
    print(f"[{numero_processo}] Processo aberto. A abrir chat...")

    # Clicar em "ENVIAR MENSAGEM AO CLIENTE"
    btn_mensagem = page.locator("text=ENVIAR MENSAGEM AO CLIENTE").first
    await btn_mensagem.wait_for(state="visible", timeout=10000)
    await btn_mensagem.click()
    await page.wait_for_load_state("networkidle")

    # Escrever mensagem
    input_msg = page.locator("textarea[placeholder*='mensagem'], input[placeholder*='mensagem']").first
    await input_msg.wait_for(state="visible", timeout=10000)
    await input_msg.click()
    await input_msg.fill(MENSAGEM)
    await page.wait_for_timeout(500)

    # Enviar (botão com seta ▷)
    btn_enviar = page.locator("button[type='submit'], button:has(svg)").last
    await btn_enviar.click()
    await page.wait_for_timeout(1000)

    print(f"[{numero_processo}] Mensagem enviada com sucesso!")
    return True


async def main():
    processos = sys.argv[1:]
    if not processos:
        print("Uso: python enviar_mensagem.py <numero_processo1> [numero_processo2] ...")
        print("Exemplo: python enviar_mensagem.py 3139910 3293728")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=300)
        context = await browser.new_context()
        page = await context.new_page()

        # Login manual
        print("A abrir página de login...")
        print("Por favor, faça login na Worten. O script continuará automaticamente após o login.")
        await page.goto(LOGIN_URL)

        # Aguardar login (detecta redirecionamento após autenticação)
        await page.wait_for_url(
            lambda url: "myLogin" not in url and "conta" in url or "resolve" in url,
            timeout=120000
        )
        print("Login detectado! A iniciar envio de mensagens...")

        resultados = {"sucesso": [], "falha": []}

        for numero in processos:
            numero = numero.strip()
            try:
                ok = await enviar_mensagem_processo(page, numero)
                if ok:
                    resultados["sucesso"].append(numero)
                else:
                    resultados["falha"].append(numero)
            except Exception as e:
                print(f"[{numero}] Erro: {e}")
                resultados["falha"].append(numero)

        print("\n=== RESUMO ===")
        print(f"Enviados com sucesso: {resultados['sucesso']}")
        if resultados["falha"]:
            print(f"Falhas: {resultados['falha']}")

        await page.wait_for_timeout(3000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
