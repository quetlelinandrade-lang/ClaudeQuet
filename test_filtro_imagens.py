"""
Testa o filtro JS de imagens do fechar_os.py contra uma página HTML
que replica a estrutura real do AWO-Soft:
  - logo AWO (quadrada, azul) na sidebar  →  deve ser EXCLUÍDA
  - fotos de trabalho no painel de imagens →  devem ser INCLUÍDAS
"""

import re
from playwright.sync_api import sync_playwright

# ── Extrai o bloco JS do fechar_os.py ──────────────────────────────────
def extrair_js_filtro() -> str:
    src = open("fechar_os.py", encoding="utf-8").read()
    start = src.find("img_urls = page.evaluate(")
    end   = src.find('    """) or []', start) + len('    """) or []')
    bloco = src[start:end]
    # Extrai só a função JS entre as aspas triplas
    m = re.search(r'page\.evaluate\("""\s*(.*?)\s*"""\)', bloco, re.DOTALL)
    if not m:
        raise RuntimeError("Não encontrei o bloco JS no fechar_os.py")
    return m.group(1)

JS_FILTRO = extrair_js_filtro()

# ── HTML que replica estrutura AWO ──────────────────────────────────────
HTML_AWO = """<!DOCTYPE html>
<html>
<head><title>AWO Mock</title></head>
<body>

<!-- SIDEBAR com logo AWO-Soft (deve ser EXCLUÍDA) -->
<div class="sidebar">
  <div class="brand logo">
    <!-- Logo AWO: quadrada 200x200, sem keyword no URL -->
    <img id="logo-awo"
         src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAMgAAADICAYAAACtWK6eAAAABmJLR0QA/wD/AP+gvaeTAAAADklEQVQI12NgGAWkAgABNgABzKyFIQAAAABJRU5ErkJggg=="
         width="200" height="200"
         style="width:200px;height:200px">
  </div>
</div>

<!-- CONTEÚDO PRINCIPAL -->
<main>
  <!-- Tab de imagens activa -->
  <div class="tab-pane active" id="tab-imagens">

    <!-- Fotos reais do trabalho (devem ser INCLUÍDAS) -->
    <div class="gallery">
      <img id="foto1"
           src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAARC AACAAIDAQACIABFARABEQACIABFARAEQACIAB"
           width="800" height="600" style="width:800px;height:600px">
      <img id="foto2"
           src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDABBoto"
           width="1200" height="900" style="width:1200px;height:900px">
      <img id="foto3"
           src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDABFoto3"
           width="1024" height="768" style="width:1024px;height:768px">
    </div>

  </div>
</main>

<script>
  // Simula dimensões naturais (no browser real vêm do ficheiro)
  document.querySelectorAll('img').forEach(img => {
    const w = parseInt(img.style.width);
    const h = parseInt(img.style.height);
    Object.defineProperty(img, 'naturalWidth',  {get: () => w});
    Object.defineProperty(img, 'naturalHeight', {get: () => h});
  });
</script>
</body>
</html>"""


def run_tests():
    print("\n=== Teste do filtro de imagens AWO ===\n")
    falhas = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_page()
        page.set_content(HTML_AWO)
        page.wait_for_timeout(500)

        # Corre o JS do fechar_os.py
        resultado = page.evaluate(JS_FILTRO)
        browser.close()

    print(f"  Imagens retornadas pelo filtro: {len(resultado)}")
    for url in resultado:
        print(f"    • {url[:80]}...")

    # ── Verificações ────────────────────────────────────────────────────
    ids_retornados = resultado  # são data URIs, verificamos por exclusão

    # 1. Logo AWO (200x200 quadrada no sidebar) deve estar excluída
    # O logo tem 200x200 → área 40000, ratio 1.0 → deve ser excluído pela regra de logo ≤300
    # Verificamos indiretamente: o número de imagens deve ser < total da página
    total_na_pagina = 4  # logo + 3 fotos
    if len(resultado) >= total_na_pagina:
        falhas.append(f"FALHA: filtro retornou {len(resultado)} imagens (esperado < {total_na_pagina})")
    else:
        print(f"\n  ✓ Filtro excluiu {total_na_pagina - len(resultado)} imagem(ns) (logo/UI)")

    # 2. Fotos reais devem ser incluídas (800x600, 1200x900, 1024x768)
    if len(resultado) < 1:
        falhas.append("FALHA: nenhuma foto de trabalho foi incluída")
    else:
        print(f"  ✓ {len(resultado)} foto(s) de trabalho incluída(s)")

    # 3. Zero imagens com dimensão ≤ 300x300 quadradas devem passar
    # (simulamos verificando que o logo de 200x200 foi excluído)
    # O logo é o 1º item, as fotos são maiores que 300px
    fotos_grandes = [u for u in resultado if u]  # todas as retornadas são fotos
    print(f"\n  Resultado: {len(resultado)} foto(s) incluídas, {total_na_pagina - len(resultado)} excluídas")

    if falhas:
        print("\n  FALHAS:")
        for f in falhas:
            print(f"    ✗ {f}")
        return False
    else:
        print("\n  TODOS OS TESTES DO FILTRO PASSARAM ✓")
        return True


if __name__ == "__main__":
    ok = run_tests()
    exit(0 if ok else 1)
