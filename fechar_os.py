"""
Automação completa: AWO → Worten

Fluxo:
  1. Login manual no AWO
  2. Calendário dia anterior → coleta OS (Estado=Realizado, TR preenchido)
  3. Para cada OS: lê dados, baixa imagens, gera PDF, muda Tipo→Fechado
  4. Login manual na Worten
  5. Para cada OS: processa na Worten (check-in, relatório, anexos, mensagem)
  6. Relatório final no terminal

Uso:
    python fechar_os.py            # processa ontem (padrão)
    python fechar_os.py --dry-run  # só lista, sem alterar nada
    python fechar_os.py --hoje     # processa hoje
    python fechar_os.py --so-awo   # só fecha no AWO, pula Worten
    python fechar_os.py --debug    # mostra eventos encontrados e sai
    python fechar_os.py --scan-form /work-orders/edit/XXXXX  # diagnóstico
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
URL_WORTEN    = "https://www.worten.pt/resolve/servicos"
PLANNING_PATH = "/work-orders/planning"
PASTA_FECHO   = Path.home() / "Documents" / "FECHO"

MENSAGEM_CLIENTE = (
    "Caro/a Cliente,\n"
    "O serviço de instalação foi concluído. Foi-lhe enviado um sms/e-mail para avaliação, "
    "pedimos a gentileza de responder com base no serviço prestado pelo técnico em sua morada, "
    "pois sua opinião é muito importante para nós.\n"
    "Com os melhores cumprimentos."
)


@dataclass
class DadosOS:
    href: str               # /work-orders/edit/{id}
    texto: str              # texto do evento no calendário
    awo_id: str = ""        # ID interno AWO (extraído do href)
    numero_processo: str = ""   # número antes do "/"
    data_visita: str = ""       # DD/MM/YYYY
    tecnico: str = ""           # nome do técnico (campo Tipo antes de fechar)
    trabalhos_realizados: str = ""
    pasta: Optional[Path] = None    # pasta com imagens e PDF
    pdf_path: Optional[Path] = None
    status: str = "pendente"    # pendente|ignorada|awo_ok|concluida|saltada|erro
    motivo: str = ""


# ──────────────────────────────────────────────
# Login manual
# ──────────────────────────────────────────────

def aguardar_login_awo(page) -> None:
    print("\n  Abrindo AWO — faça o login MANUALMENTE no navegador.")
    print("  O script continua sozinho após o login.\n")
    page.goto(f"{URL_AWO}/login")
    page.wait_for_load_state("networkidle")
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=180000)
    except PlaywrightTimeout:
        raise RuntimeError("Tempo esgotado aguardando login no AWO (3 min).")
    page.wait_for_load_state("networkidle")
    print("  Login AWO OK!\n")


def aguardar_login_worten(page) -> None:
    print("\n  Abrindo Worten — faça o login MANUALMENTE no navegador.")
    print("  O script continua sozinho após o login.\n")
    page.goto(URL_WORTEN)
    page.wait_for_load_state("networkidle")
    try:
        page.wait_for_url(
            lambda u: "login" not in u.lower() and "auth" not in u.lower(),
            timeout=180000
        )
    except PlaywrightTimeout:
        raise RuntimeError("Tempo esgotado aguardando login na Worten (3 min).")
    page.wait_for_load_state("networkidle")
    print("  Login Worten OK!\n")


# ──────────────────────────────────────────────
# Navegação para o dia certo (AWO)
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
    """Lê o campo que contém 'XXXXXX/...' e retorna só o número antes do '/'."""
    valor = page.evaluate("""
        () => {
            // Inputs e spans com "/" e começando com dígitos
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
    """Lê a data de início da OS."""
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
            // Fallback: primeiro input type=date
            const d = document.querySelector('input[type="date"], input[type="datetime-local"]');
            return d ? d.value : '';
        }
    """) or ""
    # Normaliza para DD/MM/YYYY
    if "T" in valor:
        valor = valor.split("T")[0]
    if "-" in valor and len(valor) >= 10:
        partes = valor[:10].split("-")
        if len(partes) == 3:
            return f"{partes[2]}/{partes[1]}/{partes[0]}"
    if " " in valor:
        return valor.split(" ")[0]
    return valor


def ler_trabalhos_realizados(page) -> str:
    """Lê o campo 'Trabalhos Realizados'."""
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
            // Fallback: textarea com mais conteúdo
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
            for (const img of document.querySelectorAll('img')) {
                const src = img.src || img.getAttribute('data-src') || '';
                if (!src || src.startsWith('data:') || vistos.has(src)) continue;
                if (img.naturalWidth > 0 && img.naturalWidth < 50) continue;
                vistos.add(src);
                resultado.push(src);
            }
            return resultado;
        }
    """) or []

    cookies = page.context.cookies()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    count = 0

    for i, url in enumerate(img_urls):
        try:
            ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
            if ext not in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
                ext = "jpg"
            dest = pasta / f"foto_{i+1:02d}.{ext}"
            req = urllib.request.Request(
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
    pdf_path = pasta / f"{pasta.name}.pdf"
    print_url = f"{URL_AWO}/work-orders/print/{awo_id}"
    try:
        pdf_browser = pw.chromium.launch(headless=True)
        ctx = pdf_browser.new_context()
        ctx.add_cookies(cookies)
        pdf_page = ctx.new_page()
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
# Alteração Tipo → Fechado (AWO)
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
                        Array.from(s.options).map(o => o.text).slice(0, 3).join('|') + ')').join(', ') + ']';
            }

            const opcoes = Array.from(tipoSelect.options);
            const alvo = opcoes.find(o =>
                o.text.trim().toLowerCase().includes('fechad') ||
                o.value.trim().toLowerCase().includes('fechad')
            );
            if (!alvo) {
                return 'erro:opcao Fechado nao encontrada. Opcoes: ' +
                    opcoes.map(o => '"' + o.text + '"').join(' | ');
            }

            const antes = tipoSelect.options[tipoSelect.selectedIndex]?.text || '';
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
        print(f"    AVISO mudança: {resultado[5:]}")
        return True
    print(f"    FALHA: {resultado}")
    return False


