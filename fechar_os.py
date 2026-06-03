"""
Automação AWO + Worten — Fecho completo de OS

Fluxo:
  FASE 1 — AWO
    1. Login manual no AWO (aguarda até 3 minutos)
    2. Calendário do dia anterior → encontra OS com Estado=Realizado
    3. Para cada OS: lê dados, baixa imagens, gera PDF, guarda relatorio.txt, muda Tipo→Fechado

  FASE 2 — Worten (automática, sem digitar números)
    4. Login manual na Worten
    5. Para cada processo fechado no AWO:
       • Justificar check-in (se necessário)
       • Atualizar Pedido → Concluir Serviço
       • Preencher Relatório (campos + fotos)
       • Anexos (PDF) → Guardar
       • Concluir Serviço → Fechar modal
       • Enviar mensagem fixa ao cliente

Estrutura de pastas criada:
    Documents/FECHO/
        {numero_processo}/
            foto_01.jpg  ...
            {numero_processo}.pdf
            relatorio.txt

Uso:
    python fechar_os.py                  # processa ontem (AWO + Worten)
    python fechar_os.py --hoje           # processa hoje
    python fechar_os.py --so-awo         # só fecha no AWO (sem Worten)
    python fechar_os.py --dry-run        # lista sem alterar
    python fechar_os.py --debug          # mostra eventos encontrados e sai
    python fechar_os.py --scan-form /work-orders/edit/XXXXX
"""

import os
import sys
import time
import argparse
import urllib.request
from datetime import date, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

URL_AWO       = os.environ.get("PLATFORM_URL", "https://suporteprime.awo-soft.com")
PLANNING_PATH = "/work-orders/planning"
PASTA_FECHO   = Path.home() / "Documents" / "FECHO"


@dataclass
class DadosOS:
    href: str
    texto: str
    awo_id: str = ""
    numero_processo: str = ""
    data_visita: str = ""
    tecnico: str = ""
    trabalhos_realizados: str = ""
    pasta: Optional[Path] = None
    pdf_path: Optional[Path] = None
    status: str = "pendente"   # pendente | ignorada | ok | erro
    motivo: str = ""


# ──────────────────────────────────────────────
# Login manual AWO
# ──────────────────────────────────────────────

def aguardar_login_awo(page) -> None:
    print("\n  Abrindo AWO — faça o login MANUALMENTE no navegador.")
    print("  O script continua sozinho após o login.\n")
    page.goto(f"{URL_AWO}/login")
    page.wait_for_load_state("domcontentloaded")

    # Espera até 3 minutos pelo login — verifica a cada segundo se saiu do /login
    import time as _time
    for _ in range(180):
        try:
            url_atual = page.url
        except Exception:
            break  # browser fechado — deixa continuar
        if "/login" not in url_atual:
            break
        _time.sleep(1)
    else:
        raise RuntimeError("Tempo esgotado aguardando login no AWO (3 min).")

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    print("  Login AWO OK!\n")


# ──────────────────────────────────────────────
# Navegação para o dia certo
# ──────────────────────────────────────────────

