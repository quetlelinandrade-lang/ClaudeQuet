"""
Automação: fecha OS com status "realizado" na plataforma Suporte Prime.

Uso:
    python fechar_os.py               # modo headless (sem janela)
    python fechar_os.py --headful     # abre o navegador visível
    python fechar_os.py --dry-run     # apenas lista as OS, sem alterar

Credenciais lidas do arquivo .env:
    PLATFORM_URL=https://suporteprime.awo-soft.com
    PLATFORM_EMAIL=seu@email.com
    PLATFORM_PASSWORD=suasenha
"""

import os
import sys
import time
import argparse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

URL = os.environ.get("PLATFORM_URL", "https://suporteprime.awo-soft.com")
EMAIL = os.environ.get("PLATFORM_EMAIL", "")
PASSWORD = os.environ.get("PLATFORM_PASSWORD", "")

PLANNING_PATH = "/work-orders/planning"


def login(page) -> None:
    print("  Fazendo login...")
    page.goto(f"{URL}/login")
    page.wait_for_load_state("networkidle")

    # Tenta preencher o campo de email com diferentes seletores
    email_selectors = [
        'input[type="email"]',
        'input[name="email"]',
        'input[placeholder*="mail" i]',
        'input[placeholder*="usuário" i]',
        'input[placeholder*="usuario" i]',
        'input[placeholder*="login" i]',
        'input:visible >> nth=0',
    ]
    for sel in email_selectors:
        try:
            page.fill(sel, EMAIL, timeout=3000)
            print(f"    Campo email encontrado: {sel}")
            break
        except Exception:
            continue
    else:
        raise RuntimeError("Campo de email não encontrado na página de login.")

    # Tenta preencher o campo de senha
    password_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        'input[name="senha"]',
        'input[placeholder*="senha" i]',
        'input[placeholder*="password" i]',
    ]
    for sel in password_selectors:
        try:
            page.fill(sel, PASSWORD, timeout=3000)
            print(f"    Campo senha encontrado: {sel}")
            break
        except Exception:
            continue
    else:
        raise RuntimeError("Campo de senha não encontrado na página de login.")

    # Tenta clicar no botão de login
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Entrar")',
        'button:has-text("Login")',
        'button:has-text("Acessar")',
        'button:has-text("Iniciar")',
    ]
    for sel in submit_selectors:
        try:
            page.click(sel, timeout=3000)
            print(f"    Botão login clicado: {sel}")
            break
        except Exception:
            continue

    url_antes = page.url
    try:
        page.wait_for_url(lambda u: u != url_antes, timeout=10000)
    except PlaywrightTimeout:
        pass

    page.wait_for_load_state("networkidle")
    print(f"    URL após login: {page.url}")

    # Salva screenshot para diagnóstico se ainda estiver na página de login
    if "/login" in page.url:
        page.screenshot(path="login_debug.png")
        raise RuntimeError(
            "Login falhou. Screenshot salvo em login_debug.png — verifique email/senha no .env"
        )

    print("  Login realizado com sucesso.")


def buscar_os_realizadas(page) -> list[dict]:
    """Retorna lista de dicts com {id, titulo, href} das OS com status 'realizado'."""
    print("  Acessando página de planejamento...")
    page.goto(f"{URL}{PLANNING_PATH}")
    page.wait_for_load_state("networkidle")

    os_encontradas = []

    # Estratégia: procura cards/linhas que contenham o texto "realizado"
    # Ajuste o seletor conforme a estrutura real do HTML da plataforma
    cards = page.locator("text=realizado").all()

    for card in cards:
        try:
            # Tenta subir na árvore DOM para encontrar o elemento clicável (link ou linha)
            linha = card.locator("xpath=ancestor::tr[1] | ancestor::a[1] | ancestor::div[contains(@class,'card')][1]").first
            href = linha.get_attribute("href") or ""
            texto = linha.inner_text()[:80].strip().replace("\n", " ")
            os_encontradas.append({"elemento": linha, "texto": texto, "href": href})
        except Exception:
            continue

    return os_encontradas


def fechar_os(page, os_item: dict, dry_run: bool) -> bool:
    """Abre a OS, vai na aba 'tipo' e muda para 'fechado'. Retorna True se alterou."""
    texto = os_item["texto"]
    href = os_item["href"]

    if dry_run:
        print(f"  [DRY RUN] OS encontrada: {texto[:60]}")
        return False

    print(f"  Abrindo OS: {texto[:60]}...")

    # Navega para a OS
    if href and href.startswith("http"):
        page.goto(href)
    elif href:
        page.goto(f"{URL}{href}")
    else:
        try:
            os_item["elemento"].click()
        except Exception as exc:
            print(f"    Não foi possível abrir a OS: {exc}")
            return False

    page.wait_for_load_state("networkidle")

    # Clica na aba "tipo"
    try:
        page.click("text=tipo", timeout=5000)
        time.sleep(0.5)
    except PlaywrightTimeout:
        print("    Aba 'tipo' não encontrada.")
        return False

    # Seleciona "fechado" no campo disponível (select, botão ou radio)
    try:
        # Tenta como <select>
        page.select_option("select", label="fechado", timeout=3000)
    except Exception:
        try:
            # Tenta como botão ou opção clicável
            page.click("text=fechado", timeout=3000)
        except PlaywrightTimeout:
            print("    Opção 'fechado' não encontrada.")
            return False

    # Salva a alteração
    try:
        page.click('button:has-text("salvar"), button:has-text("Salvar"), button[type="submit"]', timeout=5000)
        page.wait_for_load_state("networkidle")
        print("    OS fechada com sucesso.")
        return True
    except PlaywrightTimeout:
        print("    Botão de salvar não encontrado — verifique manualmente.")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Fecha OS com status 'realizado'")
    parser.add_argument("--headful", action="store_true", help="Abre o navegador visível")
    parser.add_argument("--dry-run", action="store_true", help="Apenas lista as OS, sem alterar")
    args = parser.parse_args()

    if not EMAIL or not PASSWORD:
        print("Erro: defina PLATFORM_EMAIL e PLATFORM_PASSWORD no arquivo .env")
        sys.exit(1)

    modo = "DRY RUN — nenhuma alteração será feita" if args.dry_run else "modo real"
    print(f"\n=== Fechamento de OS ({modo}) ===\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        context = browser.new_context()
        page = context.new_page()

        try:
            login(page)
            os_list = buscar_os_realizadas(page)

            if not os_list:
                print("  Nenhuma OS com status 'realizado' encontrada.")
            else:
                print(f"  {len(os_list)} OS encontrada(s) com status 'realizado'.\n")
                fechadas = 0
                for os_item in os_list:
                    if fechar_os(page, os_item, dry_run=args.dry_run):
                        fechadas += 1
                    time.sleep(1)  # pausa entre requisições

                if not args.dry_run:
                    print(f"\n  Concluído: {fechadas}/{len(os_list)} OS fechada(s).")

        except RuntimeError as exc:
            print(f"\nErro: {exc}")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
