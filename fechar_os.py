"""
Automação: fecha OS com status "Realizado" do dia anterior.

Fluxo:
  1. Abre o navegador — você faz login manualmente
  2. Vai para Calendário > vista Dia > dia anterior
  3. Clica em cada bloco de OS do dia
  4. Se Estado = "Realizado" → muda Tipo para "Fechado" → salva

Uso:
    python fechar_os.py            # processa ontem (padrão)
    python fechar_os.py --dry-run  # só lista, sem alterar
    python fechar_os.py --hoje     # processa hoje
    python fechar_os.py --debug    # salva screenshot do calendário e sai
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


# ──────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────

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
    print("  Login OK!\n")


# ──────────────────────────────────────────────
# Navegação para o dia certo
# ──────────────────────────────────────────────

def ir_para_dia_vista(page, alvo: date) -> None:
    """Abre o calendário, ativa vista Dia e navega para a data alvo."""
    print(f"  Abrindo calendário...")
    page.goto(f"{URL}{PLANNING_PATH}")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Ativa vista "Dia"
    for sel in ['button:has-text("Dia")', '[data-view="day"]', '.fc-dayGridDay-button']:
        try:
            page.click(sel, timeout=3000)
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            print("  Vista 'Dia' ativada.")
            break
        except Exception:
            continue

    # Clica o botão "Hoje" para garantir ponto de partida
    try:
        page.click('button:has-text("Hoje")', timeout=3000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
    except Exception:
        pass

    # Navega para a data alvo clicando no botão <
    hoje = date.today()
    passos = (hoje - alvo).days  # positivo = dias para trás
    print(f"  Navegando {passos} dia(s) para trás...")

    for _ in range(passos):
        clicou = False
        # Tenta botões < por texto, aria-label ou classe FC
        for sel in [
            'button:has-text("<")',
            '[aria-label*="anterior" i]',
            '[aria-label*="prev" i]',
            '[title*="anterior" i]',
            '.fc-prev-button',
        ]:
            try:
                page.click(sel, timeout=2000)
                clicou = True
                break
            except Exception:
                continue

        # Fallback: primeiro botão com símbolo de seta
        if not clicou:
            botoes = page.locator("button").all()
            for b in botoes[:10]:
                try:
                    txt = (b.inner_text() or "").strip()
                    if txt in ("<", "‹", "←", "«", "chevron_left", "‹"):
                        b.click()
                        clicou = True
                        break
                except Exception:
                    continue

        time.sleep(0.4)

    page.wait_for_load_state("networkidle")
    time.sleep(1)
    print(f"  Calendário em: {alvo.strftime('%d/%m/%Y')}\n")


# ──────────────────────────────────────────────
# Encontrar eventos do dia
# ──────────────────────────────────────────────

def descobrir_seletor_eventos(page) -> tuple[str, int]:
    """Descobre qual seletor CSS corresponde aos blocos de OS no calendário."""
    result = page.evaluate("""
        () => {
            const candidatos = [
                '.fc-timegrid-event',
                '.fc-event',
                '[class*="fc-event"]',
                '.fc-daygrid-event',
                '[class*="event-item"]',
                '[class*="event-block"]',
                '[class*="work-order"]',
                '[data-event-id]',
                '[data-id]',
            ];
            for (const sel of candidatos) {
                const n = document.querySelectorAll(sel).length;
                if (n > 0) return {sel, n};
            }
            return {sel: null, n: 0};
        }
    """)
    sel = result.get("sel") or ""
    n   = result.get("n") or 0
    return sel, n


# ──────────────────────────────────────────────
# Leitura e edição da OS
# ──────────────────────────────────────────────

def ler_estado(page) -> str:
    """Lê o valor do campo Estado na ficha da OS."""
    # Tenta via select com nome/id "estado"
    for sel in ['select[name*="estado" i]', 'select[id*="estado" i]']:
        try:
            return page.locator(sel).first.input_value(timeout=3000)
        except Exception:
            continue

    # Tenta via label "Estado" → select irmão
    try:
        labels = page.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('label')).map(l => ({
                    text: l.textContent.trim(),
                    for: l.getAttribute('for') || ''
                }));
            }
        """)
        for lbl in labels:
            if "estado" in lbl["text"].lower() and lbl["for"]:
                try:
                    return page.locator(f'#{lbl["for"]}').input_value(timeout=2000)
                except Exception:
                    pass
    except Exception:
        pass

    # Lê o texto visível do primeiro select que contenha "realizado" ou "não realizado"
    try:
        selects = page.locator("select").all()
        for s in selects:
            txt = s.input_value(timeout=1000)
            if txt and ("realiz" in txt.lower() or "não realiz" in txt.lower()):
                return txt
    except Exception:
        pass

    return ""


