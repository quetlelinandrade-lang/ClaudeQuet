"use strict";

const dropzone = document.getElementById("dropzone");
const inputFicheiro = document.getElementById("input-ficheiro");
const inputCamera = document.getElementById("input-camera");
const btnEscolher = document.getElementById("btn-escolher");
const btnCamera = document.getElementById("btn-camera");
const previa = document.getElementById("previa");
const imgPrevia = document.getElementById("img-previa");
const btnAnalisar = document.getElementById("btn-analisar");
const btnLimpar = document.getElementById("btn-limpar");
const btnCopiar = document.getElementById("btn-copiar");
const estado = document.getElementById("estado");
const resumo = document.getElementById("resumo");
const saida = document.getElementById("saida");

let ficheiroSelecionado = null;

function selecionarFicheiro(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    definirEstado("O ficheiro tem de ser uma imagem.", "falha");
    return;
  }
  ficheiroSelecionado = file;
  imgPrevia.src = URL.createObjectURL(file);
  dropzone.classList.add("oculto");
  previa.classList.remove("oculto");
  definirEstado("");
}

function limpar() {
  ficheiroSelecionado = null;
  inputFicheiro.value = "";
  inputCamera.value = "";
  previa.classList.add("oculto");
  dropzone.classList.remove("oculto");
  resumo.classList.add("oculto");
  resumo.innerHTML = "";
  saida.textContent = "Aguardando imagem…";
  btnCopiar.disabled = true;
  definirEstado("");
}

function definirEstado(texto, classe) {
  estado.className = "estado" + (classe ? " " + classe : "");
  estado.innerHTML = texto;
}

// --- Eventos de escolha de ficheiro ---
btnEscolher.addEventListener("click", () => inputFicheiro.click());
btnCamera.addEventListener("click", () => inputCamera.click());
inputFicheiro.addEventListener("change", (e) => selecionarFicheiro(e.target.files[0]));
inputCamera.addEventListener("change", (e) => selecionarFicheiro(e.target.files[0]));
dropzone.addEventListener("click", () => inputFicheiro.click());

// --- Drag & drop ---
["dragover", "dragenter"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("arrastando");
  })
);
["dragleave", "dragend"].forEach((ev) =>
  dropzone.addEventListener(ev, () => dropzone.classList.remove("arrastando"))
);
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("arrastando");
  if (e.dataTransfer.files.length) selecionarFicheiro(e.dataTransfer.files[0]);
});

// Colar imagem (Ctrl+V)
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) =>
    i.type.startsWith("image/")
  );
  if (item) selecionarFicheiro(item.getAsFile());
});

btnLimpar.addEventListener("click", limpar);

// --- Análise ---
btnAnalisar.addEventListener("click", async () => {
  if (!ficheiroSelecionado) return;

  btnAnalisar.disabled = true;
  btnCopiar.disabled = true;
  resumo.classList.add("oculto");
  definirEstado('<span class="spinner"></span>A analisar imagem…', "a-processar");
  saida.textContent = "";

  const dados = new FormData();
  dados.append("imagem", ficheiroSelecionado);

  try {
    const resp = await fetch("/api/ler", { method: "POST", body: dados });
    const json = await resp.json();

    if (!resp.ok) {
      definirEstado("Erro: " + (json.erro || resp.statusText), "falha");
      saida.textContent = JSON.stringify(json, null, 2);
      return;
    }

    saida.textContent = JSON.stringify(json, null, 2);
    btnCopiar.disabled = false;
    mostrarResumo(json);
    definirEstado("Leitura concluída.", "sucesso");
  } catch (err) {
    definirEstado("Falha de rede: " + err.message, "falha");
  } finally {
    btnAnalisar.disabled = false;
  }
});

function mostrarResumo(json) {
  const r = json.resumo || {};
  const chips = [
    ["Etiquetas", r.total_etiquetas],
    ["Códigos de barras", r.total_codigos_barras],
    ["QR codes", r.total_qrcodes],
    ["Legibilidade", r.legibilidade_geral],
  ];
  resumo.innerHTML = chips
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `<span class="chip">${k}: <b>${v}</b></span>`)
    .join("");
  resumo.classList.remove("oculto");
}

// --- Copiar ---
btnCopiar.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(saida.textContent);
    const original = btnCopiar.textContent;
    btnCopiar.textContent = "Copiado ✓";
    setTimeout(() => (btnCopiar.textContent = original), 1500);
  } catch {
    definirEstado("Não foi possível copiar.", "falha");
  }
});
