# Leitura de Códigos de Chegada (OCR / Visão)

Sistema online que analisa uma imagem, localiza **todas** as etiquetas de
envio, códigos de barras, QR codes e numerações impressas, e devolve a
informação estruturada em **JSON rigoroso**.

Campos não visíveis ou ilegíveis são devolvidos como `null` — **nenhum dado é
inventado**.

## Componentes

| Ficheiro | Função |
|----------|--------|
| `ocr.py` | Núcleo de visão (Anthropic). Recebe bytes da imagem, devolve o dicionário JSON. |
| `app.py` | Servidor web Flask (upload, câmara, drag-drop, colar). |
| `templates/index.html`, `static/` | Interface web. |
| `ler_chegada.py` | CLI para uso em scripts/lote. |

## Instalação

```bash
pip install -r requirements.txt
cp .env.example .env   # e preenche ANTHROPIC_API_KEY
```

## Usar via web

```bash
python app.py
# abre http://localhost:5000
```

Arrasta uma imagem, escolhe um ficheiro, tira uma foto (telemóvel) ou cola
(Ctrl+V). Clica em **Analisar imagem** para obter o JSON.

## Usar via linha de comandos

```bash
python ler_chegada.py etiqueta.jpg
python ler_chegada.py guia.png --saida resultado.json
```

## Formato de saída

```json
{
  "resumo": {
    "total_etiquetas": 1,
    "total_codigos_barras": 1,
    "total_qrcodes": 0,
    "legibilidade_geral": "alta"
  },
  "etiquetas": [
    {
      "id": 1,
      "tipo_etiqueta": "envio",
      "transportadora": null,
      "codigo_chegada": null,
      "codigo_rastreio": null,
      "numero_ord": null,
      "codigos_barras": [{ "simbologia": "code128", "valor": null }],
      "qrcodes": [],
      "numeracoes_impressas": [],
      "remetente": { "nome": null, "morada": null },
      "destinatario": { "nome": null, "morada": null },
      "data": null,
      "peso": null,
      "estado": null,
      "observacoes": null,
      "confianca": "alta"
    }
  ],
  "texto_bruto_detectado": null
}
```

## Configuração (variáveis de ambiente)

| Variável | Defeito | Descrição |
|----------|---------|-----------|
| `ANTHROPIC_API_KEY` | — | Obrigatória. |
| `VISION_MODEL` | `claude-sonnet-4-6` | Modelo de visão a usar. |
| `MAX_UPLOAD_MB` | `10` | Tamanho máximo do upload. |
| `PORT` | `5000` | Porta do servidor web. |
| `DEBUG` | — | `1` para modo debug do Flask. |

## Nota sobre códigos de barras / QR

A leitura é feita por visão do modelo, que extrai também os números legíveis
por baixo dos códigos. Para descodificação binária garantida (ex.: EAN-13),
pode adicionar-se `pyzbar`/`opencv` como melhoria futura.
