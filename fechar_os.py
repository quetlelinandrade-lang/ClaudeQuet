"""
Automação: fecha OS com status "realizado" na plataforma Suporte Prime.

Uso:
    python fechar_os.py            # abre navegador, você faz login, script assume
    python fechar_os.py --dry-run  # apenas lista as OS, sem alterar

A URL da plataforma é lida do arquivo .env:
    PLATFORM_URL=https://suporteprime.awo-soft.com
"""

import os
import sys
import time
import argparse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

URL = os.environ.get("PLATFORM_URL", "https://suporteprime.awo-soft.com")
PLANNING_PATH = "/work-orders/planning"


def aguardar_login(page) -> None:
    print("\n  O navegador vai abrir a página de login.")
    print("  Faça o login MANUALMENTE no navegador.")
    print("  O script continuará automaticamente após o login.\n")

    page.goto(f"{URL}/login")
    page.wait_for_load_state("networkidle")

    # Aguarda até sair da página de login (máx. 3 minutos)
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=180000)
    except PlaywrightTimeout:
        raise RuntimeError("Tempo esgotado. Faça o login em até 3 minutos.")

    page.wait_for_load_state("networkidle")
    print("  Login detectado! Continuando...\n")


def buscar_os_realizadas(page) -> list[dict]:
    print("  Acessando página de planejamento...")
    page.goto(f"{URL}{PLANNING_PATH}")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    os_encontradas = []
    vistos = set()

    cards = page.locator("text=realizado").all()
    print(f"  Elementos com 'realizado' encontrados: {len(cards)}")

    for card in cards:
        try:
            linha = card.locator(
                "xpath=ancestor::tr[1] | ancestor::a[1] | ancestor::div[contains(@class,'card')][1]"
            ).first
            href = linha.get_attribute("href") or ""
            texto = linha.inner_text()[:120].strip().replace("\n", " ")
            chave = href or texto[:40]
            if chave in vistos:
                continue
            vistos.add(chave)
            os_encontradas.append({"elemento": linha, "texto": texto, "href": href})
        except Exception:
            continue

    return os_encontradas


def fechar_os(page, os_item: dict, dry_run: bool) -> bool:
    texto = os_item["texto"]
    href = os_item["href"]

    if dry_run:
        print(f"  [DRY RUN] OS encontrada: {texto[:70]}")
        return False

    print(f"  Abrindo OS: {texto[:70]}...")

    if href and href.startswith("http"):
        page.goto(href)
    elif href:
        page.goto(f"{URL}{href}")
    else:
        try:
            os_item["elemento"].click()
        except Exception as exc:
            print(f"    Não foi possível abrir: {exc}")
            return False

    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # Clica na aba "tipo"
    tipo_selectors = [
        "text=Tipo",
        "text=tipo",
        '[data-tab*="tipo" i]',
        'a:has-text("Tipo")',
        'button:has-text("Tipo")',
    ]
    clicou_tipo = False
    for sel in tipo_selectors:
        try:
            page.click(sel, timeout=4000)
            clicou_tipo = True
            time.sleep(0.8)
            break
        except Exception:
            continue

    if not clicou_tipo:
        print("    Aba 'Tipo' não encontrada.")
        page.screenshot(path=f"debug_tipo_{int(time.time())}.png")
        return False

    # Seleciona "fechado"
    fechado_selectors = [
        ("select_option", "select", "fechado"),
        ("select_option", "select", "Fechado"),
        ("click", "text=Fechado", None),
        ("click", "text=fechado", None),
        ("click", '[value*="fechado" i]', None),
    ]
    selecionou = False
    for tipo, sel, val in fechado_selectors:
        try:
            if tipo == "select_option":
                page.select_option(sel, label=val, timeout=3000)
            else:
                page.click(sel, timeout=3000)
            selecionou = True
            break
        except Exception:
            continue

    if not selecionou:
        print("    Opção 'Fechado' não encontrada.")
        page.screenshot(path=f"debug_fechado_{int(time.time())}.png")
        return False

    # Salva
    salvar_selectors = [
        'button:has-text("Guardar")',
        'button:has-text("Salvar")',
        'button:has-text("Gravar")',
        'button:has-text("Confirmar")',
        'button[type="submit"]',
    ]
    for sel in salvar_selectors:
        try:
            page.click(sel, timeout=4000)
            page.wait_for_load_state("networkidle")
            print("    OS fechada com sucesso.")
            return True
        except Exception:
            continue

    print("    Botão salvar não encontrado.")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Fecha OS com status 'realizado'")
    parser.add_argument("--dry-run", action="store_true", help="Apenas lista as OS, sem alterar")
    args = parser.parse_args()

    modo = "DRY RUN — nenhuma alteração será feita" if args.dry_run else "modo real"
    print(f"\n=== Fechamento de OS ({modo}) ===")

    with sync_playwright() as pw:
        # Sempre abre o navegador visível para o usuário fazer login
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            aguardar_login(page)

            os_list = buscar_os_realizadas(page)

            if not os_list:
                print("  Nenhuma OS com status 'realizado' encontrada.")
            else:
                print(f"  {len(os_list)} OS encontrada(s) com status 'realizado'.\n")
                fechadas = 0
                for os_item in os_list:
                    if fechar_os(page, os_item, dry_run=args.dry_run):
                        fechadas += 1
                    time.sleep(1)

                if not args.dry_run:
                    print(f"\n  Concluído: {fechadas}/{len(os_list)} OS fechada(s).")
                else:
                    print(f"\n  Total encontrado: {len(os_list)} OS.")

        except RuntimeError as exc:
            print(f"\nErro: {exc}")
            sys.exit(1)
        finally:
            print("\n  Pressione Enter para fechar o navegador...")
            input()
            browser.close()


if __name__ == "__main__":
    main()
