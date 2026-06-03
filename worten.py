"""
Automação Worten — Fecho de OS (segunda fase após AWO)

Fluxo por processo:
  1. Pesquisar número do processo em worten.pt/resolve/servicos
  2. JUSTIFICAR check-in → Sim, efetuei a visita + data + motivo fixo → AVANÇAR
  3. ATUALIZAR PEDIDO → Concluir Serviço → Serviço concluído ✓
  4. PREENCHER RELATÓRIO (campos + fotos) → ENVIAR RELATÓRIO
  5. ANEXOS → upload PDF → GUARDAR
  6. CONCLUIR SERVIÇO → FECHAR modal
  7. ENVIAR MENSAGEM AO CLIENTE (texto fixo)
"""

import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

URL_LOGIN    = "https://www.worten.pt/cliente/conta#/myLogin"
URL_SERVICOS = "https://www.worten.pt/resolve/servicos"

MOTIVO_CHECKIN = "Atualizei o pedido ao final do dia"
RESULTADO_INST = "Instalação Realizada"
DETALHE_INST   = "Equipamento e Instalação com sucesso"
LOCALIZACAO    = "Na morada do Cliente"

MSG_CLIENTE = (
    "Caro/a Cliente,\n"
    "O serviço de instalação foi concluído. Foi-lhe enviado um sms/e-mail para avaliação, "
    "pedimos a gentileza de responder com base no serviço prestado pelo técnico em sua morada, "
    "pois sua opinião é muito importante para nós.\n"
    "Com os melhores cumprimentos."
)


# ──────────────────────────────────────────────
# Login manual Worten
# ──────────────────────────────────────────────

def aguardar_login_worten(page: Page) -> None:
    print("\n  Abrindo Worten — faça o login MANUALMENTE (email + password + reCAPTCHA).")
    print("  O script continua sozinho após o login.\n")
    page.goto(URL_LOGIN)
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_url(
            lambda u: "myLogin" not in u and "/login" not in u.lower(),
            timeout=300_000,
        )
    except PlaywrightTimeout:
        raise RuntimeError("Tempo esgotado aguardando login Worten (5 min).")
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    print("  Login Worten OK!\n")


# ──────────────────────────────────────────────
# Navegar para listagem de serviços
# ──────────────────────────────────────────────

def navegar_para_servicos(page: Page) -> None:
    # Tenta ir directamente; fallback pela navegação manual
    try:
        page.goto(URL_SERVICOS, wait_until="networkidle", timeout=30_000)
        if "resolve/servicos" in page.url:
            return
    except Exception:
        pass

    for sel in ['[aria-label*="Menu" i]', 'button:has-text("Menu")', '.menu-toggle']:
        try:
            page.click(sel, timeout=3000)
            time.sleep(1)
            break
        except Exception:
            continue

    for sel in ['a:has-text("Serviços")', '[href*="servico"]']:
        try:
            page.click(sel, timeout=3000)
            time.sleep(1)
            break
        except Exception:
            continue

    for sel in ['a:has-text("TORNA-TE UM PARCEIRO")', 'a:has-text("Torna-te um parceiro")']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(2)
            break
        except Exception:
            continue


# ──────────────────────────────────────────────
# Pesquisar e abrir processo
# ──────────────────────────────────────────────

def _clicar_resultado(page: Page, numero: str) -> bool:
    for sel in [
        f'a:has-text("{numero}")',
        f'[data-id="{numero}"]',
        f'tr:has-text("{numero}") a',
        ".servico-item",
        ".service-item",
        "tr.service-row",
    ]:
        try:
            page.click(sel, timeout=4000)
            time.sleep(2)
            return True
        except Exception:
            continue
    return False


def pesquisar_processo(page: Page, numero: str) -> bool:
    navegar_para_servicos(page)
    print(f"    Pesquisando processo {numero}...")

    for sel in [
        'input[type="search"]',
        'input[placeholder*="pesquis" i]',
        'input[placeholder*="process" i]',
        'input[placeholder*="número" i]',
        'input[type="text"]',
    ]:
        try:
            field = page.locator(sel).first
            field.fill(numero)
            field.press("Enter")
            time.sleep(2)
            break
        except Exception:
            continue

    if _clicar_resultado(page, numero):
        return True

    print(f"    AVISO: processo {numero} não encontrado na Worten")
    return False


