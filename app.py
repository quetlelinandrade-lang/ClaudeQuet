"""Sistema online para Leitura de Códigos de Chegada (OCR / Visão).

Servidor web Flask: carrega/captura uma imagem, envia para o módulo de
visão (:mod:`ocr`) e devolve o JSON estruturado.
"""

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from ocr import ErroLeitura, ler_codigos

load_dotenv()

app = Flask(__name__)

# Limite de tamanho do upload (10 MB por defeito).
app.config["MAX_CONTENT_LENGTH"] = int(
    os.environ.get("MAX_UPLOAD_MB", "10")
) * 1024 * 1024


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ler", methods=["POST"])
def api_ler():
    ficheiro = request.files.get("imagem")
    if ficheiro is None or ficheiro.filename == "":
        return jsonify({"erro": "Nenhuma imagem enviada."}), 400

    mime = ficheiro.mimetype or "application/octet-stream"
    imagem_bytes = ficheiro.read()

    try:
        resultado = ler_codigos(imagem_bytes, mime)
    except ErroLeitura as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - devolve erro legível ao cliente
        return jsonify({"erro": f"Falha ao processar: {exc}"}), 500

    return jsonify(resultado)


@app.route("/saude")
def saude():
    return jsonify(
        {
            "estado": "ok",
            "api_key_configurada": bool(os.environ.get("ANTHROPIC_API_KEY")),
        }
    )


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=porta, debug=os.environ.get("DEBUG") == "1")
