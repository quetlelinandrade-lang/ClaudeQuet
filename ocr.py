"""Leitura de Códigos de Chegada (OCR / Visão).

Recebe uma imagem, envia para o modelo de visão da Anthropic e devolve
as informações estruturadas em JSON de forma rigorosa. Campos não visíveis
ou ilegíveis ficam a ``null`` — nunca são inventados.
"""

import base64
import json
import os
import re

import anthropic

MODEL = os.environ.get("VISION_MODEL", "claude-sonnet-4-6")

# Tipos MIME aceites pela API de visão da Anthropic.
MIME_SUPORTADOS = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

# Esquema-alvo. Enviado ao modelo para garantir extracção consistente.
ESQUEMA_JSON = """{
  "resumo": {
    "total_etiquetas": 0,
    "total_codigos_barras": 0,
    "total_qrcodes": 0,
    "legibilidade_geral": "alta | media | baixa"
  },
  "etiquetas": [
    {
      "id": 1,
      "tipo_etiqueta": "envio | devolucao | interna | desconhecido",
      "transportadora": null,
      "codigo_chegada": null,
      "codigo_rastreio": null,
      "numero_ord": null,
      "codigos_barras": [
        { "simbologia": "code128 | ean13 | qr | desconhecido", "valor": null }
      ],
      "qrcodes": [
        { "valor": null }
      ],
      "numeracoes_impressas": [],
      "remetente": { "nome": null, "morada": null },
      "destinatario": { "nome": null, "morada": null },
      "data": null,
      "peso": null,
      "estado": null,
      "observacoes": null,
      "confianca": "alta | media | baixa"
    }
  ],
  "texto_bruto_detectado": null
}"""

SYSTEM_PROMPT = f"""És um sistema especializado em Leitura de Códigos de Chegada (OCR / Visão).

Analisa a imagem fornecida e localiza TODAS as etiquetas de envio, códigos de
barras, QR codes ou numerações impressas.

Extrai e estrutura rigorosamente as informações no formato JSON abaixo.

REGRAS OBRIGATÓRIAS:
- Responde APENAS com JSON válido. Sem texto antes ou depois, sem ```.
- Caso algum campo não esteja visível ou legível, preenche como null. NÃO inventes dados.
- Se não existir qualquer etiqueta/código, devolve "etiquetas": [] e preenche o resumo com zeros.
- Uma entrada em "etiquetas" por cada etiqueta física distinta.
- "codigo_chegada": o número principal usado para dar entrada/registar a chegada
  (ex.: nº ORD, nº de guia, nº de encomenda). Se ambíguo, usa o mais destacado.
- "numeracoes_impressas": qualquer numeração legível que não caiba nos outros campos.
- "texto_bruto_detectado": todo o texto legível na imagem, tal como aparece.
- "confianca" e "legibilidade_geral": avalia honestamente a qualidade da leitura.
- Datas no formato AAAA-MM-DD sempre que possível; caso contrário, mantém como impresso.

Formato JSON (respeita exactamente as chaves):
{ESQUEMA_JSON}
"""


class ErroLeitura(Exception):
    """Erro de negócio ao ler/analisar a imagem."""


def _cliente() -> anthropic.Anthropic:
    chave = os.environ.get("ANTHROPIC_API_KEY")
    if not chave:
        raise ErroLeitura(
            "ANTHROPIC_API_KEY não configurada. Define-a no ficheiro .env."
        )
    return anthropic.Anthropic(api_key=chave)


def _extrair_json(texto: str) -> dict:
    """Extrai o objecto JSON da resposta do modelo, tolerando ``` extra."""
    texto = texto.strip()
    # Remove cercas de código se o modelo as adicionar apesar das instruções.
    if texto.startswith("```"):
        texto = re.sub(r"^```[a-zA-Z]*\n?", "", texto)
        texto = re.sub(r"\n?```$", "", texto).strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # Última tentativa: apanhar o maior bloco { ... }.
        inicio = texto.find("{")
        fim = texto.rfind("}")
        if inicio != -1 and fim != -1 and fim > inicio:
            return json.loads(texto[inicio : fim + 1])
        raise ErroLeitura("O modelo não devolveu JSON válido.")


def ler_codigos(imagem_bytes: bytes, mime: str) -> dict:
    """Analisa a imagem e devolve o dicionário estruturado.

    Args:
        imagem_bytes: conteúdo binário da imagem.
        mime: tipo MIME (ex.: ``image/jpeg``).

    Returns:
        Dicionário no formato do :data:`ESQUEMA_JSON`.
    """
    if mime not in MIME_SUPORTADOS:
        raise ErroLeitura(
            f"Formato '{mime}' não suportado. Usa JPEG, PNG, GIF ou WEBP."
        )
    if not imagem_bytes:
        raise ErroLeitura("Imagem vazia.")

    imagem_b64 = base64.standard_b64encode(imagem_bytes).decode("ascii")
    cliente = _cliente()

    resposta = cliente.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": imagem_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Lê esta imagem e devolve o JSON estruturado "
                            "conforme as regras."
                        ),
                    },
                ],
            }
        ],
    )

    texto = ""
    for bloco in resposta.content:
        if bloco.type == "text":
            texto += bloco.text

    if not texto.strip():
        raise ErroLeitura("Resposta vazia do modelo.")

    return _extrair_json(texto)
