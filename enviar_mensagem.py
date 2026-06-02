"""
Agente Worten — Fecho completo de processos na Worten Resolve

Lê os dados gerados pelo fechar_os.py (pasta Documents/FECHO/{processo}/)
e executa todo o fluxo na Worten:
  1. Justificar check-in (se necessário)
  2. Atualizar Pedido → Concluir Serviço → Serviço Concluído
  3. Preencher Relatório (campos + fotos)
  4. Anexos (upload PDF) → Guardar
  5. Concluir Serviço → Fechar modal
  6. Enviar mensagem fixa ao cliente

Uso:
    python enviar_mensagem.py 3200785 3293728
    python enviar_mensagem.py 3200785 --dry-run   # mostra dados sem agir
"""

import sys
import time
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SERVICOS_URL = "https://www.worten.pt/resolve/servicos"
LOGIN_URL    = "https://www.worten.pt/cliente/conta#/myLogin"
PASTA_FECHO  = Path.home() / "Documents" / "FECHO"

MENSAGEM_CLIENTE = (
    "Caro/a Cliente,\n\n"
    "O serviço de instalação foi concluído. Foi-lhe enviado um sms/e-mail para avaliação, "
    "pedimos a gentileza de responder com base no serviço prestado pelo técnico em sua morada, "
    "pois sua opinião é muito importante para nós.\n\n"
    "Com os melhores cumprimentos."
)


@dataclass
class DadosProcesso:
    numero: str
    pasta: Path
    data_visita: str = ""
    tecnico: str = ""
    trabalhos_realizados: str = ""
    fotos: list = None
    pdf: Optional[Path] = None

    def __post_init__(self):
        if self.fotos is None:
            self.fotos = []


# ──────────────────────────────────────────────
# Leitura de dados do FECHO gerado pelo fechar_os
# ──────────────────────────────────────────────

def carregar_dados(numero: str) -> Optional[DadosProcesso]:
    pasta = PASTA_FECHO / numero
    if not pasta.exists():
        print(f"  [{numero}] AVISO: pasta {pasta} não encontrada — sem dados do AWO")
        return DadosProcesso(numero=numero, pasta=pasta)

    dados = DadosProcesso(numero=numero, pasta=pasta)

    # Lê relatorio.txt
    rel = pasta / "relatorio.txt"
    if rel.exists():
        for linha in rel.read_text(encoding="utf-8").splitlines():
            if linha.startswith("Data visita"):
                dados.data_visita = linha.split(":", 1)[-1].strip()
            elif linha.startswith("Técnico"):
                dados.tecnico = linha.split(":", 1)[-1].strip()
            elif linha.startswith("─") or linha.startswith("Processo") or linha.startswith("Fotos") or linha.startswith("PDF"):
                continue
            elif dados.trabalhos_realizados or linha == "Trabalhos Realizados:":
                if linha == "Trabalhos Realizados:":
                    dados.trabalhos_realizados = ""
                else:
                    dados.trabalhos_realizados += linha + "\n"
        dados.trabalhos_realizados = dados.trabalhos_realizados.strip()

    # Fotos
    dados.fotos = sorted(pasta.glob("foto_*.jpg")) + sorted(pasta.glob("foto_*.png"))

    # PDF
    pdf = pasta / f"{numero}.pdf"
    if pdf.exists():
        dados.pdf = pdf

    return dados


# ──────────────────────────────────────────────
# Helpers Playwright
# ──────────────────────────────────────────────

def clicar_texto(page, *textos, timeout=8000) -> bool:
    for txt in textos:
        try:
            loc = page.locator(f"text={txt}").first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return True
        except Exception:
            continue
    return False


def clicar_botao(page, *textos, timeout=8000) -> bool:
    for txt in textos:
        for sel in [f"button:has-text('{txt}')", f"a:has-text('{txt}')",
                    f"span:has-text('{txt}')", f"[class*='btn']:has-text('{txt}')"]:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=timeout)
                loc.click()
                return True
            except Exception:
                continue
    return False