def salvar_awo(page) -> bool:
    time.sleep(1)
    for sel in ['button:has-text("Guardar")', 'button:has-text("Salvar")',
                'button:has-text("Gravar")', 'button[type="submit"]']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(3)
            return True
        except Exception:
            continue
    return False


# ──────────────────────────────────────────────
# Scan de formulário (debug)
# ──────────────────────────────────────────────

def scan_form(page, url: str) -> None:
    full_url = url if url.startswith("http") else f"{URL_AWO}{url}"
    print(f"\n  Diagnóstico: {full_url}")
    page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)
    info = page.evaluate("""
        () => ({
            selects: Array.from(document.querySelectorAll('select')).map(s => ({
                name: s.name, id: s.id,
                selected: s.options[s.selectedIndex]?.text || '',
                options: Array.from(s.options).map(o => o.text + '=[' + o.value + ']')
            })),
            inputs: Array.from(document.querySelectorAll('input:not([type=hidden])')).map(i => ({
                type: i.type, name: i.name, id: i.id, value: i.value
            })),
            textareas: Array.from(document.querySelectorAll('textarea')).map(t => ({
                name: t.name, id: t.id, value: (t.value||'').substring(0, 150)
            })),
            labels: Array.from(document.querySelectorAll('label')).map(l => ({
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
# Processamento de cada OS no AWO
# ──────────────────────────────────────────────

def processar_os_awo(page, ev: dict, dry_run: bool, pw) -> DadosOS:
    dados = DadosOS(href=ev["href"], texto=ev["texto"])
    dados.awo_id = ev["href"].rstrip("/").rsplit("/", 1)[-1]
    full_url = ev["href"] if ev["href"].startswith("http") else f"{URL_AWO}{ev['href']}"
    titulo = ev["texto"][:60] or ev["href"]

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

    estado = ler_select_por_nome_ou_label(page, "estado")
    tecnico = ler_select_por_nome_ou_label(page, "tipo")

    e = estado.lower().strip()
    if not ("realizado" in e and "não" not in e and "nao" not in e):
        print(f"    [{estado or '---'}] {titulo} — ignorada")
        dados.status = "ignorada"
        return dados

    if "fechad" in tecnico.lower():
        print(f"    [Já fechado] {titulo} — ignorada")
        dados.status = "ignorada"
        return dados

    dados.tecnico          = tecnico
    dados.numero_processo  = ler_numero_processo(page)
    dados.data_visita      = ler_data_visita(page)
    dados.trabalhos_realizados = ler_trabalhos_realizados(page)

    print(f"    [PARA FECHAR] Estado={estado} | Técnico={dados.tecnico} | Processo={dados.numero_processo}")

    if not dados.trabalhos_realizados:
        print("    AVISO: 'Trabalhos Realizados' vazio — será saltada na Worten")

    if dry_run:
        dados.status = "para_fechar"
        return dados

    # Baixa imagens e gera PDF (só se TR preenchido e processo identificado)
    if dados.numero_processo and dados.trabalhos_realizados:
        pasta = PASTA_FECHO / dados.numero_processo
        pasta.mkdir(parents=True, exist_ok=True)
        dados.pasta = pasta

        n_imgs = baixar_imagens(page, pasta)
        print(f"    {n_imgs} imagem(ns) baixada(s) → {pasta}")

        # Volta para aba Ficha antes do PDF
        for sel in ['a:has-text("Ficha")', '[href*="ficha"]', 'li:has-text("Ficha") a']:
            try:
                page.click(sel, timeout=3000)
                time.sleep(1)
                break
            except Exception:
                continue

        dados.pdf_path = gerar_pdf(dados.awo_id, pasta, page.context.cookies(), pw)

    # Muda Tipo → Fechado e salva
    if not alterar_tipo_fechado(page):
        page.screenshot(path=f"debug_tipo_{dados.awo_id}.png")
        dados.status = "erro"
        dados.motivo = "alterar_tipo_fechado falhou"
        return dados

    if not salvar_awo(page):
        print("    AVISO: botão salvar não encontrado")
        page.screenshot(path=f"debug_salvar_{dados.awo_id}.png")
        dados.status = "erro"
        dados.motivo = "salvar falhou"
        return dados

    print("    AWO: Tipo → Fechado ✓")
    dados.status = "awo_ok"
    return dados


# ──────────────────────────────────────────────
# Worten: helpers
# ──────────────────────────────────────────────

def w_clicar(page, textos: list, timeout: int = 8000) -> bool:
    for txt in textos:
        for sel in [f'button:has-text("{txt}")', f'a:has-text("{txt}")',
                    f'[role="button"]:has-text("{txt}")', f'input[value="{txt}"]']:
            try:
                page.click(sel, timeout=timeout)
                time.sleep(1.5)
                return True
            except Exception:
                continue
    return False


def w_selecionar(page, label: str, valor: str) -> bool:
    resultado = page.evaluate(f"""
        () => {{
            const busca = '{label}'.toLowerCase();
            const val   = '{valor}'.toLowerCase();
            for (const el of document.querySelectorAll('label, span, p, div, th')) {{
                if (!el.textContent.trim().toLowerCase().includes(busca)) continue;
                let sel = el.parentElement?.querySelector('select') ||
                          el.nextElementSibling;
                if (!sel || sel.tagName !== 'SELECT') continue;
                const opt = Array.from(sel.options).find(o =>
                    o.text.toLowerCase().includes(val) || o.value.toLowerCase().includes(val));
                if (!opt) return 'sem_opcao:' + Array.from(sel.options).map(o => o.text).join('|');
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLSelectElement.prototype, 'value').set;
                setter.call(sel, opt.value);
                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                return 'ok:' + opt.text;
            }}
            return 'sem_label';
        }}
    """)
    ok = isinstance(resultado, str) and resultado.startswith("ok:")
    if not ok:
        print(f"      AVISO dropdown '{label}': {resultado}")
    return ok


def w_preencher(page, label: str, valor: str) -> bool:
    valor_js = valor.replace("\\", "\\\\").replace("`", "'").replace("\n", "\\n")
    resultado = page.evaluate(f"""
        () => {{
            const busca = '{label}'.toLowerCase();
            for (const lbl of document.querySelectorAll('label, span, p, div')) {{
                if (!lbl.textContent.trim().toLowerCase().includes(busca)) continue;
                let el = lbl.nextElementSibling ||
                         lbl.parentElement?.querySelector('input, textarea');
                if (!el || !['INPUT','TEXTAREA'].includes(el.tagName)) continue;
                const setter = Object.getOwnPropertyDescriptor(
                    Object.getPrototypeOf(el), 'value').set;
                setter.call(el, `{valor_js}`);
                el.dispatchEvent(new Event('input',  {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return 'ok';
            }}
            return 'nao_encontrado';
        }}
    """)
    return resultado == "ok"


def w_clicar_opcao(page, texto: str) -> bool:
    for sel in [f'label:has-text("{texto}")', f'button:has-text("{texto}")',
                f'[class*="option"]:has-text("{texto}")', f'li:has-text("{texto}")',
                f'[role="radio"]:has-text("{texto}")', f'[role="option"]:has-text("{texto}")']:
        try:
            page.click(sel, timeout=4000)
            time.sleep(0.5)
            return True
        except Exception:
            continue
    return False


def w_upload_arquivos(page, caminhos: list[str]) -> bool:
    if not caminhos:
        return True
    for sel in ['input[type="file"]', '[class*="upload"] input[type="file"]',
                '[class*="drop"] input[type="file"]']:
        try:
            page.set_input_files(sel, caminhos, timeout=5000)
            time.sleep(3)
            return True
        except Exception:
            continue
    print("    AVISO: campo de upload não encontrado")
    return False


# ──────────────────────────────────────────────
# Worten: fluxo completo de uma OS
# ──────────────────────────────────────────────

def processar_os_worten(page, dados: DadosOS) -> bool:
    nome = dados.numero_processo or dados.texto[:40]
    print(f"\n  Worten → Processo {nome} | Técnico: {dados.tecnico}")

    try:
        # ── Passo 1: pesquisar processo ──
        page.goto(f"{URL_WORTEN}?status=all", wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)

        pesquisou = False
        for sel in ['input[type="search"]', 'input[placeholder*="pesquis" i]',
                    'input[placeholder*="número" i]', 'input[name*="search"]', 'input[name*="q"]']:
            try:
                page.fill(sel, dados.numero_processo, timeout=3000)
                page.keyboard.press("Enter")
                time.sleep(2)
                pesquisou = True
                break
            except Exception:
                continue

        if not pesquisou:
            print(f"    AVISO: campo de pesquisa não encontrado — tentando URL direta")

        for sel in [f'a:has-text("{dados.numero_processo}")',
                    f'[class*="card"]:has-text("{dados.numero_processo}") a',
                    f'tr:has-text("{dados.numero_processo}") a',
                    f'li:has-text("{dados.numero_processo}") a']:
            try:
                page.click(sel, timeout=6000)
                time.sleep(2)
                break
            except Exception:
                continue

        # ── Passo 2: Justificar check-in ──
        tem_checkin = False
        try:
            page.wait_for_selector('button:has-text("JUSTIFICAR"), a:has-text("JUSTIFICAR")',
                                   timeout=4000)
            tem_checkin = True
        except Exception:
            pass

        if tem_checkin:
            w_clicar(page, ["JUSTIFICAR", "Justificar"])
            time.sleep(1)
            w_clicar_opcao(page, "Sim, efetuei a visita")
            time.sleep(0.5)

            # Data da visita (converter DD/MM/YYYY → YYYY-MM-DD)
            data_iso = dados.data_visita
            if "/" in dados.data_visita:
                p = dados.data_visita.split("/")
                if len(p) == 3:
                    data_iso = f"{p[2]}-{p[1]}-{p[0]}"
            for sel in ['input[type="date"]', 'input[type="datetime-local"]',
                        'input[name*="data"]', 'input[placeholder*="data" i]']:
                try:
                    page.fill(sel, data_iso, timeout=3000)
                    break
                except Exception:
                    continue

            w_selecionar(page, "motivo", "Atualizei o pedido ao final do dia")
            time.sleep(0.5)
            w_clicar(page, ["AVANÇAR", "Avançar", "NEXT"])
            time.sleep(2)

        # ── Passo 3: Atualizar pedido ──
        w_clicar(page, ["ATUALIZAR PEDIDO", "Atualizar Pedido", "ATUALIZAR"])
        time.sleep(2)

        # ── Passo 4: Concluir Serviço (1ª vez) ──
        w_clicar(page, ["Concluir Serviço", "CONCLUIR SERVIÇO", "Concluir serviço"])
        time.sleep(1)
        # Modal de confirmação
        w_clicar(page, ["Serviço concluído", "Marcar pedido como finalizado",
                        "Serviço concluído — Marcar pedido"])
        time.sleep(2)

        # ── Passo 5: Preencher relatório ──
        w_clicar(page, ["PREENCHER RELATÓRIO", "Preencher Relatório", "PREENCHER RELATORIO"])
        time.sleep(2)

        w_selecionar(page, "Resultado da Instalação", "Instalação Realizada")
        time.sleep(0.5)
        w_selecionar(page, "Detalhe Complementar", "Equipamento e Instalação com sucesso")
        time.sleep(0.5)

        # Textarea "Justifique o resultado"
        for sel in ['textarea[name*="justif"]', 'textarea[id*="justif"]',
                    'textarea[placeholder*="justif" i]', 'textarea[placeholder*="resultado" i]']:
            try:
                page.locator(sel).first.fill(dados.trabalhos_realizados, timeout=3000)
                break
            except Exception:
                continue
        else:
            # Fallback: primeira textarea disponível
            try:
                page.locator("textarea").first.fill(dados.trabalhos_realizados, timeout=3000)
            except Exception:
                pass

        w_clicar_opcao(page, "Sim")          # Realizou visita?
        time.sleep(0.3)
        w_clicar_opcao(page, "Não")          # Orçamento extra?
        time.sleep(0.3)
        w_selecionar(page, "Localização", "Na morada do Cliente")
        time.sleep(0.3)
        w_preencher(page, "Técnico Responsável", dados.tecnico)
        time.sleep(0.3)

        # Upload de imagens
        if dados.pasta and dados.pasta.exists():
            imgs = [str(p) for p in sorted(dados.pasta.iterdir())
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")]
            if imgs:
                w_upload_arquivos(page, imgs)
                print(f"    {len(imgs)} foto(s) enviada(s)")

        w_clicar(page, ["ENVIAR RELATÓRIO", "Enviar Relatório", "ENVIAR RELATORIO"])
        time.sleep(3)

        # ── Passo 6: Anexar PDF ──
        if dados.pdf_path and dados.pdf_path.exists():
            for sel in ['a:has-text("ANEXOS")', 'a:has-text("Anexos")',
                        '[href*="anexo"]', 'li:has-text("ANEXOS") a']:
                try:
                    page.click(sel, timeout=5000)
                    time.sleep(2)
                    break
                except Exception:
                    continue

            w_upload_arquivos(page, [str(dados.pdf_path)])
            print(f"    PDF anexado: {dados.pdf_path.name}")
            w_clicar(page, ["GUARDAR", "Guardar", "SALVAR", "Salvar"])
            time.sleep(2)

        # ── Passo 7: Concluir Serviço (final) ──
        w_clicar(page, ["CONCLUIR SERVIÇO", "Concluir Serviço", "CONCLUIR"])
        time.sleep(2)
        w_clicar(page, ["FECHAR", "Fechar", "CLOSE"])
        time.sleep(1)

        # ── Passo 8: Enviar mensagem ao cliente ──
        for sel in ['a:has-text("ENVIAR MENSAGEM")', 'a:has-text("Enviar Mensagem")',
                    'button:has-text("ENVIAR MENSAGEM")', '[href*="mensagem"]']:
            try:
                page.click(sel, timeout=5000)
                time.sleep(2)
                break
            except Exception:
                continue

        for sel in ['textarea', 'div[contenteditable="true"]', '[role="textbox"]']:
            try:
                page.locator(sel).first.fill(MENSAGEM_CLIENTE, timeout=3000)
                break
            except Exception:
                continue

        w_clicar(page, ["ENVIAR", "Enviar", "SEND", "Send"])
        time.sleep(2)

        print(f"    Worten: OS {nome} concluída ✓")
        dados.status = "concluida"
        return True

    except Exception as e:
        print(f"    [ERRO Worten] {nome}: {e}")
        dados.status = "erro"
        dados.motivo = f"Worten: {e}"
        try:
            page.screenshot(path=f"debug_worten_{nome}_{int(time.time())}.png")
        except Exception:
            pass
        return False


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",   action="store_true", help="Lista sem alterar")
    parser.add_argument("--hoje",      action="store_true", help="Processa hoje")
    parser.add_argument("--debug",     action="store_true", help="Mostra eventos e sai")
    parser.add_argument("--so-awo",    action="store_true", help="Só AWO, pula Worten")
    parser.add_argument("--scan-form", metavar="URL",       help="Diagnóstico de formulário")
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
                print("  Eventos sem URLs — use --debug para inspecionar.")
                return

            print(f"  {len(eventos)} OS encontradas em {label}. Processando AWO...\n")
            lista: list[DadosOS] = []

            for ev in eventos:
                d = processar_os_awo(page, ev, args.dry_run, pw)
                lista.append(d)
                time.sleep(0.3)

            # ── Resumo AWO ──
            para_fechar = [d for d in lista if d.status in ("awo_ok", "para_fechar")]
            ignoradas   = [d for d in lista if d.status == "ignorada"]
            erros_awo   = [d for d in lista if d.status == "erro"]

            print(f"\n  ── AWO {label} ──")
            print(f"  Total:     {len(eventos)}")
            if args.dry_run:
                print(f"  Para fechar: {len(para_fechar)}")
                print(f"  Ignoradas:   {len(ignoradas)}")
                if erros_awo:
                    print(f"  Erros:       {len(erros_awo)}")
                return

            print(f"  Fechadas:  {len(para_fechar)}")
            print(f"  Ignoradas: {len(ignoradas)}")
            if erros_awo:
                print(f"  Erros AWO: {len(erros_awo)}")

            # ── Fase Worten ──
            candidatas = [d for d in lista if d.status == "awo_ok"
                         and d.trabalhos_realizados and d.numero_processo]
            saltadas   = [d for d in lista if d.status == "awo_ok"
                         and (not d.trabalhos_realizados or not d.numero_processo)]

            if saltadas:
                print(f"\n  AVISO: {len(saltadas)} OS saltadas na Worten "
                      f"(sem 'Trabalhos Realizados' ou sem número de processo)")

            if args.so_awo or not candidatas:
                return

            print(f"\n  {len(candidatas)} OS prontas para a Worten.")
            aguardar_login_worten(page)

            for d in candidatas:
                processar_os_worten(page, d)
                time.sleep(0.5)

            # ── Relatório final ──
            concluidas  = sum(1 for d in candidatas if d.status == "concluida")
            erros_w     = sum(1 for d in candidatas if d.status == "erro")

            print(f"\n{'='*44}")
            print("         RELATÓRIO FINAL")
            print(f"{'='*44}")
            print(f"  Concluídas com sucesso : {concluidas}")
            print(f"  Saltadas (sem TR)       : {len(saltadas)}")
            print(f"  Erros AWO               : {len(erros_awo)}")
            print(f"  Erros Worten            : {erros_w}")
            todos_erros = [d for d in lista if d.status == "erro"]
            if todos_erros:
                print("\n  Processos com erro:")
                for d in todos_erros:
                    print(f"    - {d.numero_processo or d.texto[:40]} → {d.motivo}")
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
