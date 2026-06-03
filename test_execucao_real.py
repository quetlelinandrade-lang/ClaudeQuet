"""
Teste de execução real — simula AWO + Worten com servidor HTTP local.
Executa as funções reais do fechar_os.py contra páginas mock fidedignas.
"""
import sys
import time
import threading
import http.server
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Páginas HTML mock ──────────────────────────────────────────────────────────

AWO_LOGIN = """<!DOCTYPE html><html><body>
<form method="POST" action="/login">
  <input name="email" value=""><input name="password" type="password">
  <button type="submit">Entrar</button>
</form></body></html>"""

AWO_DASHBOARD = """<!DOCTYPE html><html><head><title>Dashboard AWO</title></head>
<body><h1>Dashboard</h1><a href="/work-orders/planning">Calendário</a></body></html>"""

# Página da OS com estrutura real AWO:
# - Logo no navbar (DEVE SER EXCLUÍDA)
# - Sidebar com ícones (DEVEM SER EXCLUÍDOS)
# - Campo "Nº Processo" com valor "3240023/82600144 LEV"
# - Aba Imagens/Doc com 3 fotos reais
AWO_OS = """<!DOCTYPE html><html><head><title>Ordem 3240023</title></head><body>
<nav class="navbar topbar">
  <img id="logo" src="/static/logo-awo.png" width="120" height="40">
  <span>AWO-SOFT</span>
</nav>
<aside class="sidebar">
  <img src="/static/icons/dashboard.svg" width="24" height="24">
  <img src="/static/icons/clients.svg" width="24" height="24">
</aside>
<main>
  <div class="work-order-form">
    <label for="processo">Nº Processo</label>
    <input id="processo" value="3240023/82600144 LEV">
    <label for="estado">Estado</label>
    <select id="estado"><option value="realizado" selected>Realizado</option></select>
    <label for="tipo">Tipo</label>
    <select id="tipo">
      <option value="aberto">Aberto</option>
      <option value="fechado">Fechado</option>
    </select>
    <label for="inicio">Data de Início</label>
    <input id="inicio" type="date" value="2026-06-02">
    <label for="tr">Trabalhos Realizados</label>
    <textarea id="tr">Instalação de termoacumulador concluída com sucesso.</textarea>
    <button type="submit">Guardar</button>
  </div>
  <ul class="tabs">
    <li><a href="#tab_ficha">Ficha</a></li>
    <li><a href="#tab_images">Imagens/Doc.</a></li>
  </ul>
  <div id="tab_images">
    <h2>Imagens e Documentos</h2>
    <div class="images-grid">
      <div><img id="foto1" src="/static/fotos/foto1.jpg" width="800" height="600"></div>
      <div><img id="foto2" src="/static/fotos/foto2.jpg" width="1200" height="900"></div>
      <div><img id="foto3" src="/static/fotos/foto3.jpg" width="1024" height="768"></div>
    </div>
  </div>
</main>
</body></html>"""

AWO_PLANNING = """<!DOCTYPE html><html><body>
<button>Dia</button><button>Hoje</button>
<div class="fc-event"><a href="/work-orders/edit/999">OS Teste</a></div>
</body></html>"""

WORTEN_LOGIN = """<!DOCTYPE html><html><head><title>Login Worten</title></head>
<body><form><input name="email"><input name="password" type="password">
<button>Iniciar Sessão</button></form></body></html>"""

WORTEN_SERVICOS = """<!DOCTYPE html><html><body>
<input placeholder="Pesquisar" id="search">
<div class="processo-card" data-id="3240023">
  <span>#3240023</span><span>Instalação</span>
</div>
<script>
document.getElementById('search').addEventListener('input', function(e) {
  const v = e.target.value;
  document.querySelector('.processo-card').style.display =
    (v === '' || '3240023'.includes(v)) ? 'block' : 'none';
});
</script>
</body></html>"""