def selecionar_opcao_dropdown(page, label_texto: str, valor_texto: str) -> bool:
    """Selecciona num dropdown identificado pelo label."""
    try:
        # Tenta encontrar select pelo label
        result = page.evaluate(f"""
            () => {{
                const labelTxt = '{label_texto}'.toLowerCase();
                const valorTxt = '{valor_texto}'.toLowerCase();
                for (const lbl of document.querySelectorAll('label')) {{
                    if (!lbl.textContent.trim().toLowerCase().includes(labelTxt)) continue;
                    const forId = lbl.getAttribute('for');
                    const sel = forId ? document.getElementById(forId)
                                     : lbl.parentElement?.querySelector('select');
                    if (!sel || sel.tagName !== 'SELECT') continue;
                    const opt = Array.from(sel.options).find(o =>
                        o.text.trim().toLowerCase().includes(valorTxt));
                    if (!opt) return 'nenhuma_opcao:' + Array.from(sel.options).map(o => o.text).join('|');
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLSelectElement.prototype, 'value').set;
                    setter.call(sel, opt.value);
                    sel.dispatchEvent(new Event('input',  {{ bubbles: true }}));
                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return 'ok';
                }}
                return 'label_nao_encontrado';
            }}
        """)
        if result == "ok":
            return True
        print(f"    AVISO dropdown '{label_texto}': {result}")
        return False
    except Exception as e:
        print(f"    AVISO dropdown '{label_texto}': {e}")
        return False


def selecionar_radio(page, label_texto: str, valor: str) -> bool:
    """Selecciona radio button / botão com texto próximo de label."""
    try:
        result = page.evaluate(f"""
            () => {{
                const lbl = '{label_texto}'.toLowerCase();
                const val = '{valor}'.toLowerCase();
                // Tenta radio buttons
                for (const inp of document.querySelectorAll('input[type="radio"]')) {{
                    const container = inp.closest('div, fieldset, li');
                    if (!container) continue;
                    const ctxt = container.textContent.toLowerCase();
                    if (ctxt.includes(lbl) && ctxt.includes(val)) {{
                        inp.click();
                        inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return 'ok';
                    }}
                }}
                // Tenta botões com texto
                for (const btn of document.querySelectorAll('button, label, span[role]')) {{
                    const btxt = btn.textContent.trim().toLowerCase();
                    if (btxt.includes(val)) {{
                        const container = btn.closest('div, fieldset, li');
                        if (container && container.textContent.toLowerCase().includes(lbl)) {{
                            btn.click();
                            return 'ok_btn';
                        }}
                    }}
                }}
                return 'nao_encontrado';
            }}
        """)
        return result.startswith("ok")
    except Exception:
        return False


# ──────────────────────────────────────────────
# Login Worten
# ──────────────────────────────────────────────

def aguardar_login_worten(page) -> None:
    print("\n  Abrindo Worten — faça o login MANUALMENTE no navegador.")
    print("  O script continuará automaticamente após o login.\n")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_url(
            lambda u: "myLogin" not in u and "login" not in u.lower(),
            timeout=120000
        )
    except PlaywrightTimeout:
        raise RuntimeError("Tempo esgotado aguardando login na Worten (2 min).")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    print("  Login Worten OK!\n")


# ──────────────────────────────────────────────
# Navegação até ao processo
# ──────────────────────────────────────────────

def abrir_processo(page, numero: str) -> bool:
    print(f"  [{numero}] A pesquisar processo...")
    page.goto(SERVICOS_URL, wait_until="networkidle")
    time.sleep(1)

    # Pesquisar
    for sel in ["input[placeholder*='Pesquisar']", "input[type='search']", "input[placeholder*='pesquisar']"]:
        try:
            campo = page.locator(sel).first
            campo.wait_for(state="visible", timeout=5000)
            campo.fill(numero)
            time.sleep(1500 / 1000)
            break
        except Exception:
            continue

    # Clicar no cartão do processo
    for sel in [f"text=#{numero}", f"text= {numero}"]:
        try:
            card = page.locator(sel).first
            card.wait_for(state="visible", timeout=8000)
            card.click()
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            return True
        except Exception:
            continue

    print(f"  [{numero}] Processo não encontrado na listagem!")
    return False


# ──────────────────────────────────────────────
# Passo 1: Justificar check-in (se presente)
# ──────────────────────────────────────────────