# ──────────────────────────────────────────────
# Justificar check-in
# ──────────────────────────────────────────────

def justificar_checkin(page: Page, data_visita: str) -> bool:
    # O botão JUSTIFICAR só aparece quando há check-in falhado
    try:
        page.click(
            'button:has-text("JUSTIFICAR"), a:has-text("JUSTIFICAR")',
            timeout=6000,
        )
        time.sleep(1.5)
    except Exception:
        return True  # Sem alerta de check-in falhado — continua normalmente

    # ── Passo 1: Seleccionar "Sim, efetuei a visita" ──
    page.screenshot(path="debug_checkin_1_antes_radio.png")
    selecionou = page.evaluate("""
        () => {
            // input[type="radio"] normal
            const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
            if (radios.length > 0) { radios[0].click(); return 'radio-input'; }
            // Elementos com texto "Sim"
            const todos = Array.from(document.querySelectorAll('label, span, div, button, li, p'));
            for (const el of todos) {
                const txt = el.textContent.trim();
                if (txt === 'Sim, efetuei a visita' || txt.startsWith('Sim,') || txt === 'Sim') {
                    el.click();
                    return 'texto:' + txt;
                }
            }
            return false;
        }
    """)
    print(f"    Radio: {selecionou}")
    time.sleep(1.5)  # Aguarda campos adicionais aparecerem

    # ── Passo 2: Preencher data da visita ──
    page.screenshot(path="debug_checkin_2_apos_radio.png")
    if data_visita:
        parts = data_visita.split("/")
        if len(parts) == 3:
            iso = f"{parts[2]}-{parts[1]}-{parts[0]}"
            # Tenta input[type="date"] e input[type="datetime-local"]
            for sel in ['input[type="date"]', 'input[type="datetime-local"]']:
                try:
                    campo = page.locator(sel).first
                    campo.fill(iso)
                    campo.dispatch_event("change")
                    time.sleep(0.5)
                    print(f"    Data preenchida: {iso}")
                    break
                except Exception:
                    continue

    # ── Passo 3: Preencher hora (se existir) ──
    try:
        hora_field = page.locator('input[type="time"]').first
        hora_field.fill("18:00")
        hora_field.dispatch_event("change")
        time.sleep(0.4)
    except Exception:
        pass

    # ── Passo 4: Seleccionar motivo "Atualizei o pedido ao final do dia" ──
    # Pode ser select, input, textarea ou lista de opções clicáveis
    motivo_preenchido = page.evaluate(f"""
        () => {{
            const texto = '{MOTIVO_CHECKIN}';

            // Tenta select
            for (const s of document.querySelectorAll('select')) {{
                for (const o of s.options) {{
                    if (o.text.toLowerCase().includes('atualizei') || o.text.toLowerCase().includes('final')) {{
                        s.value = o.value;
                        s.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return 'select:' + o.text;
                    }}
                }}
            }}

            // Tenta li/div/span clicável com esse texto
            for (const el of document.querySelectorAll('li, div[role="option"], span, button')) {{
                if (el.textContent.trim().toLowerCase().includes('atualizei') ||
                    el.textContent.trim().toLowerCase().includes('final do dia')) {{
                    el.click();
                    return 'opcao:' + el.textContent.trim();
                }}
            }}

            // Tenta textarea ou input de texto
            for (const el of document.querySelectorAll('textarea, input[type="text"]')) {{
                const lbl = el.labels ? Array.from(el.labels).map(l => l.textContent).join(' ').toLowerCase() : '';
                if (lbl.includes('motivo') || lbl.includes('justif') || el.placeholder.toLowerCase().includes('motivo')) {{
                    el.value = texto;
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return 'texto-livre';
                }}
            }}
            return false;
        }}
    """)
    print(f"    Motivo: {motivo_preenchido}")
    time.sleep(1)

    page.screenshot(path="debug_checkin_3_antes_avancar.png")

    # ── Passo 5: Clicar AVANÇAR ──
    time.sleep(1)
    try:
        btn = page.locator('button:has-text("AVANÇAR"), button:has-text("Avançar")').first
        btn.click(force=True, timeout=8000)
        time.sleep(2)
        print("    AVANÇAR clicado.")
    except Exception as e:
        print(f"    AVISO: AVANÇAR não encontrado: {e}")
        page.screenshot(path="debug_checkin_4_avancar_falhou.png")
        return False

    return True


