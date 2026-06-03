/**
 * Testa o filtro JS do fechar_os.py contra HTML que replica
 * a estrutura REAL do AWO-Soft (suporteprime.awo-soft.com)
 */
const { JSDOM } = require('jsdom');
const fs = require('fs');

const src = fs.readFileSync('fechar_os.py', 'utf8');
const match = src.match(/img_urls = page\.evaluate\("""\s*([\s\S]*?)\s*"""\s*\) or \[\]/) ||
              src.match(/img_urls = page\.evaluate\("""\s*([\s\S]*?)\s*"""\) or \[\]/);
if (!match) { console.error('Não encontrei o bloco JS'); process.exit(1); }
const JS_FILTRO = match[1];

// HTML que replica exactamente a estrutura do AWO-Soft visível no screenshot
const html = `<!DOCTYPE html><html><body>

  <!-- NAVBAR topo (logo AWO deve ser EXCLUÍDA) -->
  <nav class="navbar topbar">
    <img id="logo-awo"
         src="https://suporteprime.awo-soft.com/assets/img/logo-awo.png"
         data-w="120" data-h="40">
  </nav>

  <!-- SIDEBAR esquerda (ícones de navegação, devem ser EXCLUÍDOS) -->
  <aside class="sidebar">
    <img id="icon-dashboard"
         src="https://suporteprime.awo-soft.com/assets/icons/dashboard.svg"
         data-w="24" data-h="24">
    <img id="icon-clientes"
         src="https://suporteprime.awo-soft.com/assets/icons/clients.svg"
         data-w="24" data-h="24">
  </aside>

  <!-- CONTEÚDO PRINCIPAL -->
  <main>
    <!-- Tabs: Ficha | Periodicidade | Serviços | Custos | Imagens/Doc. | Intervenções -->
    <div id="tab_images">

      <!-- Secção "Imagens e Documentos" (estrutura real do AWO) -->
      <h2>Imagens e Documentos</h2>

      <div class="images-grid">
        <!-- 3 fotos reais de trabalho (devem ser INCLUÍDAS) -->
        <div>
          <p>Nome: .</p>
          <img id="foto1"
               src="https://suporteprime.awo-soft.com/storage/work-orders/14437/foto1.jpg"
               data-w="800" data-h="600">
        </div>
        <div>
          <p>Nome: .</p>
          <img id="foto2"
               src="https://suporteprime.awo-soft.com/storage/work-orders/14437/foto2.jpg"
               data-w="1200" data-h="900">
        </div>
        <div>
          <p>Nome: .</p>
          <img id="foto3"
               src="https://suporteprime.awo-soft.com/storage/work-orders/14437/foto3.jpg"
               data-w="1024" data-h="768">
        </div>
      </div>

    </div>
  </main>

</body></html>`;

const dom = new JSDOM(html, { runScripts: 'dangerously', url: 'https://suporteprime.awo-soft.com/work-orders/view/14437#tab_images' });
const { document: doc, Object: Obj } = dom.window;

// Simula naturalWidth/naturalHeight
doc.querySelectorAll('img').forEach(img => {
  const w = parseInt(img.getAttribute('data-w') || '0');
  const h = parseInt(img.getAttribute('data-h') || '0');
  Obj.defineProperty(img, 'naturalWidth',  { get: () => w, configurable: true });
  Obj.defineProperty(img, 'naturalHeight', { get: () => h, configurable: true });
});

const resultado = dom.window.eval(`(${JS_FILTRO})()`);

console.log('\n=== Teste filtro imagens AWO (estrutura real) ===\n');
console.log(`  Imagens na página : 5 (1 logo navbar + 2 ícones sidebar + 3 fotos)`);
console.log(`  Retornadas         : ${resultado.length}`);
resultado.forEach(u => console.log(`    ✓ ${u.split('/').slice(-2).join('/')}`));

let ok = true;

const temLogo = resultado.some(u => u.includes('logo-awo') || u.includes('logo'));
if (temLogo) { console.log('\n  ✗ FALHA: logo AWO incluída!'); ok = false; }
else          { console.log('\n  ✓ Logo AWO excluída (navbar)'); }

const temIcones = resultado.some(u => u.includes('icons/'));
if (temIcones) { console.log('  ✗ FALHA: ícones sidebar incluídos!'); ok = false; }
else           { console.log('  ✓ Ícones sidebar excluídos'); }

const fotos = resultado.filter(u => u.includes('storage/work-orders'));
if (fotos.length !== 3) {
  console.log(`  ✗ FALHA: esperadas 3 fotos, obtidas ${fotos.length}`);
  ok = false;
} else {
  console.log(`  ✓ ${fotos.length} fotos de trabalho incluídas`);
}

console.log(ok ? '\n  TODOS OS TESTES PASSARAM ✓\n' : '\n  ALGUNS TESTES FALHARAM ✗\n');
process.exit(ok ? 0 : 1);
