"""Ferramenta de teste para extrair um código postal português de uma morada.

Não usa APIs pagas, não altera o GPS e não interage com a MobiCTT/BlueStacks.
Quando possível, copia o código postal para a área de transferência do Windows.

Uso:
    python localizacao_teste.py "Rua de exemplo, 2775-002 Madorna, Portugal"
    python localizacao_teste.py --morada "Morada sem código postal"
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

POSTAL_CODE = re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{3})(?!\d)")
LOG_FILE = Path(__file__).resolve().parent / "resultados_localizacao_teste.csv"


def extrair_codigo_postal(morada: str) -> str | None:
    """Extrai e normaliza um código postal português, se existir."""
    match = POSTAL_CODE.search(morada or "")
    return f"{match.group(1)}-{match.group(2)}" if match else None


def copiar_para_area_transferencia(texto: str) -> bool:
    """Copia texto para o clipboard do Windows usando apenas a biblioteca padrão."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(texto)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def registar(resultado: dict) -> None:
    novo = not LOG_FILE.exists()
    with LOG_FILE.open("a", encoding="utf-8-sig", newline="") as ficheiro:
        writer = csv.DictWriter(
            ficheiro,
            fieldnames=["data", "morada_recebida", "codigo_postal", "estado", "copiado_clipboard"],
            delimiter=";",
            extrasaction="ignore",
        )
        if novo:
            writer.writeheader()
        writer.writerow({"data": datetime.now().isoformat(timespec="seconds"), **resultado})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrai um código postal português e tenta copiá-lo para a área de transferência."
    )
    parser.add_argument("morada", nargs="?", help="Morada recebida da aplicação")
    parser.add_argument("--morada", dest="morada_opcao", help="Morada recebida da aplicação")
    args = parser.parse_args()
    morada = (args.morada_opcao or args.morada or "").strip()
    if not morada:
        parser.error("indica a morada como argumento.")

    codigo_postal = extrair_codigo_postal(morada)
    if codigo_postal:
        copiado = copiar_para_area_transferencia(codigo_postal)
        resultado = {
            "morada_recebida": morada,
            "codigo_postal": codigo_postal,
            "estado": "codigo_postal_encontrado",
            "copiado_clipboard": copiado,
        }
        print(f"Código postal encontrado: {codigo_postal}")
        print("Copiado para a área de transferência." if copiado else
              "Não foi possível copiar automaticamente; copia o código acima.")
    else:
        resultado = {
            "morada_recebida": morada,
            "codigo_postal": None,
            "estado": "codigo_postal_nao_encontrado",
            "copiado_clipboard": False,
        }
        print("Não foi encontrado um código postal português na morada.")

    registar(resultado)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(f"Registo guardado em: {LOG_FILE}")
    return 0 if codigo_postal else 2


if __name__ == "__main__":
    raise SystemExit(main())