def justificar_checkin(page, dados: DadosProcesso) -> None:
    try:
        btn = page.locator("text=JUSTIFICAR").first
        btn.wait_for(state="visible", timeout=4000)
    except Exception:
        return  # Sem alerta de check-in falhado

    print(f"  [{dados.numero}] Check-in falhado detectado — a justificar...")
    btn.click()
    time.sleep(1)

    # "Sim, efetuei a visita"
    for sel in ["text=Sim, efetuei a visita", "label:has-text('Sim')", "input[value*='sim' i]"]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue

    # Data da visita
    if dados.data_visita:
        for sel in ["input[type='date']", "input[placeholder*='data' i]", "input[placeholder*='Data' i]"]:
            try:
                campo_data = page.locator(sel).first
                campo_data.wait_for(state="visible", timeout=3000)
                campo_data.fill(dados.data_visita)
                break
            except Exception:
                continue

    # Motivo: "Atualizei o pedido ao final do dia"
    for sel in [
        "text=Atualizei o pedido ao final do dia",
        "option:has-text('Atualizei')",
        "label:has-text('Atualizei')"
    ]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue

    # Seleccionar no dropdown se necessário
    selecionar_opcao_dropdown(page, "motivo", "atualizei o pedido ao final do dia")

    time.sleep(500 / 1000)
    clicar_botao(page, "AVANÇAR", "Avançar", "AVANCAR")
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    print(f"  [{dados.numero}] Justificação enviada.")


# ──────────────────────────────────────────────
# Passo 2: Atualizar Pedido → Concluir Serviço
# ──────────────────────────────────────────────

def atualizar_e_concluir(page, numero: str) -> bool:
    print(f"  [{numero}] A clicar em ATUALIZAR PEDIDO...")
    if not clicar_botao(page, "ATUALIZAR PEDIDO", "Atualizar Pedido"):
        print(f"  [{numero}] AVISO: botão ATUALIZAR PEDIDO não encontrado")
        return False
    time.sleep(1500 / 1000)

    # Modal "Qual é o estado do serviço?" → Concluir Serviço
    if not clicar_texto(page, "Concluir Serviço", "CONCLUIR SERVIÇO"):
        print(f"  [{numero}] AVISO: opção 'Concluir Serviço' não encontrada no modal")
        return False
    time.sleep(1)

    # Modal "Confirme a finalização" → Serviço concluído ✓
    for sel in [
        "text=Serviço concluído",
        "label:has-text('Serviço concluído')",
        "text=Marcar pedido como finalizado"
    ]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue
    time.sleep(500 / 1000)

    # Confirmar / Avançar
    clicar_botao(page, "CONFIRMAR", "Confirmar", "AVANÇAR", "Avançar", "OK")
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    print(f"  [{numero}] Pedido atualizado — a avançar para relatório...")
    return True


# ──────────────────────────────────────────────
# Passo 3: Preencher Relatório
# ──────────────────────────────────────────────

def preencher_relatorio(page, dados: DadosProcesso) -> bool:
    print(f"  [{dados.numero}] A preencher relatório...")

    if not clicar_botao(page, "PREENCHER RELATÓRIO", "Preencher Relatório", "PREENCHER RELATORIO"):
        print(f"  [{dados.numero}] AVISO: botão PREENCHER RELATÓRIO não encontrado")
        return False
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # Resultado da Instalação → Instalação Realizada
    selecionar_opcao_dropdown(page, "Resultado", "instalação realizada")
    selecionar_opcao_dropdown(page, "Resultado da Instalação", "instalação realizada")

    # Detalhe Complementar → Equipamento e Instalação com sucesso
    selecionar_opcao_dropdown(page, "Detalhe", "equipamento e instalação com sucesso")
    selecionar_opcao_dropdown(page, "Complementar", "equipamento e instalação com sucesso")

    # Justifique o Fecho → Trabalhos Realizados
    if dados.trabalhos_realizados:
        for sel in [
            "textarea[placeholder*='justif' i]",
            "textarea[placeholder*='descri' i]",
            "textarea",
        ]:
            try:
                ta = page.locator(sel).first
                ta.wait_for(state="visible", timeout=3000)
                ta.fill(dados.trabalhos_realizados)
                break
            except Exception:
                continue

    # Realizou visita → Sim
    selecionar_radio(page, "visita", "sim")
    selecionar_opcao_dropdown(page, "visita", "sim")

    # Orçamento extra → Não
    selecionar_radio(page, "orçamento", "não")
    selecionar_opcao_dropdown(page, "orçamento", "não")

    # Recolha do equipamento → Não
    selecionar_radio(page, "recolha", "não")
    selecionar_opcao_dropdown(page, "recolha", "não")

    # Localização → Na morada do Cliente
    selecionar_opcao_dropdown(page, "localização", "morada do cliente")
    selecionar_opcao_dropdown(page, "Localização", "morada do cliente")

    # Upload fotos
    if dados.fotos:
        print(f"  [{dados.numero}] A fazer upload de {len(dados.fotos)} foto(s)...")
        for sel in [
            "input[type='file']",
            "input[accept*='image']",
        ]:
            try:
                file_input = page.locator(sel).first
                file_input.wait_for(state="attached", timeout=5000)
                file_input.set_input_files([str(f) for f in dados.fotos])
                time.sleep(2)
                break
            except Exception:
                continue

    time.sleep(1)

    # Enviar Relatório
    if not clicar_botao(page, "ENVIAR RELATÓRIO", "Enviar Relatório", "ENVIAR RELATORIO",
                        "CONCLUIR RELATÓRIO", "Concluir Relatório"):
        print(f"  [{dados.numero}] AVISO: botão ENVIAR RELATÓRIO não encontrado")
        return False

    page.wait_for_load_state("networkidle")
    time.sleep(1500 / 1000)
    print(f"  [{dados.numero}] Relatório enviado.")
    return True