def alterar_tipo_fechado(page) -> bool:
    """Muda o campo Tipo para 'Fechado'. Retorna True se conseguiu."""
    for sel in ['select[name*="tipo" i]', 'select[id*="tipo" i]']:
        for val in ["Fechado", "fechado", "FECHADO"]:
            try:
                page.select_option(sel, label=val, timeout=3000)
                return True
            except Exception:
                try:
                    page.select_option(sel, value=val, timeout=1000)
                    return True
                except Exception:
                    continue

    # Fallback via label
    try:
        labels = page.evaluate("""
            () => Array.from(document.querySelectorAll('label')).map(l => ({
                text: l.textContent.trim(),
                for: l.getAttribute('for') || ''
            }))
        """)
        for lbl in labels:
            if "tipo" in lbl["text"].lower() and lbl["for"]:
                for val in ["Fechado", "fechado", "FECHADO"]:
                    try:
                        page.select_option(f'#{lbl["for"]}', label=val, timeout=2000)
                        return True
                    except Exception:
                        continue
    except Exception:
        pass
    return False


def salvar(page) -> bool:
    for sel in [
        'button:has-text("Guardar")',
        'button:has-text("Salvar")',
        'button:has-text("Gravar")',
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


# ──────────────────────────────────────────────
# Processamento de cada OS
# ──────────────────────────────────────────────

def processar_os(page, seletor_evento: str, idx: int,
                 url_calendario: str, dry_run: bool) -> str:
    """
    Clica no evento de índice idx, verifica Estado e fecha se necessário.
    Retorna: 'fechada' | 'ignorada' | 'erro'
    """
    # Re-seleciona o evento (DOM pode ter mudado após navegação)
    try:
        evento = page.locator(seletor_evento).nth(idx)
        texto_evento = (evento.inner_text() or "").strip().replace("\n", " ")[:60]
        evento.click(timeout=5000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
    except Exception as e:
        print(f"    [ERRO] não conseguiu clicar no evento {idx}: {e}")
        return "erro"

    if "/login" in page.url:
        return "erro"

    estado = ler_estado(page)
    titulo = texto_evento or page.title()[:50]

    if "realiz" not in estado.lower():
        print(f"    [{estado or '---'}] {titulo} — ignorada")
        page.goto(url_calendario)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return "ignorada"

    print(f"    [Realizado] {titulo}")

    if dry_run:
        page.goto(url_calendario)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return "ignorada"

    if not alterar_tipo_fechado(page):
        print(f"    AVISO: campo Tipo não encontrado — screenshot salvo")
        page.screenshot(path=f"debug_{int(time.time())}.png")
        page.goto(url_calendario)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return "erro"

    if not salvar(page):
        print(f"    AVISO: botão salvar não encontrado")
        page.goto(url_calendario)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return "erro"

    print(f"    ✓ Fechada!")
    page.goto(url_calendario)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    return "fechada"


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Lista sem alterar")
    parser.add_argument("--hoje",    action="store_true", help="Processa hoje")
    parser.add_argument("--debug",   action="store_true", help="Salva screenshot do calendário e sai")
    args = parser.parse_args()

    alvo  = date.today() if args.hoje else date.today() - timedelta(days=1)
    label = alvo.strftime("%d/%m/%Y")
    modo  = "DRY RUN" if args.dry_run else "modo real"

    print(f"\n=== Fechamento de OS — {label} ({modo}) ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page    = browser.new_page()

        try:
            aguardar_login(page)
            ir_para_dia_vista(page, alvo)

            url_calendario = page.url

            # Modo debug: salva screenshot e sai
            if args.debug:
                fname = f"debug_calendario_{alvo.strftime('%Y%m%d')}.png"
                page.screenshot(path=fname, full_page=True)
                sel, n = descobrir_seletor_eventos(page)
                print(f"  Screenshot salvo: {fname}")
                print(f"  Seletor eventos: '{sel}' ({n} encontrados)")
                return

            sel, total = descobrir_seletor_eventos(page)

            if not sel or total == 0:
                # Salva screenshot para diagnóstico
                page.screenshot(path="debug_sem_eventos.png")
                print(f"  Nenhum evento encontrado em {label}.")
                print(f"  Screenshot salvo: debug_sem_eventos.png")
            else:
                print(f"  {total} OS encontradas em {label}. Processando...\n")
                fechadas = ignoradas = erros = 0

                for i in range(total):
                    resultado = processar_os(page, sel, 0, url_calendario, args.dry_run)
                    # Sempre usa índice 0 pois após voltar ao calendário
                    # as OS já processadas são ignoradas pelo Estado

                    if resultado == "fechada":
                        fechadas += 1
                    elif resultado == "erro":
                        erros += 1
                    else:
                        ignoradas += 1

                    # Re-conta eventos restantes
                    _, restantes = descobrir_seletor_eventos(page)
                    if restantes == 0:
                        break
                    time.sleep(0.3)

                print(f"\n  ── Resumo {label} ──")
                print(f"  Fechadas:  {fechadas}")
                print(f"  Ignoradas: {ignoradas}")
                if erros:
                    print(f"  Erros:     {erros} (veja debug_*.png)")

        except RuntimeError as exc:
            print(f"\nErro: {exc}")
            sys.exit(1)
        finally:
            print("\n  Pressione Enter para fechar o navegador...")
            input()
            browser.close()


if __name__ == "__main__":
    main()
