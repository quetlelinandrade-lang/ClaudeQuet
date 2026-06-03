/**
 * Testa o filtro JS do fechar_os.py contra uma página que replica
 * a estrutura real do AWO-Soft (logo quadrada + fotos de trabalho)
 */
const { JSDOM } = require('jsdom');
const fs = require('fs');

// ── Extrai o bloco JS do fechar_os.py ─────────────────────────────────
const src = fs.readFileSync('fechar_os.py', 'utf8');
const match = src.match(/img_urls = page\.evaluate\("""\s*([\s\S]*?)\s*"""\s*\) or \[\]/) ||
              src.match(/img_urls = page\.evaluate\("""\s*([\s\S]*?)\s*"""\) or \[\]/);
if (!match) { console.error('Não encontrei o bloco JS'); process.exit(1); }
const JS_FILTRO = match[1];

// ── HTML que replica estrutura AWO-Soft ───────────────────────────────
const html = `<!DOCTYPE html><html><body>
  <!-- Logo AWO-Soft na sidebar (DEVE SER EXCLUÍDA) -->
  <aside class="sidebar brand logo">
    <img id="logo-awo" src="https://app.awo-soft.com/assets/logo.png"
         data-w="200" data-h="200">
  </aside>

  <!-- Cabeçalho com logo (DEVE SER EXCLUÍDA) -->
  <header>
    <img id="logo-header" src="https://app.awo-soft.com/img/awosoft-brand.svg"
         data-w="150" data-h="80">
  </header>

  <!-- Painel activo da tab de Imagens (DEVEM SER INCLUÍDAS) -->
  <main>
    <div class="tab-pane active" id="tab-imagens">
      <div class="gallery">
        <img id="foto1" src="https://app.awo-soft.com/storage/uploads/foto_trabalho_1.jpg"
             data-w="1200" data-h="900">
        <img id="foto2" src="https://app.awo-soft.com/storage/uploads/foto_trabalho_2.jpg"
             data-w="800" data-h="600">
        <img id="foto3" src="https://app.awo-soft.com/storage/uploads/foto_trabalho_3.jpg"
             data-w="1024" data-h="768">
      </div>
    </div>
  </main>
</body></html>`;

const dom = new JSDOM(html, { runScripts: 'dangerously' });
const { document, Object: Obj } = dom.window;

// Simula naturalWidth/naturalHeight via data attributes
document.querySelectorAll('img').forEach(img => {
  const w = parseInt(img.getAttribute('data-w') || '0');
  const h = parseInt(img.getAttribute('data-h') || '0');
  Obj.defineProperty(img, 'naturalWidth',  { get: () => w, configurable: true });
  Obj.defineProperty(img, 'naturalHeight', { get: () => h, configurable: true });
});

// Corre o filtro JS
const fn   = new dom.window.Function(JS_FILTRO.replace(/^\s*\(\)\s*=>\s*\{/, '').replace(/\}$/, '').replace(/return resultado;/, 'return resultado;'));
// Usa eval via jsdom para correr a arrow function completa
const resultado = dom.window.eval(`(${JS_FILTRO})()`);

// ── Verificações ──────────────────────────────────────────────────────
console.log('\n=== Teste do filtro de imagens AWO ===\n');
console.log(`  Total imagens na página: 5`);
console.log(`  Retornadas pelo filtro : ${resultado.length}`);
resultado.forEach(u => console.log(`    ✓ ${u}`));

let ok = true;

// Logo AWO (sidebar.brand.logo, 200x200 quadrada) deve ser excluída
const temLogoAwo = resultado.includes('https://app.awo-soft.com/assets/logo.png');
if (temLogoAwo) {
  console.log('\n  ✗ FALHA: logo AWO-Soft (200x200 quadrada) foi incluída!');
  ok = false;
} else {
  console.log('\n  ✓ Logo AWO-Soft excluída correctamente');
}

// Logo do header deve ser excluída
const temLogoHeader = resultado.includes('https://app.awo-soft.com/img/awosoft-brand.svg');
if (temLogoHeader) {
  console.log('  ✗ FALHA: logo do header foi incluída!');
  ok = false;
} else {
  console.log('  ✓ Logo do header excluída correctamente');
}

// 3 fotos de trabalho devem ser incluídas
const fotos = resultado.filter(u => u.includes('/storage/uploads/'));
if (fotos.length !== 3) {
  console.log(`  ✗ FALHA: esperadas 3 fotos de trabalho, obtidas ${fotos.length}`);
  ok = false;
} else {
  console.log(`  ✓ ${fotos.length} fotos de trabalho incluídas correctamente`);
}

console.log(ok
  ? '\n  TODOS OS TESTES PASSARAM ✓\n'
  : '\n  ALGUNS TESTES FALHARAM ✗\n');
process.exit(ok ? 0 : 1);
