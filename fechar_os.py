"""
Automação AWO + Worten — Fecho de OS

Fluxo:
  FASE 1 — AWO (login manual):
    1. Calendário do dia → encontra OS com Estado=Realizado e Trabalhos preenchidos
    2. Para cada OS: lê dados, baixa imagens, gera PDF, guarda relatorio.txt, muda Tipo→Fechado

  FASE 2 — Worten (login manual):
    3. Para cada OS processada: pesquisa processo, justifica check-in, preenche
       relatório, anexa PDF e conclui serviço com mensagem ao cliente.

Estrutura de pastas criada:
    Documentos/FECHO/
        {numero_processo}/
            foto_01.jpg  (imagens descarregadas do AWO)
            ...
            {numero_processo}.pdf
            relatorio.txt

Uso:
    python fechar_os.py                      # processa ontem (padrão)
    python fechar_os.py --hoje               # processa hoje
    python fechar_os.py --dry-run            # lista sem alterar
    python fechar_os.py --so-awo             # fase AWO apenas (sem Worten)
    python fechar_os.py --debug              # mostra eventos encontrados e sai
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
from worten import aguardar_login_worten, processar_os_worten

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
    hora_visita: str = ""
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
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=180000)
    except PlaywrightTimeout:
        raise RuntimeError("Tempo esgotado aguardando login no AWO (3 min).")
    except Exception:
        if "/login" in page.url:
            raise RuntimeError("Erro durante a navegação do login AWO.")
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
                // Extrai hora do atributo data-start ou do texto do evento (ex: "8:00 - 9:00")
                const dataStart = e.getAttribute('data-start') || e.closest('[data-start]')?.getAttribute('data-start') || '';
                let hora = '';
                if (dataStart) {{
                    const m = dataStart.match(/T(\\d{{2}}:\\d{{2}})/);
                    if (m) hora = m[1];
                }}
                if (!hora) {{
                    const m = texto.match(/(\\d{{1,2}}:\\d{{2}})/);
                    if (m) hora = m[1].padStart(5, '0');
                }}
                resultado.push({{ href, texto, hora }});
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


def ler_data_visita(page) -> tuple[str, str]:
    """Devolve (data DD/MM/YYYY, hora HH:MM) lidas do AWO."""
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
            const d = document.querySelector('input[type="datetime-local"], input[type="date"]');
            return d ? d.value : '';
        }
    """) or ""

    hora = ""
    if "T" in valor:
        partes = valor.split("T")
        hora  = partes[1][:5] if len(partes) > 1 else ""
        valor = partes[0]
    elif " " in valor and ":" in valor:
        partes = valor.split(" ")
        hora  = partes[1][:5]
        valor = partes[0]

    # Normaliza data para DD/MM/YYYY
    if "-" in valor and len(valor) >= 10:
        p = valor[:10].split("-")
        if len(p) == 3:
            valor = f"{p[2]}/{p[1]}/{p[0]}"

    return valor, hora


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
    dados.awo_id    = ev["href"].rstrip("/").rsplit("/", 1)[-1]
    dados.hora_visita = ev.get("hora", "")
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
    dados.data_visita, dados.hora_visita = ler_data_visita(page)
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
        print("    AVISO: botão guardar não encontrado")
        page.screenshot(path=f"debug_salvar_{dados.awo_id}.png")
        dados.status = "erro"
        dados.motivo = "guardar falhou"
        return dados

    print(f"    ✓ OS {dados.numero_processo} fechada")
    dados.status = "ok"
    return dados


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fecho automático de OS no AWO + Worten")
    parser.add_argument("--dry-run",   action="store_true", help="Lista sem alterar")
    parser.add_argument("--hoje",      action="store_true", help="Processa hoje (padrão: ontem)")
    parser.add_argument("--so-awo",    action="store_true", help="Apenas fase AWO, sem Worten")
    parser.add_argument("--debug",     action="store_true", help="Mostra eventos e sai")
    parser.add_argument("--scan-form", metavar="URL",       help="Diagnóstico de formulário AWO")
    args = parser.parse_args()

    alvo  = date.today() if args.hoje else date.today() - timedelta(days=1)
    label = alvo.strftime("%d/%m/%Y")
    modo  = "DRY RUN" if args.dry_run else ("FECHO AWO" if args.so_awo else "FECHO AWO + WORTEN")

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

            print(f"  {len(eventos)} OS encontradas em {label}. Processando...\n")

            lista: list[DadosOS] = []
            for ev in eventos:
                d = processar_os(page, ev, args.dry_run, pw)
                lista.append(d)
                time.sleep(0.3)

            # ── Fase 2: Worten ──
            fechadas_awo = [d for d in lista if d.status == "ok"]
            worten_ok: list[DadosOS] = []
            worten_err: list[DadosOS] = []

            if not args.dry_run and not args.so_awo and fechadas_awo:
                print(f"\n{'='*44}")
                print("         FASE 2 — WORTEN")
                print(f"{'='*44}")
                print(f"  {len(fechadas_awo)} OS para processar na Worten.\n")
                aguardar_login_worten(page)

                for d in fechadas_awo:
                    fotos = sorted(d.pasta.glob("foto_*")) if d.pasta else []
                    ok = processar_os_worten(
                        page,
                        numero_processo=d.numero_processo,
                        data_visita=d.data_visita,
                        hora_visita=d.hora_visita,
                        trabalhos=d.trabalhos_realizados,
                        fotos=fotos,
                        pdf_path=d.pdf_path,
                    )
                    (worten_ok if ok else worten_err).append(d)
                    time.sleep(0.5)

            # ── Relatório final ──
            fechadas  = [d for d in lista if d.status == "ok"]
            dry_list  = [d for d in lista if d.status == "para_fechar"]
            ignoradas = [d for d in lista if d.status == "ignorada"]
            erros     = [d for d in lista if d.status == "erro"]

            print(f"\n{'='*44}")
            print("         RELATÓRIO FINAL — AWO")
            print(f"{'='*44}")
            print(f"  Data           : {label}")
            print(f"  Total eventos  : {len(eventos)}")
            if args.dry_run:
                print(f"  Para fechar    : {len(dry_list)}")
                for d in dry_list:
                    print(f"    • {d.numero_processo or d.texto[:40]} | {d.tecnico}")
            else:
                print(f"  Fechadas AWO ✓ : {len(fechadas)}")
                print(f"  Ignoradas      : {len(ignoradas)}")
                if erros:
                    print(f"  Erros AWO      : {len(erros)}")
                    for d in erros:
                        print(f"    ✗ {d.numero_processo or d.texto[:40]} → {d.motivo}")
                if not args.so_awo:
                    print(f"  Worten OK ✓    : {len(worten_ok)}")
                    if worten_err:
                        print(f"  Worten erros   : {len(worten_err)}")
                        for d in worten_err:
                            print(f"    ✗ {d.numero_processo or d.texto[:40]}")
                print(f"\n  Pasta: {PASTA_FECHO}")
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