# ──────────────────────────────────────────────
# Passo 4: Anexos — upload PDF
# ──────────────────────────────────────────────

def anexar_pdf(page, dados: DadosProcesso) -> bool:
    if not dados.pdf:
        print(f"  [{dados.numero}] AVISO: PDF não encontrado em {dados.pasta} — a saltar anexo")
        return True

    print(f"  [{dados.numero}] A anexar PDF {dados.pdf.name}...")

    # Navegar para aba ANEXOS
    if not clicar_texto(page, "ANEXOS", "Anexos"):
        print(f"  [{dados.numero}] AVISO: aba ANEXOS não encontrada")
        return False
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # Upload
    for sel in ["input[type='file']", "input[accept*='pdf' i]", "input[accept*='application' i]"]:
        try:
            file_input = page.locator(sel).first
            file_input.wait_for(state="attached", timeout=5000)
            file_input.set_input_files(str(dados.pdf))
            time.sleep(2)
            break
        except Exception:
            continue

    # Guardar
    if not clicar_botao(page, "GUARDAR", "Guardar", "SALVAR", "Salvar"):
        print(f"  [{dados.numero}] AVISO: botão GUARDAR não encontrado nos Anexos")
        return False

    page.wait_for_load_state("networkidle")
    time.sleep(1500 / 1000)
    print(f"  [{dados.numero}] PDF anexado e guardado.")
    return True


# ──────────────────────────────────────────────
# Passo 5: Concluir Serviço (2ª vez, após anexos)
# ──────────────────────────────────────────────

def concluir_servico(page, numero: str) -> bool:
    print(f"  [{numero}] A concluir serviço (passo final)...")

    # Voltar ao Estado do Serviço se necessário
    clicar_texto(page, "VER ESTADO DO SERVIÇO", "Estado do Serviço", "ESTADO DO SERVIÇO")
    time.sleep(500 / 1000)

    # ATUALIZAR PEDIDO (2ª vez)
    clicar_botao(page, "ATUALIZAR PEDIDO", "Atualizar Pedido")
    time.sleep(1)

    # Modal: Concluir Serviço
    clicar_texto(page, "Concluir Serviço", "CONCLUIR SERVIÇO")
    time.sleep(1)

    # Serviço concluído ✓
    for sel in [
        "text=Serviço concluído",
        "label:has-text('Serviço concluído')",
        "text=Marcar pedido como finalizado"
    ]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue
    time.sleep(500 / 1000)

    clicar_botao(page, "CONFIRMAR", "Confirmar", "CONCLUIR SERVIÇO", "Concluir Serviço")
    page.wait_for_load_state("networkidle")
    time.sleep(1500 / 1000)

    # Fechar modal "Marcou o serviço como concluído"
    clicar_botao(page, "FECHAR", "Fechar", "OK", "CLOSE")
    time.sleep(1)
    print(f"  [{numero}] Serviço concluído ✓")
    return True


# ──────────────────────────────────────────────
# Passo 6: Enviar mensagem ao cliente
# ──────────────────────────────────────────────

