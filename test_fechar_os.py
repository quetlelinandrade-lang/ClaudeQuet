"""
Testes das correcções críticas do fechar_os.py

Testa sem browser real usando mocks:
  1. salvar_awo: falha NÃO bloqueia o processo para a Worten
  2. _navegar_para_listagem: segue o caminho correcto e imprime diagnóstico
  3. processar_os: status "ok" mesmo quando save falha
"""

import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass
from typing import Optional


# ── Stubs mínimos para importar fechar_os sem Playwright instalado ──
def _stub_playwright():
    pw = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    class _FakeTimeout(Exception): pass
    sync_api.TimeoutError = _FakeTimeout
    sync_api.sync_playwright = MagicMock()
    pw.sync_api = sync_api
    sys.modules.setdefault("playwright", pw)
    sys.modules.setdefault("playwright.sync_api", sync_api)
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    sys.modules.setdefault("dotenv", dotenv)

_stub_playwright()

import fechar_os
from fechar_os import DadosOS, salvar_awo, _navegar_para_listagem


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def make_page(click_succeeds_for=None, url="https://www.worten.pt/resolve/servicos"):
    """Cria um mock de page Playwright configurável."""
    page = MagicMock()
    page.url = url

    def _click(sel, timeout=None):
        if click_succeeds_for and any(k in sel for k in click_succeeds_for):
            return
        raise Exception(f"selector not found: {sel}")

    page.click.side_effect = _click

    locator_mock = MagicMock()
    locator_mock.first = MagicMock()
    locator_mock.first.is_visible.return_value = True
    locator_mock.first.click = MagicMock()
    locator_mock.first.wait_for = MagicMock()
    page.locator.return_value = locator_mock

    page.goto = MagicMock()
    page.wait_for_load_state = MagicMock()
    page.keyboard = MagicMock()
    page.evaluate = MagicMock(return_value="ok:")
    page.screenshot = MagicMock()
    return page


# ─────────────────────────────────────────────
# TESTE 1: salvar_awo falha → processo continua (não bloqueia)
# ─────────────────────────────────────────────

def test_save_falha_nao_bloqueia():
    """Se salvar_awo falhar, o processo deve ter status='ok' e ir para Worten."""

    # Simula page onde nenhum botão guardar existe
    page = make_page(click_succeeds_for=[])
    page.click.side_effect = Exception("botão não encontrado")
    page.locator.return_value.first.is_visible.return_value = False
    page.locator.return_value.all.return_value = []

    # Ctrl+S também falha
    page.keyboard.press.side_effect = Exception("keyboard not supported")

    resultado = salvar_awo(page)
    # Todos os métodos falharam → retorna False
    assert resultado == False, f"Esperado False quando tudo falha, obteve {resultado}"

    # Agora simula processar_os com save falhado
    dados = DadosOS(href="/work-orders/edit/999", texto="Teste OS")
    dados.numero_processo = "3240023"
    dados.data_visita = "01/06/2026"
    dados.trabalhos_realizados = "Instalação concluída"
    dados.status = "ok"

    # Verifica que o status não muda para "erro" quando save falha
    # (lógica do novo código: continua para Worten mesmo assim)
    page2 = make_page()
    page2.evaluate.return_value = "ok:Anderson silva → Fechado"

    mock_gerador = MagicMock()
    mock_gerador.gerar.return_value = Path("/tmp/3240023.pdf")

    with patch.object(fechar_os, 'salvar_awo', return_value=False), \
         patch.object(fechar_os, 'baixar_imagens', return_value=2), \
         patch.object(fechar_os, 'gerar_relatorio_txt'), \
         patch.object(fechar_os, 'alterar_tipo_fechado', return_value=True), \
         patch.object(fechar_os, 'ler_select_por_nome_ou_label', side_effect=["Realizado", "Anderson"]), \
         patch.object(fechar_os, 'ler_numero_processo', return_value="3240023"), \
         patch.object(fechar_os, 'ler_data_visita', return_value="01/06/2026"), \
         patch.object(fechar_os, 'ler_trabalhos_realizados', return_value="Instalação OK"), \
         patch('builtins.print'):
        d = fechar_os.processar_os(page2, {"href": "/work-orders/edit/999", "texto": "Teste"}, False, mock_gerador)
        assert d.status == "ok", f"FALHOU: status={d.status} motivo={d.motivo} — save falhar deve NÃO bloquear"

    print("  PASSOU: save falha → processo continua para Worten (status=ok)")