# ──────────────────────────────────────────────
# Atualizar pedido e seleccionar "Concluir"
# ──────────────────────────────────────────────

def atualizar_e_concluir(page: Page) -> bool:
    try:
        page.click(
            'button:has-text("ATUALIZAR PEDIDO"), a:has-text("ATUALIZAR PEDIDO")',
            timeout=8000,
        )
        time.sleep(1)
    except Exception as e:
        print(f"    AVISO: ATUALIZAR PEDIDO não encontrado: {e}")
        return False

    for sel in ['button:has-text("Concluir Serviço")', 'a:has-text("Concluir Serviço")']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(1)
            break
        except Exception:
            continue

    for sel in [
        'button:has-text("Serviço concluído")',
        'label:has-text("Serviço concluído")',
        'input[value*="conclu" i]',
    ]:
        try:
            page.click(sel, timeout=5000)
            time.sleep(1)
            break
        except Exception:
            continue

    return True


# ──────────────────────────────────────────────
# Preencher relatório
# ──────────────────────────────────────────────

def preencher_relatorio(page: Page, trabalhos: str, fotos: list) -> bool:
    try:
        page.click(
            'button:has-text("PREENCHER RELATÓRIO"), a:has-text("PREENCHER RELATÓRIO")',
            timeout=8000,
        )
        time.sleep(1)
    except Exception as e:
        print(f"    AVISO: PREENCHER RELATÓRIO não encontrado: {e}")
        return False

    # Resultado da Instalação
    try:
        page.select_option(
            'select[name*="resultado" i], select[name*="result" i]',
            label=RESULTADO_INST,
            timeout=3000,
        )
    except Exception:
        try:
            page.click(f'option:has-text("{RESULTADO_INST}")', timeout=3000)
        except Exception:
            pass

    # Detalhe
    for sel in ['input[name*="detalhe" i]', 'textarea[name*="detalhe" i]']:
        try:
            page.locator(sel).first.fill(DETALHE_INST)
            break
        except Exception:
            continue

    # Justifique o fecho → Trabalhos Realizados
    preenchido = False
    for sel in [
        'textarea[name*="justif" i]',
        'textarea[name*="descr" i]',
        'textarea[name*="observ" i]',
        'textarea[name*="trabalho" i]',
    ]:
        try:
            page.locator(sel).first.fill(trabalhos)
            preenchido = True
            break
        except Exception:
            continue

    if not preenchido:
        try:
            page.locator("textarea").first.fill(trabalhos)
        except Exception:
            pass

    # Realizou Visita → SIM (radio/select)
    try:
        page.locator('input[type="radio"][value*="sim" i]').first.click(timeout=2000)
    except Exception:
        pass

    # Orçamento Extra → NÃO
    try:
        page.locator('input[type="radio"][value*="nao" i], input[type="radio"][value*="não" i]').nth(0).click(timeout=2000)
    except Exception:
        pass

    # Recolher Equipamento → NÃO
    try:
        page.locator('input[type="radio"][value*="nao" i], input[type="radio"][value*="não" i]').nth(1).click(timeout=2000)
    except Exception:
        pass

    # Localização
    try:
        page.select_option('select[name*="local" i]', label=LOCALIZACAO, timeout=3000)
    except Exception:
        pass

    # Upload fotos
    fotos_existentes = [str(f) for f in fotos if Path(f).exists()]
    if fotos_existentes:
        try:
            page.locator('input[type="file"]').first.set_input_files(fotos_existentes)
            print(f"    {len(fotos_existentes)} foto(s) anexada(s)")
            time.sleep(2)
        except Exception as e:
            print(f"    AVISO: upload fotos falhou: {e}")

    # Enviar relatório
    try:
        page.click(
            'button:has-text("ENVIAR RELATÓRIO"), button:has-text("Enviar Relatório")',
            timeout=5000,
        )
        time.sleep(2)
    except Exception as e:
        print(f"    AVISO: ENVIAR RELATÓRIO não encontrado: {e}")
        return False

    return True


# ──────────────────────────────────────────────
# Anexar PDF da OS
# ──────────────────────────────────────────────