def enviar_mensagem(page, numero: str) -> bool:
    print(f"  [{numero}] A enviar mensagem ao cliente...")

    if not clicar_texto(page, "ENVIAR MENSAGEM AO CLIENTE", "Enviar Mensagem ao Cliente"):
        print(f"  [{numero}] AVISO: botão de mensagem não encontrado")
        return False

    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # Campo de texto
    for sel in [
        "textarea[placeholder*='mensagem' i]",
        "input[placeholder*='mensagem' i]",
        "textarea",
    ]:
        try:
            campo = page.locator(sel).first
            campo.wait_for(state="visible", timeout=8000)
            campo.click()
            campo.fill(MENSAGEM_CLIENTE)
            time.sleep(500 / 1000)
            break
        except Exception:
            continue

    # Botão enviar (seta ▷)
    for sel in [
        "button[type='submit']",
        "button:has(svg)",
        "[aria-label*='enviar' i]",
        "[aria-label*='send' i]",
    ]:
        try:
            btn = page.locator(sel).last
            btn.wait_for(state="visible", timeout=5000)
            btn.click()
            time.sleep(1)
            print(f"  [{numero}] Mensagem enviada ✓")
            return True
        except Exception:
            continue

    print(f"  [{numero}] AVISO: botão de envio não encontrado")
    return False


# ──────────────────────────────────────────────
# Orquestrador principal por processo
# ──────────────────────────────────────────────

def processar_processo(page, numero: str, dry_run: bool) -> str:
    dados = carregar_dados(numero)

    if dry_run:
        print(f"\n  [{numero}] DRY RUN:")
        print(f"    Data visita : {dados.data_visita or '—'}")
        print(f"    Técnico     : {dados.tecnico or '—'}")
        print(f"    Fotos       : {len(dados.fotos)}")
        print(f"    PDF         : {dados.pdf.name if dados.pdf else '—'}")
        print(f"    TR          : {(dados.trabalhos_realizados or '—')[:80]}...")
        return "dry_run"

    try:
        if not abrir_processo(page, numero):
            return "erro:processo_nao_encontrado"

        justificar_checkin(page, dados)

        if not atualizar_e_concluir(page, numero):
            return "erro:atualizar_concluir"

        if not preencher_relatorio(page, dados):
            return "erro:relatorio"

        if not anexar_pdf(page, dados):
            return "erro:anexos"

        if not concluir_servico(page, numero):
            return "erro:concluir"

        enviar_mensagem(page, numero)

        return "ok"

    except Exception as e:
        print(f"  [{numero}] Erro inesperado: {e}")
        try:
            page.screenshot(path=f"debug_{numero}.png")
        except Exception:
            pass
        return f"erro:{e}"


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fecho de processos na Worten Resolve")
    parser.add_argument("processos", nargs="+", help="Números dos processos (ex: 3200785 3293728)")
    parser.add_argument("--dry-run", action="store_true", help="Mostra dados sem executar na Worten")
    args = parser.parse_args()

    print(f"\n=== Worten — Fecho de {len(args.processos)} processo(s) ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=200)
        page    = browser.new_page()

        try:
            if not args.dry_run:
                aguardar_login_worten(page)

            resultados = {"ok": [], "erro": [], "dry_run": []}

            for numero in args.processos:
                numero = numero.strip()
                print(f"\n{'─'*44}")
                estado = processar_processo(page, numero, args.dry_run)
                if estado == "ok":
                    resultados["ok"].append(numero)
                elif estado == "dry_run":
                    resultados["dry_run"].append(numero)
                else:
                    resultados["erro"].append(f"{numero} ({estado})")
                time.sleep(500 / 1000)

            print(f"\n{'='*44}")
            print("       RELATÓRIO FINAL — WORTEN")
            print(f"{'='*44}")
            if args.dry_run:
                print(f"  Para processar : {resultados['dry_run']}")
            else:
                print(f"  Concluídos ✓   : {resultados['ok']}")
                if resultados["erro"]:
                    print(f"  Com erros ✗    : {resultados['erro']}")
            print(f"{'='*44}")

        except RuntimeError as exc:
            print(f"\nErro: {exc}")
            sys.exit(1)
        finally:
            if not args.dry_run:
                print("\n  Pressione Enter para fechar o navegador...")
                input()
            browser.close()


if __name__ == "__main__":
    main()
