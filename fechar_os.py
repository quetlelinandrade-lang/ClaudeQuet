"""
Automação: fecha OS com status "Realizado" do dia anterior.

Fluxo:
  1. Abre o navegador — você faz login manualmente
  2. Navega para o dia anterior na vista "Dia"
  3. Abre cada OS do dia
  4. Se Estado = "Realizado" → muda Tipo para "Fechado" → salva
  5. Passa para a próxima

Uso:
    python fechar_os.py            # processa o dia anterior (padrão)
    python fechar_os.py --dry-run  # só lista, sem alterar
    python fechar_os.py --hoje     # processa o dia de hoje
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


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def aguardar_login(page) -> None:
    print("\n  Abrindo página de login...")
    print("  Faça o login MANUALMENTE no navegador.")
    print("  O script continua sozinho após o login.\n")

    page.goto(f"{URL}/login")
    page.wait_for_load_state("networkidle")

    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=180000)
    except PlaywrightTimeout:
        raise RuntimeError("Tempo esgotado. Faça login em até 3 minutos.")

    page.wait_for_load_state("networkidle")
    print("  Login detectado! Continuando...\n")


# ---------------------------------------------------------------------------
# Navegação no calendário
# ---------------------------------------------------------------------------

def ir_para_dia(page, alvo: date) -> None:
    """Navega o calendário até a data alvo usando os botões < e >."""
    print(f"  Acessando calendário...")
    page.goto(f"{URL}{PLANNING_PATH}")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Garante vista "Dia"
    try:
        page.click('button:has-text("Dia")', timeout=5000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
    except Exception:
        pass

    hoje = date.today()
    delta = (alvo - hoje).days  # negativo = passado

    if delta == 0:
        print(f"  Já está no dia {alvo.strftime('%d/%m/%Y')}.")
        return

    seta = "button:nth-of-type(1)" if delta < 0 else "button:nth-of-type(2)"

    # Tenta encontrar os botões < e > pelo texto ou posição
    for _ in range(abs(delta)):
        clicou = False
        for sel in ['button:has-text("<")', '[aria-label*="anterior" i]', '[title*="anterior" i]']:
            try:
                if delta < 0:
                    page.click(sel, timeout=2000)
                    clicou = True
                    break
            except Exception:
                continue

        if not clicou:
            # Fallback: primeiro botão de navegação visível
            try:
                botoes = page.locator("button").all()
                for b in botoes:
                    txt = (b.inner_text() or "").strip()
                    if delta < 0 and txt in ("<", "‹", "←", "«"):
                        b.click()
                        clicou = True
                        break
                    if delta > 0 and txt in (">", "›", "→", "»"):
                        b.click()
                        clicou = True
                        break
            except Exception:
                pass

        if not clicou:
            # Último recurso: clica no primeiro/segundo botão da área de navegação
            try:
                idx = 0 if delta < 0 else 1
                page.locator(".fc-prev-button, .fc-next-button, nav button").nth(idx).click(timeout=2000)
            except Exception:
                pass

        time.sleep(0.5)
        page.wait_for_load_state("networkidle")

    print(f"  Calendário em: {alvo.strftime('%d/%m/%Y')}")
    time.sleep(1)


# ---------------------------------------------------------------------------
# Coleta de OS do dia
# ---------------------------------------------------------------------------

def coletar_links_os(page) -> list[str]:
    """Retorna lista de URLs das OS visíveis no dia atual do calendário."""
    time.sleep(2)

    hrefs = set()

    # Busca todos os elementos clicáveis dentro do calendário
    # Os eventos são divs/links coloridos com texto do cliente
    candidatos = page.locator("a[href*='work-order'], a[href*='ordem'], div[data-event], [class*='event'], [class*='fc-event']").all()

    for c in candidatos:
        try:
            h = c.get_attribute("href") or ""
            if h and h not in hrefs:
                hrefs.add(h)
        except Exception:
            continue

    # Fallback: pega todos os links com /work-order ou /ordem na URL
    if not hrefs:
        todos = page.locator("a").all()
        for a in todos:
            try:
                h = a.get_attribute("href") or ""
                if "work-order" in h or "ordem" in h or "order" in h:
                    hrefs.add(h)
            except Exception:
                continue

    print(f"  {len(hrefs)} OS encontradas no calendário.")
    return list(hrefs)


def coletar_eventos_clicaveis(page) -> list:
    """Retorna locators dos blocos de evento no calendário (para clicar)."""
    time.sleep(2)
    seletores = [
        "[class*='fc-event']",
        "[class*='event-item']",
        "[class*='calendar-event']",
        "div[style*='background'][data-id]",
    ]
    for sel in seletores:
        itens = page.locator(sel).all()
        if itens:
            print(f"  {len(itens)} eventos encontrados com seletor '{sel}'.")
            return itens

    print("  Nenhum evento encontrado com seletores padrão.")
    return []


# ---------------------------------------------------------------------------
# Processamento de cada OS
# ---------------------------------------------------------------------------

def ler_estado(page) -> str:
    """Lê o valor atual do campo Estado."""
    seletores = [
        'select[name*="estado" i]',
        'select[id*="estado" i]',
        'select:near(:text("Estado"))',
    ]
    for sel in seletores:
        try:
            val = page.locator(sel).first.input_value(timeout=3000)
            return val
        except Exception:
            continue

    # Tenta pelo texto visível do select
    try:
        labels = page.locator("label").all()
        for label in labels:
            if "estado" in (label.inner_text() or "").lower():
                for_id = label.get_attribute("for") or ""
                if for_id:
                    val = page.locator(f"#{for_id}").input_value(timeout=2000)
                    return val
    except Exception:
        pass

    return ""


def alterar_tipo_para_fechado(page) -> bool:
    """Altera o campo Tipo para 'Fechado'. Retorna True se conseguiu."""
    seletores_tipo = [
        'select[name*="tipo" i]',
        'select[id*="tipo" i]',
    ]

    # Tenta via seletor direto
    for sel in seletores_tipo:
        for valor in ["Fechado", "fechado", "FECHADO"]:
            try:
                page.select_option(sel, label=valor, timeout=3000)
                print("    Campo Tipo → Fechado")
                return True
            except Exception:
                try:
                    page.select_option(sel, value=valor, timeout=2000)
                    print("    Campo Tipo → Fechado")
                    return True
                except Exception:
                    continue

    # Tenta pelo label na página
    try:
        labels = page.locator("label").all()
        for label in labels:
            if "tipo" in (label.inner_text() or "").lower():
                for_id = label.get_attribute("for") or ""
                if for_id:
                    for valor in ["Fechado", "fechado", "FECHADO"]:
                        try:
                            page.select_option(f"#{for_id}", label=valor, timeout=2000)
                            print("    Campo Tipo → Fechado")
                            return True
                        except Exception:
                            continue
    except Exception:
        pass

    return False


def salvar_os(page) -> bool:
    """Clica no botão de salvar. Retorna True se encontrou."""
    for sel in [
        'button:has-text("Guardar")',
        'button:has-text("Salvar")',
        'button:has-text("Gravar")',
        'button:has-text("Confirmar")',
        'button[type="submit"]',
    ]:
        try:
            page.click(sel, timeout=4000)
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            return True
        except Exception:
            continue
    return False


def processar_os_por_url(page, url: str, dry_run: bool) -> str:
    """
    Abre uma OS pela URL, verifica Estado e fecha se necessário.
    Retorna: 'fechada', 'ignorada', 'erro'
    """
    full_url = url if url.startswith("http") else f"{URL}{url}"
    page.goto(full_url)
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    estado = ler_estado(page)
    titulo = page.title() or full_url

    if "realizado" not in estado.lower() and "realizada" not in estado.lower():
        print(f"    [{estado or 'sem estado'}] {titulo[:50]} — ignorada")
        return "ignorada"

    print(f"    [Realizado] {titulo[:50]}")

    if dry_run:
        return "ignorada"

    # Altera Tipo para Fechado
    if not alterar_tipo_para_fechado(page):
        print("    Não encontrou campo Tipo. Screenshot salvo.")
        page.screenshot(path=f"debug_tipo_{int(time.time())}.png")
        return "erro"

    if not salvar_os(page):
        print("    Botão salvar não encontrado.")
        return "erro"

    print("    OS fechada com sucesso!")
    return "fechada"


def processar_os_por_click(page, evento, dry_run: bool, url_calendario: str) -> str:
    """
    Clica em um evento do calendário, verifica Estado e fecha se necessário.
    """
    try:
        evento.click(timeout=5000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
    except Exception as e:
        return "erro"

    if "/login" in page.url:
        return "erro"

    estado = ler_estado(page)
    titulo = page.title() or page.url

    if "realizado" not in estado.lower() and "realizada" not in estado.lower():
        print(f"    [{estado or 'sem estado'}] {titulo[:50]} — ignorada")
        page.go_back()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        return "ignorada"

    print(f"    [Realizado] {titulo[:50]}")

    if dry_run:
        page.go_back()
        page.wait_for_load_state("networkidle")
        return "ignorada"

    if not alterar_tipo_para_fechado(page):
        print("    Não encontrou campo Tipo. Screenshot salvo.")
        page.screenshot(path=f"debug_tipo_{int(time.time())}.png")
        page.go_back()
        page.wait_for_load_state("networkidle")
        return "erro"

    if not salvar_os(page):
        print("    Botão salvar não encontrado.")
        page.go_back()
        page.wait_for_load_state("networkidle")
        return "erro"

    print("    OS fechada com sucesso!")
    # Volta ao calendário
    page.goto(url_calendario)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    return "fechada"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fecha OS 'Realizado' do dia anterior")
    parser.add_argument("--dry-run", action="store_true", help="Apenas lista, sem alterar")
    parser.add_argument("--hoje", action="store_true", help="Processa o dia de hoje")
    args = parser.parse_args()

    alvo = date.today() if args.hoje else date.today() - timedelta(days=1)
    label = alvo.strftime("%d/%m/%Y")
    modo = "DRY RUN" if args.dry_run else "modo real"

    print(f"\n=== Fechamento de OS — {label} ({modo}) ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            aguardar_login(page)
            ir_para_dia(page, alvo)

            url_calendario = page.url

            # Tenta primeiro coletar links diretos das OS
            links = coletar_links_os(page)

            if links:
                print(f"\n  Processando {len(links)} OS via links...\n")
                fechadas = erros = ignoradas = 0
                for link in links:
                    resultado = processar_os_por_url(page, link, dry_run=args.dry_run)
                    if resultado == "fechada":
                        fechadas += 1
                    elif resultado == "erro":
                        erros += 1
                    else:
                        ignoradas += 1
                    time.sleep(0.5)
            else:
                # Fallback: clica em cada evento do calendário
                eventos = coletar_eventos_clicaveis(page)
                if not eventos:
                    print(f"\n  Nenhuma OS encontrada em {label}.")
                else:
                    print(f"\n  Processando {len(eventos)} eventos via clique...\n")
                    fechadas = erros = ignoradas = 0
                    for i in range(len(eventos)):
                        # Re-coleta eventos pois o DOM pode ter mudado
                        eventos_atuais = coletar_eventos_clicaveis(page)
                        if i >= len(eventos_atuais):
                            break
                        resultado = processar_os_por_click(
                            page, eventos_atuais[i], dry_run=args.dry_run,
                            url_calendario=url_calendario
                        )
                        if resultado == "fechada":
                            fechadas += 1
                        elif resultado == "erro":
                            erros += 1
                        else:
                            ignoradas += 1
                        time.sleep(0.5)

            print(f"\n  Resumo {label}:")
            print(f"    Fechadas:  {fechadas}")
            print(f"    Ignoradas: {ignoradas} (Estado ≠ Realizado)")
            if erros:
                print(f"    Erros:     {erros} (verifique screenshots debug_*.png)")

        except RuntimeError as exc:
            print(f"\nErro: {exc}")
            sys.exit(1)
        finally:
            print("\n  Pressione Enter para fechar o navegador...")
            input()
            browser.close()


if __name__ == "__main__":
    main()