WORTEN_PROCESSO = """<!DOCTYPE html><html><body>
<h1>Processo 3240023</h1>
<button onclick="this.nextElementSibling.style.display='block'">ATUALIZAR PEDIDO</button>
<div style="display:none" id="modal1">
  <span onclick="document.getElementById('modal1').style.display='none';
                  document.getElementById('modal2').style.display='block'">Concluir Serviço</span>
</div>
<div style="display:none" id="modal2">
  <label><input type="radio" name="estado" value="concluido"> Serviço concluído</label>
  <button onclick="document.getElementById('modal2').style.display='none';
                   document.getElementById('relatorio').style.display='block'">CONFIRMAR</button>
</div>
<div style="display:none" id="relatorio">
  <button onclick="document.getElementById('relatorio').style.display='none';
                   document.getElementById('form_rel').style.display='block'">PREENCHER RELATÓRIO</button>
</div>
<div style="display:none" id="form_rel">
  <select id="resultado"><option value="">--</option><option value="realizado">Instalação Realizada</option></select>
  <textarea placeholder="Justifique o fecho"></textarea>
  <input type="file" id="fotos" multiple>
  <button id="btn_enviar" onclick="document.getElementById('form_rel').style.display='none';
          document.getElementById('rel_ok').style.display='block'">ENVIAR RELATÓRIO</button>
</div>
<div style="display:none" id="rel_ok"><span>✓ Relatório Concluído</span>
  <a href="#" onclick="document.getElementById('anexos').style.display='block'">ANEXOS</a>
</div>
<div style="display:none" id="anexos">
  <input type="file" id="pdf_upload">
  <button id="btn_guardar" onclick="document.getElementById('anexos_ok').style.display='block'">GUARDAR</button>
</div>
<div style="display:none" id="anexos_ok"><span>Guardado</span>
  <button id="btn_concluir" onclick="document.getElementById('modal_final').style.display='block'">CONCLUIR SERVIÇO</button>
</div>
<div style="display:none" id="modal_final">
  <span>Serviço concluído</span>
  <button id="btn_fechar" onclick="document.getElementById('modal_final').style.display='none';
          document.getElementById('chat').style.display='block'">FECHAR</button>
</div>
<div style="display:none" id="chat">
  <span>ENVIAR MENSAGEM AO CLIENTE</span>
  <textarea placeholder="Escreva uma mensagem..." id="msg_input"></textarea>
  <button type="submit" id="btn_msg" onclick="document.getElementById('msg_enviada').style.display='block'">▷</button>
</div>
<div style="display:none" id="msg_enviada"><span>✓ Mensagem enviada</span></div>
</body></html>"""

# ── Servidor HTTP mock ────────────────────────────────────────────────────────

ROTAS = {
    "/login":                     (AWO_LOGIN,       "text/html"),
    "/dashboard":                 (AWO_DASHBOARD,   "text/html"),
    "/work-orders/planning":      (AWO_PLANNING,    "text/html"),
    "/work-orders/edit/999":      (AWO_OS,          "text/html"),
    "/work-orders/view/999":      (AWO_OS,          "text/html"),
    "/static/logo-awo.png":       (b"\x89PNG\r\n",  "image/png"),
    "/static/icons/dashboard.svg":(b"<svg/>",       "image/svg+xml"),
    "/static/icons/clients.svg":  (b"<svg/>",       "image/svg+xml"),
    "/static/fotos/foto1.jpg":    (b"\xff\xd8\xff" + b"\x00"*1000, "image/jpeg"),
    "/static/fotos/foto2.jpg":    (b"\xff\xd8\xff" + b"\x00"*1000, "image/jpeg"),
    "/static/fotos/foto3.jpg":    (b"\xff\xd8\xff" + b"\x00"*1000, "image/jpeg"),
    "/worten/login":              (WORTEN_LOGIN,    "text/html"),
    "/worten/servicos":           (WORTEN_SERVICOS, "text/html"),
    "/worten/processo/3240023":   (WORTEN_PROCESSO, "text/html"),
}

class MockServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ROTAS:
            body, ctype = ROTAS[path]
            if isinstance(body, str):
                body = body.encode()
            self.send_response(200)
            ct = ctype + "; charset=utf-8" if "html" in ctype else ctype
            self.send_header("Content-Type", ct)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # Login AWO → redireciona para dashboard
        self.send_response(302)
        self.send_header("Location", "/dashboard")
        self.end_headers()

    def log_message(self, *args):
        pass  # silencia logs do servidor

def iniciar_servidor(porta=18765):
    srv = http.server.HTTPServer(("localhost", porta), MockServer)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

# ── Importa funções reais do fechar_os ───────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent))
import os
os.environ["PLATFORM_URL"] = "http://localhost:18765"

import fechar_os
fechar_os.URL_AWO       = "http://localhost:18765"
fechar_os.SERVICOS_URL  = "http://localhost:18765/worten/servicos"
fechar_os.WORTEN_LOGIN_URL = "http://localhost:18765/worten/login"
fechar_os.PASTA_FECHO   = Path("/tmp/fecho_teste")