# ─────────────────────────────────────────────
# TESTE 2: _navegar_para_listagem imprime URL e confirma campo
# ─────────────────────────────────────────────

def test_navegacao_imprime_diagnostico(capsys=None):
    """_navegar_para_listagem deve imprimir URL actual e confirmar campo encontrado."""

    page = make_page(click_succeeds_for=["Menu", "Serviços", "Parceiro"])
    page.url = "https://www.worten.pt/resolve/servicos"

    printed = []
    original_print = print

    with patch('builtins.print', side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
        result = _navegar_para_listagem(page)

    # Deve ter imprimido o caminho de navegação
    all_output = "\n".join(printed)
    assert "Menu" in all_output or "worten" in all_output.lower(), \
        f"Esperado mensagem de navegação, obteve:\n{all_output}"

    # Deve ter imprimido o URL actual
    url_printed = any("URL" in p or "worten.pt" in p for p in printed)
    assert url_printed, f"URL actual não foi imprimido. Output:\n{all_output}"

    print(f"  PASSOU: navegação imprime diagnóstico ({len(printed)} mensagens)")
    return result


# ─────────────────────────────────────────────
# TESTE 3: Loop Worten usa contador [i/total]
# ─────────────────────────────────────────────

def test_loop_worten_tem_contador():
    """O loop da Worten deve mostrar [1/N] antes de cada processo."""
    src = open("fechar_os.py").read()
    assert "for i, d in enumerate(processos_para_worten, 1)" in src, \
        "Loop sem enumerate/contador"
    assert 'f"\\n  Worten [{i}/{len(processos_para_worten)}]:' in src or \
           "Worten [" in src, \
        "Mensagem de progresso não encontrada"
    print("  PASSOU: loop Worten tem contador [i/total]")


# ─────────────────────────────────────────────
# TESTE 4: salvar_awo tenta Ctrl+S como fallback
# ─────────────────────────────────────────────

def test_save_tenta_ctrl_s():
    """salvar_awo deve tentar Ctrl+S quando não encontra botão."""
    page = make_page()
    page.click.side_effect = Exception("not found")
    page.locator.return_value.first.is_visible.return_value = False
    page.locator.return_value.all.return_value = []
    page.keyboard.press = MagicMock(return_value=None)

    with patch('builtins.print'):
        salvar_awo(page)

    page.keyboard.press.assert_called_with("Control+s")
    print("  PASSOU: salvar_awo tenta Ctrl+S como fallback")


# ─────────────────────────────────────────────
# TESTE 5: filtro de imagens exclui logo AWO
# ─────────────────────────────────────────────

def test_filtro_exclui_logo_awo():
    """A query JS deve excluir imagens com 'awo' no URL e imagens pequenas."""
    src = open("fechar_os.py").read()
    start = src.find("img_urls = page.evaluate")
    end   = src.find("or []", start) + 5
    bloco = src[start:end]

    assert "excluirNome" in bloco or "awo" in bloco, "Filtro de nome de ficheiro não encontrado"
    assert "logo" in bloco,         "Filtro 'logo' não encontrado"
    assert any(x in bloco for x in ["< 100", "< 80", "< 120"]), "Filtro de tamanho mínimo não encontrado"
    assert any(x in bloco for x in ["excluirUrl.some", "excluir.some", "excluirNome.some"]), \
        "Lógica de exclusão por nome de ficheiro não encontrada"

    print("  PASSOU: filtro JS exclui logo AWO, logos e imagens pequenas")


# ─────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────

if __name__ == "__main__":
    testes = [
        ("Save falha não bloqueia processo",     test_save_falha_nao_bloqueia),
        ("Navegação imprime diagnóstico",          test_navegacao_imprime_diagnostico),
        ("Loop Worten tem contador [i/total]",    test_loop_worten_tem_contador),
        ("salvar_awo tenta Ctrl+S como fallback", test_save_tenta_ctrl_s),
        ("Filtro exclui logo AWO das fotos",      test_filtro_exclui_logo_awo),
    ]

    falhas = 0
    print("\n=== Testes fechar_os.py ===\n")
    for nome, fn in testes:
        print(f"[{nome}]")
        try:
            fn()
        except AssertionError as e:
            print(f"  FALHOU: {e}")
            falhas += 1
        except Exception as e:
            print(f"  ERRO inesperado: {e}")
            falhas += 1
        print()

    print(f"{'='*40}")
    print(f"Resultado: {len(testes)-falhas}/{len(testes)} passaram")
    if falhas:
        print("ALGUNS TESTES FALHARAM")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM ✓")
