"""
Automação: fecha OS com status "Realizado" do dia anterior.

Fluxo:
  1. Abre o navegador — você faz login manualmente
  2. Vai para Calendário > vista Dia > dia anterior
  3. Para cada OS: se Estado = "Realizado" e Tipo != "Fechado" → muda Tipo para "Fechado" → salva

Uso:
    python fechar_os.py            # processa ontem (padrão)
    python fechar_os.py --dry-run  # só lista, sem alterar
    python fechar_os.py --hoje     # processa hoje
    python fechar_os.py --debug    # mostra URLs encontradas e sai
"""

import os
import sys
import time
import argparse
from datetime import date, timedelta
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

URL          = os.environ.get("PLATFORM_URL", "https://suporteprime.awo-soft.com")
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
    print("  Abrindo calendário...")
    page.goto(f"{URL}{PLANNING_PATH}")
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
                        b.click(); clicou = True; break
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
    dados = page.evaluate(f"""
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
    """)
    return dados or []


# ──────────────────────────────────────────────
# Leitura dos campos da OS
# ──────────────────────────────────────────────

def ler_campo(page, nome_campo: str) -> str:
    """Lê o valor atual de um campo select pelo name/id ou pelo label."""
    return page.evaluate(f"""
        () => {{
            const nome = '{nome_campo}';
            const selects = Array.from(document.querySelectorAll('select'));

            // 1) Por name ou id
            for (const s of selects) {{
                const id = (s.name || s.id || '').toLowerCase();
                if (id.includes(nome)) {{
                    return s.options[s.selectedIndex]?.text || s.value || '';
                }}
            }}

            // 2) Pelo label
            for (const lbl of document.querySelectorAll('label')) {{
                const txt = lbl.textContent.trim().toLowerCase();
                if (txt.startsWith(nome)) {{
                    const forId = lbl.getAttribute('for');
                    const s = forId ? document.getElementById(forId)
                                    : lbl.parentElement?.querySelector('select');
                    if (s && s.tagName === 'SELECT') {{
                        return s.options[s.selectedIndex]?.text || s.value || '';
                    }}
                }}
            }}
            return '';
        }}
    """) or ""


# ──────────────────────────────────────────────
# Alteração do campo Tipo
# ──────────────────────────────────────────────