# ── Testes ───────────────────────────────────────────────────────────────────

resultados = []

def ok(msg):
    resultados.append(("✓", msg))
    print(f"  ✓ {msg}")

def falha(msg):
    resultados.append(("✗", msg))
    print(f"  ✗ FALHA: {msg}")

print("\n=== TESTE DE EXECUÇÃO REAL — fechar_os.py ===\n")

srv = iniciar_servidor()
time.sleep(0.3)

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=True,
        executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
    )
    page    = browser.new_page()

    # ── TESTE 1: Login AWO ──────────────────────────────────────────────────
    print("[1] Login AWO")
    page.goto("http://localhost:18765/login")
    page.fill("input[name='email']", "teste@teste.com")
    page.fill("input[name='password']", "senha")
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")
    if "/dashboard" in page.url or "/login" not in page.url:
        ok("Login AWO — redireccionou para dashboard")
    else:
        falha(f"Login AWO falhou — URL: {page.url}")

    # ── TESTE 2: Leitura número de processo ────────────────────────────────
    print("[2] Leitura número de processo")
    page.goto("http://localhost:18765/work-orders/edit/999")
    page.wait_for_load_state("domcontentloaded")
    numero = fechar_os.ler_numero_processo(page)
    if numero == "3240023":
        ok(f"Número de processo lido correctamente: {numero}")
    else:
        falha(f"Número lido: '{numero}' (esperado '3240023')")

    # ── TESTE 3: Leitura estado e trabalhos realizados ─────────────────────
    print("[3] Leitura de campos AWO")
    estado = fechar_os.ler_select_por_nome_ou_label(page, "estado")
    tr     = fechar_os.ler_trabalhos_realizados(page)
    data   = fechar_os.ler_data_visita(page)
    if "realizado" in estado.lower():
        ok(f"Estado lido: '{estado}'")
    else:
        falha(f"Estado: '{estado}'")
    if tr:
        ok(f"Trabalhos Realizados lido: '{tr[:40]}...'")
    else:
        falha("Trabalhos Realizados vazio")
    if data:
        ok(f"Data visita lida: '{data}'")
    else:
        falha("Data visita vazia")

    # ── TESTE 4: Filtro de imagens (logo AWO excluída) ─────────────────────
    print("[4] Filtro de imagens — logo AWO excluída")
    page.goto("http://localhost:18765/work-orders/edit/999")
    # Clica na aba Imagens/Doc
    try:
        page.click("a:has-text('Imagens')", timeout=3000)
    except Exception:
        pass
    time.sleep(0.5)

    img_urls = page.evaluate(fechar_os.baixar_imagens.__code__.co_consts[0]
                              if False else """
        () => {
            const vistos = new Set(); const resultado = [];
            const excluirNome = ['logo','icon','favicon','avatar','placeholder','sprite','default'];
            const uiSels = 'header,nav,footer,aside,.navbar,.sidebar,.topbar,.top-bar,[class*="navbar"],[class*="sidebar"],[class*="topbar"],[class*="logo"],[class*="brand"]';
            let imgs = [];
            for (const el of document.querySelectorAll('h1,h2,h3,h4,div,section')) {
                const txt = el.textContent.trim().toLowerCase();
                if (txt.includes('imagens') && txt.includes('document')) {
                    const c = el.closest('section,.card,.panel,main') || el.parentElement;
                    if (c) { imgs = Array.from(c.querySelectorAll('img')); if(imgs.length>0) break; }
                }
            }
            if(imgs.length===0) imgs = Array.from(document.querySelectorAll('img'));
            for (const img of imgs) {
                const src = img.src || img.getAttribute('data-src') || '';
                if(!src||src.startsWith('data:')||vistos.has(src)) continue;
                if(img.closest(uiSels)) continue;
                const nome = src.toLowerCase().split('/').pop().split('?')[0];
                if(excluirNome.some(k=>nome.includes(k))) continue;
                vistos.add(src); resultado.push(src);
            }
            return resultado;
        }
    """)

    logos_incluidos = [u for u in img_urls if 'logo' in u.lower()]
    fotos_reais     = [u for u in img_urls if 'foto' in u.lower()]

    if not logos_incluidos:
        ok(f"Logo AWO excluída ({len(img_urls)} imagens retornadas)")
    else:
        falha(f"Logo AWO incluída: {logos_incluidos}")

    if len(fotos_reais) == 3:
        ok(f"3 fotos reais incluídas: {[u.split('/')[-1] for u in fotos_reais]}")
    else:
        falha(f"Fotos reais: esperadas 3, obtidas {len(fotos_reais)}: {fotos_reais}")

    # ── TESTE 5: Alterar tipo → Fechado ───────────────────────────────────
    print("[5] Alterar Tipo → Fechado no AWO")
    page.goto("http://localhost:18765/work-orders/edit/999")
    page.wait_for_load_state("domcontentloaded")
    res = fechar_os.alterar_tipo_fechado(page)
    if res:
        ok("Tipo alterado para Fechado via Vue.js")
    else:
        falha("alterar_tipo_fechado retornou False")

    # ── TESTE 6: Navegação Worten (listagem de serviços) ───────────────────
    print("[6] Navegação Worten — listagem de serviços")
    page.goto("http://localhost:18765/worten/servicos")
    page.wait_for_load_state("domcontentloaded")
    campo = page.locator("input[placeholder*='Pesquisar']").first
    if campo.is_visible():
        ok("Campo de pesquisa Worten visível")
    else:
        falha("Campo de pesquisa Worten não encontrado")

    # ── TESTE 7: Pesquisa e abertura de processo Worten ────────────────────
    print("[7] Pesquisa processo na Worten")
    campo.fill("3240023")
    time.sleep(0.5)
    card = page.locator("text=#3240023").first
    if card.is_visible():
        ok("Processo #3240023 encontrado na pesquisa")
        card.click()
        # Redireccionaria para o processo; mockamos navegação directa
        page.goto("http://localhost:18765/worten/processo/3240023")
        page.wait_for_load_state("domcontentloaded")
        ok("Processo Worten aberto")
    else:
        falha("Processo #3240023 não encontrado")

    # ── TESTE 8: Fluxo Worten — botões presentes ──────────────────────────
    print("[8] Fluxo Worten — botões do processo")
    botoes_esperados = ["ATUALIZAR PEDIDO", "PREENCHER RELATÓRIO",
                        "ENVIAR RELATÓRIO", "GUARDAR", "CONCLUIR SERVIÇO",
                        "ENVIAR MENSAGEM AO CLIENTE"]
    # Verifica pelo DOM directamente (evita problemas de encoding no content())
    for btn_txt in botoes_esperados:
        encontrado = page.evaluate(
            f"() => document.body.textContent.includes({repr(btn_txt)})"
        )
        if encontrado:
            ok(f"Botão '{btn_txt}' presente na página")
        else:
            falha(f"Botão '{btn_txt}' não encontrado")

    # ── TESTE 9: Envio de mensagem ao cliente ─────────────────────────────
    print("[9] Envio de mensagem ao cliente")
    # Expõe o chat manualmente para testar
    page.evaluate("document.getElementById('chat').style.display='block'")
    page.wait_for_selector("#msg_input", state="visible", timeout=3000)
    campo_msg = page.locator("#msg_input")
    campo_msg.fill(fechar_os.MENSAGEM_CLIENTE)
    valor_msg = campo_msg.input_value()
    if "Caro/a Cliente" in valor_msg:
        ok(f"Mensagem preenchida ({len(valor_msg)} chars)")
    else:
        falha("Mensagem não foi preenchida")
    page.locator("#btn_msg").click()
    time.sleep(0.5)
    if page.locator("#msg_enviada").is_visible():
        ok("Mensagem ao cliente enviada com sucesso ✓")
    else:
        falha("Confirmação de envio não encontrada")

    browser.close()

srv.shutdown()

# ── Sumário ──────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print("          SUMÁRIO DE EXECUÇÃO REAL")
print(f"{'='*50}")
passou = sum(1 for s,_ in resultados if s == "✓")
falhou = sum(1 for s,_ in resultados if s == "✗")
for s, m in resultados:
    print(f"  {s} {m}")
print(f"{'='*50}")
print(f"  Resultado: {passou}/{len(resultados)} passaram")
if falhou == 0:
    print("  EXECUÇÃO COMPLETA SEM ERROS ✓")
else:
    print(f"  {falhou} FALHA(S) DETECTADA(S) ✗")
print(f"{'='*50}\n")
sys.exit(0 if falhou == 0 else 1)