def anexar_pdf(page: Page, pdf_path) -> bool:
    if not pdf_path or not Path(pdf_path).exists():
        print("    AVISO: PDF não encontrado para anexar")
        return False

    for sel in ['a:has-text("ANEXOS")', 'button:has-text("ANEXOS")', '[href*="anex" i]']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(1)
            break
        except Exception:
            continue

    try:
        page.locator('input[type="file"]').last.set_input_files(str(pdf_path))
        print(f"    PDF anexado: {Path(pdf_path).name}")
        time.sleep(2)
    except Exception as e:
        print(f"    AVISO: upload PDF falhou: {e}")
        return False

    try:
        page.click('button:has-text("GUARDAR"), button:has-text("Guardar")', timeout=5000)
        time.sleep(2)
    except Exception as e:
        print(f"    AVISO: GUARDAR não encontrado: {e}")
        return False

    return True


# ──────────────────────────────────────────────
# Concluir serviço (segunda passagem)
# ──────────────────────────────────────────────

def concluir_servico_final(page: Page) -> bool:
    # Após guardar anexos reaparece o banner → segundo ATUALIZAR PEDIDO
    try:
        page.click(
            'button:has-text("ATUALIZAR PEDIDO"), a:has-text("ATUALIZAR PEDIDO")',
            timeout=8000,
        )
        time.sleep(1)
    except Exception:
        pass

    for sel in ['button:has-text("Concluir Serviço")', 'a:has-text("Concluir Serviço")']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(1)
            break
        except Exception:
            continue

    for sel in ['button:has-text("Serviço concluído")', 'label:has-text("Serviço concluído")']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(1)
            break
        except Exception:
            continue

    try:
        page.click(
            'button:has-text("CONCLUIR SERVIÇO"), a:has-text("CONCLUIR SERVIÇO")',
            timeout=8000,
        )
        time.sleep(2)
    except Exception as e:
        print(f"    AVISO: CONCLUIR SERVIÇO não encontrado: {e}")
        return False

    for sel in ['button:has-text("FECHAR")', 'button:has-text("Fechar")']:
        try:
            page.click(sel, timeout=4000)
            time.sleep(1)
            break
        except Exception:
            continue

    return True


# ──────────────────────────────────────────────
# Enviar mensagem ao cliente
# ──────────────────────────────────────────────

def enviar_mensagem_cliente(page: Page) -> bool:
    for sel in [
        'button:has-text("ENVIAR MENSAGEM")',
        'a:has-text("ENVIAR MENSAGEM")',
        'button:has-text("Enviar mensagem")',
    ]:
        try:
            page.click(sel, timeout=5000)
            time.sleep(1)
            break
        except Exception:
            continue
    else:
        return True  # Não crítico

    try:
        page.locator("textarea").first.fill(MSG_CLIENTE)
        time.sleep(0.5)
    except Exception:
        pass

    try:
        page.click('button:has-text("Enviar"), button[type="submit"]', timeout=5000)
        time.sleep(1)
        print("    Mensagem ao cliente enviada.")
    except Exception as e:
        print(f"    AVISO: enviar mensagem falhou: {e}")
        return False

    return True


# ──────────────────────────────────────────────
# Ponto de entrada público
# ──────────────────────────────────────────────

def processar_os_worten(
    page: Page,
    numero_processo: str,
    data_visita: str,
    trabalhos: str,
    fotos: list,
    pdf_path,
) -> bool:
    """Executa o fluxo completo Worten para uma OS. Retorna True se concluído."""
    print(f"\n  [WORTEN] Processo {numero_processo}")

    if not numero_processo:
        print("    ERRO: número de processo vazio — saltando")
        return False

    if not trabalhos:
        print("    INFO: Trabalhos Realizados vazio — saltando na Worten")
        return False

    try:
        if not pesquisar_processo(page, numero_processo):
            return False
        if not justificar_checkin(page, data_visita):
            return False
        if not atualizar_e_concluir(page):
            return False
        if not preencher_relatorio(page, trabalhos, fotos):
            return False
        anexar_pdf(page, pdf_path)         # Não bloqueia se falhar
        if not concluir_servico_final(page):
            return False
        enviar_mensagem_cliente(page)
        print(f"  ✓ Worten: processo {numero_processo} concluído")
        return True

    except Exception as e:
        print(f"  ERRO Worten processo {numero_processo}: {e}")
        return False
