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
from datetime import date, timedelta
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


def navegar_dia_anterior(page) -> None:
    """Clica na seta < para ir ao dia anterior no calendário."""
    try:
        page.click('button:has-text("<"), [aria-label*="anterior" i], [aria-label*="prev" i], [title*="anterior" i]', timeout=3000)
        time.sleep(1)
        page.wait_for_load_state("networkidle")
        return
    except Exception:
        pass

    # Fallback: procura a seta esquerda genérica
    try:
        setas = page.locator("button").all()
        for s in setas:
            txt = (s.inner_text() or "").strip()
            if txt in ("<", "‹", "←", "Anterior", "Previous"):
                s.click()
                time.sleep(1)
                page.wait_for_load_state("networkidle")
                return
    except Exception:
        pass

    print("  Aviso: não foi possível navegar ao dia anterior automaticamente.")


def buscar_os_realizadas(page, dia_anterior: bool = True) -> list[dict]:
    ontem = date.today() - timedelta(days=1)
    label_dia = ontem.strftime("%d/%m/%Y")

    print(f"  Acessando página de planejamento (buscando OS de {label_dia})...")
    page.goto(f"{URL}{PLANNING_PATH}")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Garante vista de Dia (não semana/mês)
    try:
        page.click('button:has-text("Dia")', timeout=3000)
        time.sleep(1)
        page.wait_for_load_state("networkidle")
    except Exception:
        pass

    if dia_anterior:
        navegar_dia_anterior(page)
        print(f"  Calendário navegado para o dia anterior ({label_dia}).")

    time.sleep(1)

    os_encontradas = []
    vistos = set()

    elementos = page.locator("text=realizado").all()
    print(f"  Elementos com 'realizado' encontrados: {len(elementos)}")

    for el in elementos:
        try:
            # Tenta subir até 8 níveis na árvore DOM procurando elemento clicável
            href = ""
            texto = ""
            encontrou = False

            for nivel in range(1, 9):
                xpath = f"xpath=ancestor::*[{nivel}]"
                try:
                    pai = el.locator(xpath).first
                    h = pai.get_attribute("href") or ""
                    t = pai.inner_text()[:120].strip().replace("\n", " ")

                    # Verifica se é um elemento clicável
                    tag = pai.evaluate("el => el.tagName.toLowerCase()")
                    tem_click = pai.get_attribute("onclick") is not None
                    tem_cursor = "pointer" in (pai.evaluate("el => window.getComputedStyle(el).cursor") or "")

                    if tag in ("a", "tr") or tem_click or tem_cursor or h:
                        href = h
                        texto = t
                        encontrou = True
                        break

                    # Para quando o elemento ficou grande demais
                    if len(t) > 300:
                        break
                except Exception:
                    break

            if not encontrou:
                # Usa o próprio elemento se não achou ancestral clicável
                texto = el.inner_text()[:120].strip().replace("\n", " ")
                href = el.get_attribute("href") or ""

            chave = href or texto[:40]
            if chave in vistos or not texto:
                continue
            vistos.add(chave)
            os_encontradas.append({"elemento": el, "texto": texto, "href": href})
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
    ontem = date.today() - timedelta(days=1)

    parser = argparse.ArgumentParser(description="Fecha OS com status 'realizado' do dia anterior")
    parser.add_argument("--dry-run", action="store_true", help="Apenas lista as OS, sem alterar")
    parser.add_argument("--hoje", action="store_true", help="Busca no dia de hoje em vez do dia anterior")
    args = parser.parse_args()

    dia_anterior = not args.hoje
    label_data = ontem.strftime("%d/%m/%Y") if dia_anterior else date.today().strftime("%d/%m/%Y")
    modo = "DRY RUN — nenhuma alteração será feita" if args.dry_run else "modo real"

    print(f"\n=== Fechamento de OS — {label_data} ({modo}) ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            aguardar_login(page)

            os_list = buscar_os_realizadas(page, dia_anterior=dia_anterior)

            if not os_list:
                print(f"  Nenhuma OS com status 'realizado' encontrada em {label_data}.")
            else:
                print(f"  {len(os_list)} OS encontrada(s) com status 'realizado' em {label_data}.\n")
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