def alterar_tipo_fechado(page) -> bool:
    """Muda o campo Tipo para 'Fechado' usando o setter nativo (compatível com Vue.js)."""
    resultado = page.evaluate("""
        () => {
            const selects = Array.from(document.querySelectorAll('select'));
            let tipoSelect = null;

            // 1) Por name/id contendo "tipo"
            for (const s of selects) {
                const id = (s.name || s.id || '').toLowerCase();
                if (id.includes('tipo') || id.includes('type')) {
                    tipoSelect = s; break;
                }
            }

            // 2) Pelo label cujo texto é exatamente "Tipo" (ou "Tipo:")
            if (!tipoSelect) {
                for (const lbl of document.querySelectorAll('label')) {
                    const txt = lbl.textContent.trim().toLowerCase().replace(/:$/, '');
                    if (txt === 'tipo') {
                        const forId = lbl.getAttribute('for');
                        const s = forId ? document.getElementById(forId)
                                        : lbl.parentElement?.querySelector('select');
                        if (s && s.tagName === 'SELECT') { tipoSelect = s; break; }
                    }
                }
            }

            // 3) Label que começa com "tipo" (fallback)
            if (!tipoSelect) {
                for (const lbl of document.querySelectorAll('label')) {
                    const txt = lbl.textContent.trim().toLowerCase();
                    if (txt.startsWith('tipo')) {
                        const forId = lbl.getAttribute('for');
                        const s = forId ? document.getElementById(forId)
                                        : lbl.parentElement?.querySelector('select');
                        if (s && s.tagName === 'SELECT') { tipoSelect = s; break; }
                    }
                }
            }

            if (!tipoSelect) {
                return 'erro:nenhum select tipo. Selects na pagina: [' +
                    selects.map(s => (s.name||s.id||'sem-id') + '(' +
                        Array.from(s.options).map(o=>o.text).slice(0,3).join('|') + ')').join(', ') + ']';
            }

            const opcoes = Array.from(tipoSelect.options);
            const alvo = opcoes.find(o =>
                o.text.trim().toLowerCase().includes('fechad') ||
                o.value.trim().toLowerCase().includes('fechad')
            );

            if (!alvo) {
                return 'erro:opcao fechado nao encontrada no select id=' + (tipoSelect.id||tipoSelect.name||'?') +
                    '. Opcoes disponiveis: ' + opcoes.map(o => '"' + o.text + '"').join(' | ');
            }

            const anteriorText = tipoSelect.options[tipoSelect.selectedIndex]?.text || '';

            // Setter nativo — necessário para Vue.js/React não ignorar a mudança
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, 'value'
            ).set;
            setter.call(tipoSelect, alvo.value);
            tipoSelect.dispatchEvent(new Event('input',  { bubbles: true }));
            tipoSelect.dispatchEvent(new Event('change', { bubbles: true }));

            // Vue 3: dispara também no elemento pai caso seja um wrapper
            const parent = tipoSelect.parentElement;
            if (parent) {
                parent.dispatchEvent(new Event('change', { bubbles: true }));
            }

            // Verifica se a mudança foi aceita pelo DOM
            const posteriorText = tipoSelect.options[tipoSelect.selectedIndex]?.text || '';
            if (posteriorText.toLowerCase().includes('fechad')) {
                return 'ok:' + anteriorText + ' → ' + posteriorText;
            }
            return 'warn:mudanca enviada mas valor atual ainda e "' + posteriorText + '" (esperado "' + alvo.text + '")';
        }
    """)

    if isinstance(resultado, str) and resultado.startswith("ok:"):
        print(f"    Tipo → {resultado[3:]}")
        return True

    if isinstance(resultado, str) and resultado.startswith("warn:"):
        print(f"    AVISO mudança parcial: {resultado[5:]}")
        return True  # tenta salvar mesmo assim

    print(f"    FALHA: {resultado}")
    return False


# ──────────────────────────────────────────────
# Salvar
# ──────────────────────────────────────────────

def salvar(page) -> bool:
    time.sleep(1)  # aguarda Vue processar a mudança do select antes de salvar
    for sel in ['button:has-text("Guardar")', 'button:has-text("Salvar")',
                'button:has-text("Gravar")', 'button[type="submit"]']:
        try:
            page.click(sel, timeout=5000)
            time.sleep(3)
            return True
        except Exception:
            continue
    return False


def scan_form(page, url: str) -> None:
    """Imprime todos os campos do formulário de uma OS (para diagnóstico)."""
    import json
    full_url = url if url.startswith("http") else f"{URL}{url}"
    print(f"\n  Abrindo OS para diagnóstico: {full_url}")
    page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)

    info = page.evaluate("""
        () => {
            const selects = Array.from(document.querySelectorAll('select')).map(s => ({
                tag: 'select',
                name: s.name || null,
                id:   s.id   || null,
                selected: s.options[s.selectedIndex]?.text || '',
                options: Array.from(s.options).map(o => o.text + ' [val=' + o.value + ']')
            }));
            const inputs = Array.from(document.querySelectorAll('input:not([type=hidden])')).map(i => ({
                tag: 'input',
                type: i.type,
                name: i.name || null,
                id:   i.id   || null,
                value: i.value || null
            }));
            const labels = Array.from(document.querySelectorAll('label')).map(l => ({
                text: l.textContent.trim(),
                for:  l.getAttribute('for')
            }));
            return { selects, inputs, labels };
        }
    """)
    print("\n=== SELECTS ===")
    for s in info.get("selects", []):
        print(f"  name={s['name']} id={s['id']} selecionado='{s['selected']}'")
        for o in s["options"]:
            print(f"    opção: {o}")
    print("\n=== INPUTS ===")
    for i in info.get("inputs", []):
        print(f"  [{i['type']}] name={i['name']} id={i['id']} value={i['value']}")
    print("\n=== LABELS ===")
    for l in info.get("labels", []):
        print(f"  '{l['text']}'  for={l['for']}")


