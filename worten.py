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

def justificar_checkin(page: Page, data_visita: str, _hora_visita: str = "") -> bool:
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
    selecionou = False
    for sel in [
        'text="Sim, efetuei a visita"',
        ':text("Sim, efetuei a visita")',
        'label:has-text("Sim, efetuei a visita")',
        'input[type="radio"] >> nth=0',
    ]:
        try:
            page.locator(sel).first.click(timeout=2000, force=True)
            selecionou = True
            print(f"    Radio clicado via: {sel}")
            break
        except Exception:
            continue

    if not selecionou:
        page.evaluate("""
            () => {
                const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
                if (radios.length > 0) { radios[0].click(); return; }
                for (const el of document.querySelectorAll('label, span, div, button, li, p')) {
                    const txt = el.textContent.trim();
                    if (txt === 'Sim, efetuei a visita' || txt.startsWith('Sim,')) {
                        el.click(); return;
                    }
                }
            }
        """)

    time.sleep(2)  # Aguarda modal de data/hora aparecer

    # ── Passo 2: Modal "Selecionar data e hora" ──
    # Verifica se o modal está visível
    modal_visivel = page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('h2, h3, div, span'));
            return els.some(el => el.textContent.trim().toLowerCase().includes('selecionar data'));
        }
    """)

    if modal_visivel:
        print("    Modal de data/hora detectado.")

        # Selecionar o dia correcto (círculos com número do dia)
        if data_visita:
            partes = data_visita.split("/")
            if len(partes) == 3:
                dia = str(int(partes[0]))  # "03" → "3"
                clicou_dia = page.evaluate(f"""
                    () => {{
                        const dia = '{dia}';
                        // Os dias são botões com o número e abreviatura (ex: "Qua\\n03")
                        for (const btn of document.querySelectorAll('button')) {{
                            const txt = btn.textContent.trim();
                            // Último número no texto do botão = dia
                            const m = txt.match(/(\\d{{1,2}})\\s*$/);
                            if (m && m[1] === dia) {{
                                btn.click();
                                return txt;
                            }}
                        }}
                        return false;
                    }}
                """)
                print(f"    Dia clicado: {clicou_dia}")
                time.sleep(0.5)

        # Selecionar slot de hora mais próximo da hora do AWO
        if _hora_visita:
            hora_int = int(_hora_visita.split(":")[0]) if ":" in _hora_visita else 0
            slot = page.evaluate(f"""
                () => {{
                    const hora = {hora_int};
                    for (const btn of document.querySelectorAll('button')) {{
                        const txt = btn.textContent.trim();
                        const m = txt.match(/^(\\d{{1,2}}):(\\d{{2}})\\s*[-–]/);
                        if (m && parseInt(m[1]) === hora) {{
                            btn.click();
                            return txt;
                        }}
                    }}
                    // Fallback: clica no primeiro slot disponível
                    for (const btn of document.querySelectorAll('button')) {{
                        if (/\\d{{1,2}}:\\d{{2}}\\s*[-–]/.test(btn.textContent.trim())) {{
                            btn.click();
                            return 'fallback:' + btn.textContent.trim();
                        }}
                    }}
                    return false;
                }}
            """)
            print(f"    Slot horário: {slot}")
            time.sleep(0.5)

        # Clicar SELECIONAR
        try:
            page.locator('button:has-text("SELECIONAR"), button:has-text("Selecionar")').last.click(timeout=4000)
            time.sleep(1)
            print("    SELECIONAR clicado.")
        except Exception as e:
            print(f"    AVISO: SELECIONAR não encontrado: {e}")
    else:
        print("    Modal de data/hora não detectado — a continuar.")

    # ── Passo 3: Motivo de falha de check-in (lista de radio buttons) ──
    # Opção: "Atualizei o pedido ao final do dia"
    motivo_ok = False
    for sel in [
        'text="Atualizei o pedido ao final do dia"',
        ':text("Atualizei o pedido ao final do dia")',
        'label:has-text("Atualizei o pedido ao final do dia")',
    ]:
        try:
            page.locator(sel).first.click(timeout=3000, force=True)
            motivo_ok = True
            print("    Motivo seleccionado.")
            break
        except Exception:
            continue

    if not motivo_ok:
        page.evaluate("""
            () => {
                for (const el of document.querySelectorAll('label, span, div, li, p')) {
                    if (el.textContent.trim().toLowerCase().includes('atualizei') ||
                        el.textContent.trim().toLowerCase().includes('final do dia')) {
                        el.click(); return;
                    }
                }
                // Tenta radio input ao lado do label
                const radios = document.querySelectorAll('input[type="radio"]');
                if (radios.length >= 2) radios[1].click(); // Segundo radio = "Atualizei..."
            }
        """)

    time.sleep(0.5)

    # ── Passo 4: Clicar AVANÇAR ──
    time.sleep(1)
    try:
        btn = page.locator('button:has-text("AVANÇAR"), button:has-text("Avançar")').first
        btn.click(force=True, timeout=8000)
        time.sleep(2)
        print("    AVANÇAR clicado.")
    except Exception as e:
        print(f"    AVISO: AVANÇAR não encontrado: {e}")
        page.screenshot(path="debug_avancar_falhou.png")
        return False

    return True


# ──────────────────────────────────────────────
# Atualizar pedido e seleccionar "Concluir"
# ──────────────────────────────────────────────

def atualizar_e_concluir(page: Page) -> bool:
    # Aguarda a página estabilizar após AVANÇAR
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    time.sleep(2)

    try:
        page.click(
            'button:has-text("ATUALIZAR PEDIDO"), a:has-text("ATUALIZAR PEDIDO")',
            timeout=10000,
        )
        time.sleep(1)
    except Exception as e:
        print(f"    AVISO: ATUALIZAR PEDIDO não encontrado: {e}")
        page.screenshot(path="debug_atualizar_pedido.png")
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
# Auxiliares de preenchimento de formulário
# ──────────────────────────────────────────────

def _select_opcao(page: Page, label_txt: str, valor: str) -> None:
    """Selecciona uma opção num dropdown próximo de um label com label_txt."""
    result = page.evaluate(f"""
        () => {{
            const label = '{label_txt.lower()}';
            const valor = '{valor.lower()}';
            // Encontra o select mais próximo do label
            for (const el of document.querySelectorAll('label, th, td, div, span, p')) {{
                if (!el.textContent.trim().toLowerCase().includes(label)) continue;
                // Procura select no mesmo container
                const container = el.closest('div, tr, section') || el.parentElement;
                const sel = container ? container.querySelector('select') : null;
                if (!sel) continue;
                for (const o of sel.options) {{
                    if (o.text.toLowerCase().includes(valor) || o.value.toLowerCase().includes(valor)) {{
                        sel.value = o.value;
                        sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return o.text;
                    }}
                }}
            }}
            return false;
        }}
    """)
    if result:
        print(f"    {label_txt}: {result}")


def _preencher_textarea_apos_label(page: Page, label_txt: str, valor: str) -> None:
    """Preenche o textarea mais próximo de um label com label_txt."""
    preenchido = page.evaluate(f"""
        () => {{
            const label = '{label_txt.lower()}';
            for (const el of document.querySelectorAll('label, p, span, div, h3, h4')) {{
                if (!el.textContent.trim().toLowerCase().includes(label)) continue;
                const container = el.closest('div, section') || el.parentElement;
                const ta = container ? container.querySelector('textarea') : null;
                if (ta) {{
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                    setter.call(ta, {repr(valor)});
                    ta.dispatchEvent(new Event('input', {{bubbles: true}}));
                    ta.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }}
            }}
            // Fallback: primeiro textarea visível
            const tas = document.querySelectorAll('textarea');
            if (tas.length) {{
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(tas[0], {repr(valor)});
                tas[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                return 'fallback';
            }}
            return false;
        }}
    """)
    if preenchido:
        print(f"    Textarea '{label_txt}' preenchida.")


def _clicar_botao_junto_label(page: Page, label_txt: str, botao_txt: str) -> None:
    """Clica num botão com botao_txt (Sim/Não) junto de um label com label_txt."""
    clicou = page.evaluate(f"""
        () => {{
            const label = '{label_txt.lower()}';
            const botao = '{botao_txt.lower()}';
            for (const el of document.querySelectorAll('label, p, span, div, h3, h4')) {{
                if (!el.textContent.trim().toLowerCase().includes(label)) continue;
                const container = el.closest('div, section, tr') || el.parentElement;
                if (!container) continue;
                for (const btn of container.querySelectorAll('button')) {{
                    if (btn.textContent.trim().toLowerCase() === botao) {{
                        btn.click();
                        return true;
                    }}
                }}
            }}
            return false;
        }}
    """)
    if clicou:
        print(f"    '{label_txt}' → {botao_txt}")


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

    # ── Resultado da Instalação (dropdown) ──
    _select_opcao(page, "Resultado da Instalação", RESULTADO_INST)

    # ── Detalhe Complementar (dropdown) ──
    _select_opcao(page, "Detalhe Complementar", "[IR] Equipamento e Instalação com sucesso")

    # ── Justifique o resultado → Trabalhos Realizados do AWO ──
    _preencher_textarea_apos_label(page, "Justifique", trabalhos)

    # ── Realizou visita? → Sim (botão toggle) ──
    _clicar_botao_junto_label(page, "Realizou visita", "Sim")

    # ── Houve orçamento extra? → Não (botão toggle) ──
    _clicar_botao_junto_label(page, "orçamento extra", "Não")

    # ── Recolher equipamento? → Não (botão toggle) ──
    _clicar_botao_junto_label(page, "recolher", "Não")

    # ── Localização → Na morada do Cliente (dropdown) ──
    _select_opcao(page, "Localização", LOCALIZACAO)

    # ── Anexar fotografias ──
    fotos_existentes = [str(f) for f in (fotos or []) if Path(f).exists()]
    if fotos_existentes:
        try:
            page.locator('input[type="file"]').first.set_input_files(fotos_existentes)
            print(f"    {len(fotos_existentes)} foto(s) anexada(s)")
            time.sleep(2)
        except Exception as e:
            print(f"    AVISO: upload fotos falhou: {e}")

    # ── Enviar Relatório ──
    try:
        page.click(
            'button:has-text("ENVIAR RELATÓRIO"), button:has-text("Enviar Relatório")',
            timeout=5000,
        )
        time.sleep(2)
        print("    Relatório enviado.")
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
        ta = page.locator("textarea").first
        ta.fill(MSG_CLIENTE)
        time.sleep(0.5)
    except Exception:
        pass

    # O botão de envio é uma seta → tenta vários selectores
    for sel in [
        'button[type="submit"]',
        'button:has-text("Enviar")',
        'button[aria-label*="enviar" i]',
        'button svg',           # botão com ícone de seta
        'form button',
    ]:
        try:
            page.locator(sel).last.click(timeout=3000)
            time.sleep(1)
            print("    Mensagem ao cliente enviada.")
            return True
        except Exception:
            continue

    print("    AVISO: botão enviar mensagem não encontrado")
    return False


# ──────────────────────────────────────────────
# Ponto de entrada público
# ──────────────────────────────────────────────

def processar_os_worten(
    page: Page,
    numero_processo: str,
    data_visita: str,
    hora_visita: str = "",
    trabalhos: str = "",
    fotos: list = None,
    pdf_path=None,
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
        if not justificar_checkin(page, data_visita, hora_visita):
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
