"""CLI para Leitura de Códigos de Chegada.

Uso:
    python ler_chegada.py caminho/para/imagem.jpg
    python ler_chegada.py imagem.png --saida resultado.json
"""

import argparse
import json
import mimetypes
import sys

from dotenv import load_dotenv

from ocr import ErroLeitura, ler_codigos


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Lê etiquetas, códigos de barras, QR codes e numerações de uma imagem."
    )
    parser.add_argument("imagem", help="Caminho para o ficheiro de imagem.")
    parser.add_argument(
        "--saida",
        "-o",
        help="Ficheiro onde gravar o JSON (por defeito imprime no ecrã).",
    )
    args = parser.parse_args()

    try:
        with open(args.imagem, "rb") as f:
            dados = f.read()
    except OSError as exc:
        print(f"Erro ao abrir a imagem: {exc}", file=sys.stderr)
        return 1

    mime, _ = mimetypes.guess_type(args.imagem)
    if not mime:
        mime = "image/jpeg"

    try:
        resultado = ler_codigos(dados, mime)
    except ErroLeitura as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    texto = json.dumps(resultado, ensure_ascii=False, indent=2)

    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as f:
            f.write(texto)
        print(f"Resultado gravado em {args.saida}")
    else:
        print(texto)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