def ir_para_dia_vista(page, alvo: date) -> None:
    print("  Abrindo calendário AWO...")
    page.goto(f"{URL_AWO}{PLANNING_PATH}")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    for sel in ['button:has-text("Dia")', '[data-view="day"]', '.fc-dayGridDay-button']:
        try:
            page.click(sel, timeout=3000)
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            print("  Vista 'Dia' ativada.")
            break
        except Exception:
            continue

    try:
        page.click('button:has-text("Hoje")', timeout=3000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
    except Exception:
        pass

    passos = (date.today() - alvo).days
    print(f"  Navegando {passos} dia(s) para trás...")

    for _ in range(passos):
        clicou = False
        for sel in ['button:has-text("<")', '[aria-label*="anterior" i]',
                    '[aria-label*="prev" i]', '[title*="anterior" i]', '.fc-prev-button']:
            try:
                page.click(sel, timeout=2000)
                clicou = True
                break
            except Exception:
                continue
        if not clicou:
            for b in page.locator("button").all()[:10]:
                try:
                    if (b.inner_text() or "").strip() in ("<", "‹", "←", "«"):
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
# Extração de URLs dos eventos
# ──────────────────────────────────────────────

def extrair_urls_eventos(page, seletor: str) -> list[dict]:
    return page.evaluate(f"""
        () => {{
            const eventos = Array.from(document.querySelectorAll('{seletor}'));
            const vistos = new Set();
            const resultado = [];
            eventos.forEach(e => {{
                const a = e.tagName === 'A' ? e : e.querySelector('a[href]');
                const href = a ? (a.getAttribute('href') || '') : '';
                if (!href || vistos.has(href)) return;
                vistos.add(href);
                const texto = e.textContent.trim().replace(/\\s+/g, ' ').substring(0, 80);
                resultado.push({{ href, texto }});
            }});
            return resultado;
        }}
    """) or []


# ──────────────────────────────────────────────
# Leitura de campos AWO
# ──────────────────────────────────────────────

def ler_select_por_nome_ou_label(page, nome: str) -> str:
    return page.evaluate(f"""
        () => {{
            const nome = '{nome}';
            for (const s of document.querySelectorAll('select')) {{
                const id = (s.name || s.id || '').toLowerCase();
                if (id.includes(nome)) return s.options[s.selectedIndex]?.text || '';
            }}
            for (const lbl of document.querySelectorAll('label')) {{
                if (!lbl.textContent.trim().toLowerCase().startsWith(nome)) continue;
                const forId = lbl.getAttribute('for');
                const s = forId ? document.getElementById(forId)
                                : lbl.parentElement?.querySelector('select');
                if (s?.tagName === 'SELECT') return s.options[s.selectedIndex]?.text || '';
            }}
            return '';
        }}
    """) or ""


def ler_numero_processo(page) -> str:
    valor = page.evaluate("""
        () => {
            for (const el of document.querySelectorAll('input, span, p, td, div')) {
                const v = (el.value || el.textContent || '').trim();
                if (v.includes('/') && /^\\d{5,}/.test(v)) return v;
            }
            return '';
        }
    """) or ""
    if "/" in valor:
        return valor.split("/")[0].strip()
    return valor.strip()


def ler_data_visita(page) -> str:
    valor = page.evaluate("""
        () => {
            for (const lbl of document.querySelectorAll('label')) {
                const txt = lbl.textContent.trim().toLowerCase();
                if (!txt.includes('início') && !txt.includes('inicio') && !txt.includes('data')) continue;
                const forId = lbl.getAttribute('for');
                let el = forId ? document.getElementById(forId)
                               : lbl.parentElement?.querySelector('input, span');
                if (!el) el = lbl.nextElementSibling;
                if (!el) continue;
                const v = (el.value || el.textContent || '').trim();
                if (v) return v;
            }
            const d = document.querySelector('input[type="date"], input[type="datetime-local"]');
            return d ? d.value : '';
        }
    """) or ""
    if "T" in valor:
        valor = valor.split("T")[0]
    if "-" in valor and len(valor) >= 10:
        p = valor[:10].split("-")
        if len(p) == 3:
            return f"{p[2]}/{p[1]}/{p[0]}"
    if " " in valor:
        return valor.split(" ")[0]
    return valor


def ler_trabalhos_realizados(page) -> str:
    return page.evaluate("""
        () => {
            for (const lbl of document.querySelectorAll('label')) {
                const txt = lbl.textContent.trim().toLowerCase();
                if (!txt.includes('trabalhos') && !txt.includes('realizados')) continue;
                const forId = lbl.getAttribute('for');
                let el = forId ? document.getElementById(forId)
                               : lbl.parentElement?.querySelector('textarea, input');
                if (!el) el = lbl.nextElementSibling;
                if (el) return el.value || el.textContent.trim() || '';
            }
            const tas = Array.from(document.querySelectorAll('textarea'));
            if (tas.length) {
                tas.sort((a, b) => b.value.length - a.value.length);
                return tas[0].value || '';
            }
            return '';
        }
    """) or ""


# ──────────────────────────────────────────────
# Download de imagens (aba Imagens/Doc.)
# ──────────────────────────────────────────────

def baixar_imagens(page, pasta: Path) -> int:
    pasta.mkdir(parents=True, exist_ok=True)

    clicou = False
    for tentativa in ['a:has-text("Imagens")', 'a:has-text("Fotos")',
                      '[href*="imagem"]', '[href*="image"]', 'a:has-text("Doc")']:
        try:
            page.click(tentativa, timeout=3000)
            time.sleep(2)
            clicou = True
            break
        except Exception:
            continue

    if not clicou:
        print("    AVISO: aba Imagens/Doc. não encontrada")
        return 0

    img_urls = page.evaluate("""
        () => {
            const vistos = new Set();
            const resultado = [];
            // Palavras que identificam logos/ícones a excluir
            const excluir = ['logo', 'icon', 'favicon', 'avatar', 'brand',
                             'awo', 'awo-soft', 'awosoft', 'placeholder',
                             'sprite', 'thumb_default', 'no-image'];
            for (const img of document.querySelectorAll('img')) {
                const src = img.src || img.getAttribute('data-src') || '';
                if (!src || src.startsWith('data:') || vistos.has(src)) continue;
                // Ignora imagens muito pequenas (logos/ícones)
                if (img.naturalWidth > 0 && img.naturalWidth < 100) continue;
                if (img.naturalHeight > 0 && img.naturalHeight < 100) continue;
                // Ignora por URL (logo AWO e similares)
                const srcLower = src.toLowerCase();
                if (excluir.some(k => srcLower.includes(k))) continue;
                // Ignora imagens quadradas pequenas (logos costumam ser quadradas)
                if (img.naturalWidth > 0 && img.naturalHeight > 0) {
                    const ratio = img.naturalWidth / img.naturalHeight;
                    const area = img.naturalWidth * img.naturalHeight;
                    if (area < 10000 && ratio > 0.8 && ratio < 1.2) continue;
                }
                vistos.add(src);
                resultado.push(src);
            }
            return resultado;
        }
    """) or []

    cookies   = page.context.cookies()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    count = 0

    for i, url in enumerate(img_urls):
        try:
            ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
            if ext not in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
                ext = "jpg"
            dest = pasta / f"foto_{i+1:02d}.{ext}"
            req  = urllib.request.Request(
                url, headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                dest.write_bytes(resp.read())
            count += 1
        except Exception as e:
            print(f"      AVISO: imagem {i+1} não baixada: {e}")

    return count


# ──────────────────────────────────────────────
# Geração de PDF (contexto headless separado)
# ──────────────────────────────────────────────

def gerar_pdf(awo_id: str, pasta: Path, cookies: list, pw) -> Optional[Path]:
    pdf_path  = pasta / f"{pasta.name}.pdf"
    print_url = f"{URL_AWO}/work-orders/print/{awo_id}"
    try:
        pdf_browser = pw.chromium.launch(headless=True)
        ctx         = pdf_browser.new_context()
        ctx.add_cookies(cookies)
        pdf_page    = ctx.new_page()
        pdf_page.goto(print_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        pdf_page.pdf(path=str(pdf_path), format="A4", print_background=True)
        pdf_browser.close()
        print(f"    PDF: {pdf_path.name}")
        return pdf_path
    except Exception as e:
        print(f"    AVISO: PDF não gerado: {e}")
        return None


# ──────────────────────────────────────────────
# Relatório de texto por processo
# ──────────────────────────────────────────────

def gerar_relatorio_txt(dados: "DadosOS", n_fotos: int) -> None:
    if not dados.pasta:
        return
    txt_path = dados.pasta / "relatorio.txt"
    linhas = [
        f"Processo       : {dados.numero_processo}",
        f"Data visita    : {dados.data_visita}",
        f"Técnico        : {dados.tecnico}",
        f"Fotos guardadas: {n_fotos}",
        f"PDF            : {dados.pdf_path.name if dados.pdf_path else 'não gerado'}",
        "",
        "Trabalhos Realizados:",
        "─" * 40,
        dados.trabalhos_realizados or "(não preenchido)",
    ]
    txt_path.write_text("\n".join(linhas), encoding="utf-8")
    print(f"    Relatório: relatorio.txt")


# ──────────────────────────────────────────────
# Alteração Tipo → Fechado (Vue.js compatível)
# ──────────────────────────────────────────────

def alterar_tipo_fechado(page) -> bool:
    resultado = page.evaluate("""
        () => {
            const selects = Array.from(document.querySelectorAll('select'));
            let tipoSelect = null;

            for (const s of selects) {
                const id = (s.name || s.id || '').toLowerCase();
                if (id.includes('tipo') || id.includes('type')) { tipoSelect = s; break; }
            }
            if (!tipoSelect) {
                for (const lbl of document.querySelectorAll('label')) {
                    const txt = lbl.textContent.trim().toLowerCase().replace(/:$/, '');
                    if (txt === 'tipo') {
                        const forId = lbl.getAttribute('for');
                        const s = forId ? document.getElementById(forId)
                                        : lbl.parentElement?.querySelector('select');
                        if (s?.tagName === 'SELECT') { tipoSelect = s; break; }
                    }
                }
            }
            if (!tipoSelect) {
                for (const lbl of document.querySelectorAll('label')) {
                    if (!lbl.textContent.trim().toLowerCase().startsWith('tipo')) continue;
                    const forId = lbl.getAttribute('for');
                    const s = forId ? document.getElementById(forId)
                                    : lbl.parentElement?.querySelector('select');
                    if (s?.tagName === 'SELECT') { tipoSelect = s; break; }
                }
            }
            if (!tipoSelect) {
                return 'erro:nenhum select tipo. Selects: [' +
                    selects.map(s => (s.name||s.id||'?') + '(' +
                        Array.from(s.options).map(o => o.text).slice(0,3).join('|') + ')').join(', ') + ']';
            }

            const opcoes = Array.from(tipoSelect.options);
            const alvo   = opcoes.find(o =>
                o.text.trim().toLowerCase().includes('fechad') ||
                o.value.trim().toLowerCase().includes('fechad')
            );
            if (!alvo) {
                return 'erro:opcao Fechado nao encontrada. Opcoes: ' +
                    opcoes.map(o => '"' + o.text + '"').join(' | ');
            }

            const antes  = tipoSelect.options[tipoSelect.selectedIndex]?.text || '';
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, 'value').set;
            setter.call(tipoSelect, alvo.value);
            tipoSelect.dispatchEvent(new Event('input',  { bubbles: true }));
            tipoSelect.dispatchEvent(new Event('change', { bubbles: true }));
            if (tipoSelect.parentElement)
                tipoSelect.parentElement.dispatchEvent(new Event('change', { bubbles: true }));

            const depois = tipoSelect.options[tipoSelect.selectedIndex]?.text || '';
            if (depois.toLowerCase().includes('fechad'))
                return 'ok:' + antes + ' → ' + depois;
            return 'warn:enviado mas DOM mostra "' + depois + '" (esperado "' + alvo.text + '")';
        }
    """)

    if isinstance(resultado, str) and resultado.startswith("ok:"):
        print(f"    Tipo → {resultado[3:]}")
        return True
    if isinstance(resultado, str) and resultado.startswith("warn:"):
        print(f"    AVISO: {resultado[5:]}")
        return True
    print(f"    FALHA: {resultado}")
    return False


def salvar_awo(page) -> bool:
    time.sleep(1)
    # Tenta pelos textos habituais
    for sel in ['button:has-text("Guardar")', 'button:has-text("Salvar")',
                'button:has-text("Gravar")', 'input[type="submit"]',
                'button[type="submit"]:not([disabled])']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(3)
            return True
        except Exception:
            continue
    # Tenta qualquer botão submit visível
    try:
        btns = page.locator("button[type='submit'], input[type='submit']").all()
        for btn in btns:
            if btn.is_visible():
                btn.click()
                time.sleep(3)
                return True
    except Exception:
        pass
    # Último recurso: Ctrl+S
    try:
        page.keyboard.press("Control+s")
        time.sleep(2)
        return True
    except Exception:
        pass
    return False


# ──────────────────────────────────────────────
# Diagnóstico de formulário
# ──────────────────────────────────────────────

def scan_form(page, url: str) -> None:
    full_url = url if url.startswith("http") else f"{URL_AWO}{url}"
    print(f"\n  Diagnóstico: {full_url}")
    page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)
    info = page.evaluate("""
        () => ({
            selects:   Array.from(document.querySelectorAll('select')).map(s => ({
                name: s.name, id: s.id,
                selected: s.options[s.selectedIndex]?.text || '',
                options: Array.from(s.options).map(o => o.text + '=[' + o.value + ']')
            })),
            inputs:    Array.from(document.querySelectorAll('input:not([type=hidden])')).map(i => ({
                type: i.type, name: i.name, id: i.id, value: i.value
            })),
            textareas: Array.from(document.querySelectorAll('textarea')).map(t => ({
                name: t.name, id: t.id, value: (t.value||'').substring(0, 150)
            })),
            labels:    Array.from(document.querySelectorAll('label')).map(l => ({
                text: l.textContent.trim(), for: l.getAttribute('for')
            }))
        })
    """)
    print("\n=== SELECTS ===")
    for s in info["selects"]:
        print(f"  [{s['name']}|{s['id']}] = '{s['selected']}'")
        for o in s["options"]:
            print(f"      {o}")
    print("\n=== INPUTS ===")
    for i in info["inputs"]:
        print(f"  [{i['type']}] {i['name']}|{i['id']} = {i['value']}")
    print("\n=== TEXTAREAS ===")
    for t in info["textareas"]:
        print(f"  {t['name']}|{t['id']} = '{t['value']}'")
    print("\n=== LABELS ===")
    for l in info["labels"]:
        print(f"  '{l['text']}'  for={l['for']}")


# ──────────────────────────────────────────────
# Processamento de cada OS
# ──────────────────────────────────────────────

def processar_os(page, ev: dict, dry_run: bool, pw) -> DadosOS:
    dados    = DadosOS(href=ev["href"], texto=ev["texto"])
    dados.awo_id = ev["href"].rstrip("/").rsplit("/", 1)[-1]
    full_url = ev["href"] if ev["href"].startswith("http") else f"{URL_AWO}{ev['href']}"
    titulo   = ev["texto"][:60] or ev["href"]

    try:
        page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
    except Exception as e:
        print(f"    [ERRO] {titulo}: {e}")
        dados.status = "erro"
        dados.motivo = str(e)
        return dados

    if "/login" in page.url:
        dados.status = "erro"
        dados.motivo = "redirecionado para login"
        return dados

    estado  = ler_select_por_nome_ou_label(page, "estado")
    tecnico = ler_select_por_nome_ou_label(page, "tipo")
    e       = estado.lower().strip()

    # Ignora se não é Realizado
    if not ("realizado" in e and "não" not in e and "nao" not in e):
        print(f"    [{estado or '---'}] {titulo} — ignorada")
        dados.status = "ignorada"
        return dados

    # Ignora se já está Fechado (evita reprocessar)
    if "fechad" in tecnico.lower():
        print(f"    [Já fechado] {titulo} — ignorada")
        dados.status = "ignorada"
        return dados

    dados.tecnico              = tecnico
    dados.numero_processo      = ler_numero_processo(page)
    dados.data_visita          = ler_data_visita(page)
    dados.trabalhos_realizados = ler_trabalhos_realizados(page)

    print(f"    [PARA FECHAR] Estado={estado} | Técnico={dados.tecnico} | Processo={dados.numero_processo}")

    if not dados.trabalhos_realizados:
        print("    AVISO: campo 'Trabalhos Realizados' vazio")

    if dry_run:
        dados.status = "para_fechar"
        return dados

    # ── Cria pasta e guarda ficheiros ──
    pasta = PASTA_FECHO / (dados.numero_processo or dados.awo_id)
    pasta.mkdir(parents=True, exist_ok=True)
    dados.pasta = pasta

    n_fotos = baixar_imagens(page, pasta)
    print(f"    {n_fotos} foto(s) → {pasta}")

    # Volta à aba Ficha para gerar PDF
    for sel in ['a:has-text("Ficha")', '[href*="ficha"]', 'li:has-text("Ficha") a']:
        try:
            page.click(sel, timeout=3000)
            time.sleep(1)
            break
        except Exception:
            continue

    dados.pdf_path = gerar_pdf(dados.awo_id, pasta, page.context.cookies(), pw)
    gerar_relatorio_txt(dados, n_fotos)

    # ── Muda Tipo → Fechado ──
    if not alterar_tipo_fechado(page):
        page.screenshot(path=f"debug_tipo_{dados.awo_id}.png")
        dados.status = "erro"
        dados.motivo = "alterar_tipo_fechado falhou"
        return dados

    if not salvar_awo(page):
        print("    AVISO: botão guardar não encontrado — Tipo já alterado, continua para Worten")
        page.screenshot(path=f"debug_salvar_{dados.awo_id}.png")
        # Não bloqueia: o tipo Vue.js já foi alterado, segue para Worten mesmo assim
    else:
        print(f"    ✓ Guardado no AWO")

    print(f"    ✓ OS {dados.numero_processo} pronta para Worten")
    dados.status = "ok"
    return dados


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# FASE 2 — Worten: funções de automação
# ──────────────────────────────────────────────

SERVICOS_URL     = "https://www.worten.pt/resolve/servicos"
WORTEN_LOGIN_URL = "https://www.worten.pt/cliente/conta#/myLogin"

MENSAGEM_CLIENTE = (
    "Caro/a Cliente,\n\n"
    "O serviço de instalação foi concluído. Foi-lhe enviado um sms/e-mail para avaliação, "
    "pedimos a gentileza de responder com base no serviço prestado pelo técnico em sua morada, "
    "pois sua opinião é muito importante para nós.\n\n"
    "Com os melhores cumprimentos."
)


def aguardar_login_worten(page) -> None:
    print("\n  ── FASE 2: Worten ──")
    print("  Abrindo Worten — faça o login MANUALMENTE no navegador.")
    print("  O script continuará automaticamente após o login.\n")
    page.goto(WORTEN_LOGIN_URL, wait_until="domcontentloaded")
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
    print("  Login Worten OK! A navegar para os serviços...")
    # Navega pelo menu logo após o login
    _navegar_para_listagem(page)
    print("  Listagem de serviços carregada.\n")


def _clicar_botao_w(page, *textos, timeout=8000) -> bool:
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


def _clicar_texto_w(page, *textos, timeout=8000) -> bool:
    for txt in textos:
        try:
            loc = page.locator(f"text={txt}").first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return True
        except Exception:
            continue
    return False


def _selecionar_dropdown_w(page, label_txt: str, valor_txt: str) -> bool:
    try:
        result = page.evaluate(f"""
            () => {{
                const lbl = '{label_txt}'.toLowerCase();
                const val = '{valor_txt}'.toLowerCase();
                for (const el of document.querySelectorAll('label')) {{
                    if (!el.textContent.trim().toLowerCase().includes(lbl)) continue;
                    const forId = el.getAttribute('for');
                    const sel = forId ? document.getElementById(forId)
                                     : el.parentElement?.querySelector('select');
                    if (!sel || sel.tagName !== 'SELECT') continue;
                    const opt = Array.from(sel.options).find(o =>
                        o.text.trim().toLowerCase().includes(val));
                    if (!opt) return 'nenhuma_opcao';
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
        return result == "ok"
    except Exception:
        return False


def _navegar_para_listagem(page) -> bool:
    """Navega para worten.pt/resolve/servicos pelo caminho correcto do menu."""
    print("    Worten: worten.pt → Menu → Serviços → Torna-te Parceiro...")

    # 1. Ir para worten.pt
    try:
        page.goto("https://www.worten.pt/", wait_until="networkidle", timeout=20000)
    except Exception:
        page.goto("https://www.worten.pt/")
    time.sleep(2)

    # 2. Clicar em Menu (hambúrguer)
    clicou_menu = False
    for sel in ["button:has-text('Menu')", "text=☰ Menu", "text=Menu",
                "[aria-label*='menu' i]", "nav button", ".hamburger"]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click()
                time.sleep(1.5)
                clicou_menu = True
                break
        except Exception:
            continue
    if not clicou_menu:
        print("    AVISO: botão Menu não encontrado — tenta URL directo")
        page.goto(SERVICOS_URL, wait_until="networkidle", timeout=20000)
        time.sleep(3)
        try:
            page.locator("input[placeholder*='Pesquisar'], input[type='search']").first.wait_for(
                state="visible", timeout=8000)
            return True
        except Exception:
            return False

    # 3. Clicar em Serviços no menu lateral
    clicou_servicos = False
    for sel in ["text=Serviços", "a:has-text('Serviços')", "li:has-text('Serviços') a"]:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=5000)
            loc.click()
            time.sleep(1.5)
            clicou_servicos = True
            break
        except Exception:
            continue
    if not clicou_servicos:
        print("    AVISO: item Serviços não encontrado no menu")

    # 4. Clicar em Torna-te Parceiro / Torna-te um Parceiro
    clicou_parceiro = False
    for sel in ["text=Torna-te Parceiro", "text=TORNA-TE PARCEIRO",
                "text=Torna-te um Parceiro", "a:has-text('Parceiro')",
                "a:has-text('parceiro')"]:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=5000)
            loc.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(2)
            clicou_parceiro = True
            break
        except Exception:
            continue
    if not clicou_parceiro:
        print("    AVISO: Torna-te Parceiro não encontrado — navega directamente")
        page.goto(SERVICOS_URL, wait_until="networkidle", timeout=20000)
        time.sleep(3)

    print(f"    URL actual: {page.url}")

    # 5. Verifica se a listagem está carregada
    try:
        page.locator("input[placeholder*='Pesquisar'], input[type='search'], "
                     "input[placeholder*='pesquisar']").first.wait_for(
            state="visible", timeout=10000)
        print("    Campo de pesquisa encontrado ✓")
        return True
    except Exception:
        print("    ERRO: campo de pesquisa não encontrado na listagem")
        page.screenshot(path="debug_listagem_worten.png")
        return False


def _abrir_processo_worten(page, numero: str) -> bool:
    if not _navegar_para_listagem(page):
        print(f"    ERRO: não foi possível carregar a listagem de serviços")
        return False

    # Pesquisar processo
    for sel in ["input[placeholder*='Pesquisar']", "input[type='search']",
                "input[placeholder*='pesquisar']"]:
        try:
            campo = page.locator(sel).first
            campo.wait_for(state="visible", timeout=5000)
            campo.clear()
            campo.fill(numero)
            time.sleep(2)
            break
        except Exception:
            continue

    # Clicar no cartão do processo
    for sel in [f"text=#{numero}", f":text('#{numero}')"]:
        try:
            card = page.locator(sel).first
            card.wait_for(state="visible", timeout=8000)
            card.click()
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            return True
        except Exception:
            continue
    return False


def _justificar_checkin_w(page, dados: DadosOS) -> None:
    try:
        page.locator("text=JUSTIFICAR").first.wait_for(state="visible", timeout=4000)
    except Exception:
        return
    print(f"    Check-in falhado — a justificar...")
    page.locator("text=JUSTIFICAR").first.click()
    time.sleep(1)
    for sel in ["text=Sim, efetuei a visita", "label:has-text('Sim')"]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue
    if dados.data_visita:
        for sel in ["input[type='date']", "input[placeholder*='data' i]"]:
            try:
                page.locator(sel).first.fill(dados.data_visita)
                break
            except Exception:
                continue
    _selecionar_dropdown_w(page, "motivo", "atualizei o pedido ao final do dia")
    for sel in ["text=Atualizei o pedido ao final do dia", "label:has-text('Atualizei')"]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue
    time.sleep(0.5)
    _clicar_botao_w(page, "AVANÇAR", "Avançar")
    page.wait_for_load_state("networkidle")
    time.sleep(1)


def _atualizar_e_concluir_w(page, numero: str) -> bool:
    if not _clicar_botao_w(page, "ATUALIZAR PEDIDO", "Atualizar Pedido"):
        return False
    time.sleep(1.5)
    if not _clicar_texto_w(page, "Concluir Serviço", "CONCLUIR SERVIÇO"):
        return False
    time.sleep(1)
    for sel in ["text=Serviço concluído", "label:has-text('Serviço concluído')",
                "text=Marcar pedido como finalizado"]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue
    time.sleep(0.5)
    _clicar_botao_w(page, "CONFIRMAR", "Confirmar", "AVANÇAR", "Avançar", "OK")
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    return True


def _preencher_relatorio_w(page, dados: DadosOS) -> bool:
    if not _clicar_botao_w(page, "PREENCHER RELATÓRIO", "Preencher Relatório",
                           "PREENCHER RELATORIO"):
        return False
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    _selecionar_dropdown_w(page, "Resultado", "instalação realizada")
    _selecionar_dropdown_w(page, "Resultado da Instalação", "instalação realizada")
    _selecionar_dropdown_w(page, "Detalhe", "equipamento e instalação com sucesso")
    _selecionar_dropdown_w(page, "Complementar", "equipamento e instalação com sucesso")

    if dados.trabalhos_realizados:
        for sel in ["textarea[placeholder*='justif' i]", "textarea[placeholder*='descri' i]",
                    "textarea"]:
            try:
                ta = page.locator(sel).first
                ta.wait_for(state="visible", timeout=3000)
                ta.fill(dados.trabalhos_realizados)
                break
            except Exception:
                continue

    _selecionar_dropdown_w(page, "visita", "sim")
    _selecionar_dropdown_w(page, "orçamento", "não")
    _selecionar_dropdown_w(page, "recolha", "não")
    _selecionar_dropdown_w(page, "localização", "morada do cliente")
    _selecionar_dropdown_w(page, "Localização", "morada do cliente")

    # Upload fotos
    if dados.pasta:
        fotos = sorted(dados.pasta.glob("foto_*.jpg")) + sorted(dados.pasta.glob("foto_*.png"))
        if fotos:
            print(f"    Upload de {len(fotos)} foto(s)...")
            for sel in ["input[type='file']", "input[accept*='image']"]:
                try:
                    fi = page.locator(sel).first
                    fi.wait_for(state="attached", timeout=5000)
                    fi.set_input_files([str(f) for f in fotos])
                    time.sleep(2)
                    break
                except Exception:
                    continue

    time.sleep(1)
    if not _clicar_botao_w(page, "ENVIAR RELATÓRIO", "Enviar Relatório",
                           "CONCLUIR RELATÓRIO", "Concluir Relatório"):
        return False
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)
    return True


def _anexar_pdf_w(page, dados: DadosOS) -> bool:
    if not dados.pdf_path:
        return True
    if not _clicar_texto_w(page, "ANEXOS", "Anexos"):
        return False
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    for sel in ["input[type='file']", "input[accept*='pdf' i]"]:
        try:
            fi = page.locator(sel).first
            fi.wait_for(state="attached", timeout=5000)
            fi.set_input_files(str(dados.pdf_path))
            time.sleep(2)
            break
        except Exception:
            continue
    if not _clicar_botao_w(page, "GUARDAR", "Guardar"):
        return False
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)
    return True


def _concluir_servico_w(page) -> None:
    _clicar_texto_w(page, "VER ESTADO DO SERVIÇO", "Estado do Serviço", timeout=3000)
    time.sleep(0.5)
    _clicar_botao_w(page, "ATUALIZAR PEDIDO", "Atualizar Pedido")
    time.sleep(1)
    _clicar_texto_w(page, "Concluir Serviço", "CONCLUIR SERVIÇO")
    time.sleep(1)
    for sel in ["text=Serviço concluído", "label:has-text('Serviço concluído')",
                "text=Marcar pedido como finalizado"]:
        try:
            page.locator(sel).first.click()
            break
        except Exception:
            continue
    time.sleep(0.5)
    _clicar_botao_w(page, "CONFIRMAR", "Confirmar", "CONCLUIR SERVIÇO", "Concluir Serviço")
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)
    _clicar_botao_w(page, "FECHAR", "Fechar", "OK")
    time.sleep(1)


def _enviar_mensagem_w(page, numero: str) -> None:
    if not _clicar_texto_w(page, "ENVIAR MENSAGEM AO CLIENTE", "Enviar Mensagem ao Cliente"):
        print(f"    AVISO: botão de mensagem não encontrado")
        return
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    for sel in ["textarea[placeholder*='mensagem' i]", "input[placeholder*='mensagem' i]",
                "textarea"]:
        try:
            campo = page.locator(sel).first
            campo.wait_for(state="visible", timeout=8000)
            campo.fill(MENSAGEM_CLIENTE)
            time.sleep(0.5)
            break
        except Exception:
            continue
    for sel in ["button[type='submit']", "button:has(svg)", "[aria-label*='enviar' i]"]:
        try:
            page.locator(sel).last.click()
            time.sleep(1)
            break
        except Exception:
            continue


def fechar_na_worten(page, dados: DadosOS) -> str:
    numero = dados.numero_processo
    if not numero:
        return "ignorado:sem_numero"
    print(f"\n  [{numero}] A fechar na Worten...")
    try:
        if not _abrir_processo_worten(page, numero):
            return "erro:processo_nao_encontrado"
        _justificar_checkin_w(page, dados)
        if not _atualizar_e_concluir_w(page, numero):
            return "erro:atualizar_concluir"
        if not _preencher_relatorio_w(page, dados):
            return "erro:relatorio"
        if not _anexar_pdf_w(page, dados):
            return "erro:anexos"
        _concluir_servico_w(page)
        _enviar_mensagem_w(page, numero)
        print(f"  [{numero}] ✓ Processo fechado na Worten + mensagem enviada")
        return "ok"
    except Exception as e:
        print(f"  [{numero}] Erro Worten: {e}")
        try:
            page.screenshot(path=f"debug_worten_{numero}.png")
        except Exception:
            pass
        return f"erro:{e}"


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fecho automático de OS no AWO + Worten")
    parser.add_argument("--dry-run",   action="store_true", help="Lista sem alterar")
    parser.add_argument("--hoje",      action="store_true", help="Processa hoje (padrão: ontem)")
    parser.add_argument("--debug",     action="store_true", help="Mostra eventos e sai")
    parser.add_argument("--so-awo",    action="store_true", help="Só fecha no AWO (sem Worten)")
    parser.add_argument("--scan-form", metavar="URL",       help="Diagnóstico de formulário AWO")
    args = parser.parse_args()

    alvo  = date.today() if args.hoje else date.today() - timedelta(days=1)
    label = alvo.strftime("%d/%m/%Y")
    modo  = "DRY RUN" if args.dry_run else ("SÓ AWO" if args.so_awo else "AWO + WORTEN")

    print(f"\n=== Fechar OS — {label} ({modo}) ===")
    PASTA_FECHO.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page    = browser.new_page()

        try:
            aguardar_login_awo(page)

            if args.scan_form:
                scan_form(page, args.scan_form)
                return

            ir_para_dia_vista(page, alvo)

            if args.debug:
                n       = page.evaluate("() => document.querySelectorAll('.fc-event').length")
                eventos = extrair_urls_eventos(page, ".fc-event")
                print(f"  .fc-event: {n} | URLs: {len(eventos)}")
                for ev in eventos[:10]:
                    print(f"    {ev['href']}  →  {ev['texto'][:50]}")
                return

            seletor = page.evaluate("""
                () => {
                    for (const s of ['.fc-timegrid-event', '.fc-event', '[class*="fc-event"]']) {
                        if (document.querySelectorAll(s).length > 0) return s;
                    }
                    return null;
                }
            """)

            if not seletor:
                page.screenshot(path="debug_sem_eventos.png")
                print(f"  Nenhum evento encontrado em {label}.")
                return

            eventos = extrair_urls_eventos(page, seletor)
            if not eventos:
                print("  Eventos encontrados mas sem URLs — use --debug para inspecionar.")
                return

            print(f"  {len(eventos)} OS encontradas em {label}. Processando AWO...\n")

            lista: list[DadosOS] = []
            for ev in eventos:
                d = processar_os(page, ev, args.dry_run, pw)
                lista.append(d)
                time.sleep(0.3)

            fechadas  = [d for d in lista if d.status == "ok"]
            dry_list  = [d for d in lista if d.status == "para_fechar"]
            ignoradas = [d for d in lista if d.status == "ignorada"]
            erros_awo = [d for d in lista if d.status == "erro"]

            print(f"\n{'='*44}")
            print("         RELATÓRIO — AWO")
            print(f"{'='*44}")
            print(f"  Data           : {label}")
            if args.dry_run:
                print(f"  Para fechar    : {len(dry_list)}")
                for d in dry_list:
                    print(f"    • {d.numero_processo or d.texto[:40]} | {d.tecnico}")
                print(f"{'='*44}")
                return
            else:
                print(f"  Fechadas ✓     : {len(fechadas)}")
                print(f"  Ignoradas      : {len(ignoradas)}")
                if erros_awo:
                    print(f"  Erros          : {len(erros_awo)}")
                    for d in erros_awo:
                        print(f"    ✗ {d.numero_processo or d.texto[:40]} → {d.motivo}")
                print(f"  Pasta: {PASTA_FECHO}")
            print(f"{'='*44}")

            # ── FASE 2: Worten ──
            processos_para_worten = [d for d in fechadas if d.numero_processo]
            if not processos_para_worten:
                print("\n  Nenhum processo com número para fechar na Worten.")
                return

            if args.so_awo:
                print(f"\n  --so-awo activo. Processos para fechar na Worten: "
                      f"{[d.numero_processo for d in processos_para_worten]}")
                return

            print(f"\n  {len(processos_para_worten)} processo(s) a fechar na Worten: "
                  f"{[d.numero_processo for d in processos_para_worten]}")

            aguardar_login_worten(page)

            resultados_worten = {"ok": [], "erro": []}
            for i, d in enumerate(processos_para_worten, 1):
                print(f"\n  Worten [{i}/{len(processos_para_worten)}]: {d.numero_processo}")
                estado = fechar_na_worten(page, d)
                if estado == "ok":
                    resultados_worten["ok"].append(d.numero_processo)
                else:
                    resultados_worten["erro"].append(f"{d.numero_processo} ({estado})")
                time.sleep(0.5)

            print(f"\n{'='*44}")
            print("         RELATÓRIO — WORTEN")
            print(f"{'='*44}")
            print(f"  Concluídos ✓   : {resultados_worten['ok']}")
            if resultados_worten["erro"]:
                print(f"  Com erros ✗    : {resultados_worten['erro']}")
            print(f"{'='*44}")

        except RuntimeError as exc:
            print(f"\nErro: {exc}")
            sys.exit(1)
        finally:
            print("\n  Pressione Enter para fechar o navegador...")
            input()
            browser.close()


if __name__ == "__main__":
    main()