# ──────────────────────────────────────────────
# Processamento de cada OS
# ──────────────────────────────────────────────

def processar_os(page, url: str, texto: str, dry_run: bool) -> str:
    full_url = url if url.startswith("http") else f"{URL}{url}"
    titulo   = texto[:70] or url

    try:
        page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
    except Exception as e:
        print(f"    [ERRO] {titulo}: {e}")
        return "erro"

    if "/login" in page.url:
        return "erro"

    estado = ler_campo(page, "estado")
    tipo   = ler_campo(page, "tipo")

    # Só processa Estado = "Realizado" (exclui "Não Realizado")
    e = estado.lower().strip()
    is_realizado = "realizado" in e and "não" not in e and "nao" not in e

    if not is_realizado:
        print(f"    [{estado or '---'}] {titulo} — ignorada")
        return "ignorada"

    # Já está fechado
    if "fechad" in tipo.lower():
        print(f"    [Já fechado] {titulo} — ignorada")
        return "ignorada"

    print(f"    [PARA FECHAR] Estado={estado} | Tipo={tipo} | {titulo}")

    if dry_run:
        return "para_fechar"

    # Altera Tipo → Fechado
    if not alterar_tipo_fechado(page):
        page.screenshot(path=f"debug_{int(time.time())}.png")
        return "erro"

    # Salva
    if not salvar(page):
        print("    AVISO: botão salvar não encontrado")
        page.screenshot(path=f"debug_salvar_{int(time.time())}.png")
        return "erro"

    print("    Fechada com sucesso!")
    return "fechada"


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",   action="store_true", help="Lista sem alterar")
    parser.add_argument("--hoje",      action="store_true", help="Processa hoje")
    parser.add_argument("--debug",     action="store_true", help="Mostra URLs e sai")
    parser.add_argument("--scan-form", metavar="URL",       help="Mostra campos de uma OS e sai")
    args = parser.parse_args()

    alvo  = date.today() if args.hoje else date.today() - timedelta(days=1)
    label = alvo.strftime("%d/%m/%Y")
    modo  = "DRY RUN (sem alterações)" if args.dry_run else "MODO REAL"

    print(f"\n=== Fechamento de OS — {label} ({modo}) ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page    = browser.new_page()

        try:
            aguardar_login(page)

            if args.scan_form:
                scan_form(page, args.scan_form)
                return

            ir_para_dia_vista(page, alvo)

            if args.debug:
                n       = page.evaluate("() => document.querySelectorAll('.fc-event').length")
                eventos = extrair_urls_eventos(page, ".fc-event")
                print(f"  .fc-event: {n} | URLs: {len(eventos)}")
                for ev in eventos[:5]:
                    print(f"    {ev['href']}  →  {ev['texto'][:50]}")
                return

            result = page.evaluate("""
                () => {
                    for (const sel of ['.fc-timegrid-event', '.fc-event', '[class*="fc-event"]']) {
                        if (document.querySelectorAll(sel).length > 0) return sel;
                    }
                    return null;
                }
            """)

            if not result:
                page.screenshot(path="debug_sem_eventos.png")
                print(f"  Nenhum evento encontrado em {label}.")
                return

            eventos = extrair_urls_eventos(page, result)
            if not eventos:
                print("  Eventos sem URLs — verifique com --debug")
                return

            print(f"  {len(eventos)} OS encontradas em {label}. Processando...\n")
            fechadas = para_fechar = ignoradas = erros = 0

            for ev in eventos:
                r = processar_os(page, ev["href"], ev["texto"], args.dry_run)
                if   r == "fechada":     fechadas    += 1
                elif r == "para_fechar": para_fechar += 1
                elif r == "erro":        erros       += 1
                else:                    ignoradas   += 1
                time.sleep(0.3)

            print(f"\n  ── Resumo {label} ──")
            print(f"  Total:     {len(eventos)}")
            if args.dry_run:
                print(f"  Para fechar (dry-run): {para_fechar}")
                print(f"  Já OK / outros:        {ignoradas}")
            else:
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
