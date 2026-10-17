"""Ferramenta de QA isolada para testar extração de código postal e geocodificação.

Não altera o GPS do Android/BlueStacks nem interage com a MobiCTT.
Usa a Google Geocoding API com uma chave própria em GOOGLE_MAPS_API_KEY.

Uso (PowerShell):
    $env:GOOGLE_MAPS_API_KEY="A_TUA_CHAVE"
    python localizacao_teste.py "Rua Exemplo, 2775-305 Parede, Portugal"
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

POSTAL_CODE = re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{3})(?!\d)")
API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
LOG_FILE = Path(__file__).resolve().parent / "resultados_localizacao_teste.csv"


def extrair_codigo_postal(morada: str) -> str | None:
    """Extrai e normaliza um código postal português, se existir."""
    match = POSTAL_CODE.search(morada or "")
    return f"{match.group(1)}-{match.group(2)}" if match else None


def geocodificar(texto: str, *, codigo_postal: str | None = None) -> dict | None:
    """Geocodifica um código postal ou morada completa usando uma chave do utilizador."""
    chave = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not chave:
        raise RuntimeError("Define a variável de ambiente GOOGLE_MAPS_API_KEY com uma chave válida.")

    consulta = codigo_postal or texto.strip()
    params = {"address": consulta, "components": "country:PT", "key": chave, "region": "pt"}
    response = requests.get(API_URL, params=params, timeout=15)
    response.raise_for_status()
    dados = response.json()
    if dados.get("status") == "ZERO_RESULTS":
        return None
    if dados.get("status") != "OK" or not dados.get("results"):
        raise RuntimeError(f"Google Geocoding API devolveu: {dados.get('status', 'resposta inválida')}")

    item = dados["results"][0]
    loc = item["geometry"]["location"]
    return {
        "latitude": float(loc["lat"]),
        "longitude": float(loc["lng"]),
        "nome_resultado": item.get("formatted_address", ""),
        "tipo_resultado": ", ".join(item.get("types", [])),
        "origem_consulta": "codigo_postal" if codigo_postal else "morada_completa",
        "precisao": item.get("geometry", {}).get("location_type", "desconhecida"),
        "place_id": item.get("place_id", ""),
    }


def resolver_morada(morada: str) -> dict:
    """Tenta o código postal primeiro; sem resultado, tenta a morada completa."""
    morada = (morada or "").strip()
    if not morada:
        raise ValueError("A morada está vazia.")

    codigo_postal = extrair_codigo_postal(morada)
    if codigo_postal:
        resultado = geocodificar(morada, codigo_postal=codigo_postal)
        if resultado:
            return {"morada_recebida": morada, "codigo_postal": codigo_postal,
                    "estado": "coordenadas_encontradas", **resultado}

    resultado = geocodificar(morada)
    if resultado:
        return {"morada_recebida": morada, "codigo_postal": codigo_postal,
                "estado": "coordenadas_encontradas", **resultado}

    return {"morada_recebida": morada, "codigo_postal": codigo_postal,
            "estado": "localizacao_nao_encontrada", "latitude": None, "longitude": None,
            "origem_consulta": None, "precisao": None, "nome_resultado": ""}


def registar(resultado: dict) -> None:
    novo = not LOG_FILE.exists()
    with LOG_FILE.open("a", encoding="utf-8-sig", newline="") as ficheiro:
        writer = csv.DictWriter(
            ficheiro,
            fieldnames=["data", "morada_recebida", "codigo_postal", "estado",
                        "latitude", "longitude", "origem_consulta", "precisao", "nome_resultado"],
            delimiter=";",
            extrasaction="ignore",
        )
        if novo:
            writer.writeheader()
        writer.writerow({"data": datetime.now().isoformat(timespec="seconds"), **resultado})


def main() -> int:
    parser = argparse.ArgumentParser(description="Testa extração de código postal e geocodificação (sem alterar GPS).")
    parser.add_argument("morada", nargs="?", help="Morada devolvida pela aplicação")
    parser.add_argument("--morada", dest="morada_opcao", help="Morada devolvida pela aplicação")
    args = parser.parse_args()
    morada = args.morada_opcao or args.morada
    if not morada:
        parser.error("indica a morada como argumento.")
    try:
        resultado = resolver_morada(morada)
        registar(resultado)
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 1

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(f"Registo guardado em: {LOG_FILE}")
    return 0 if resultado["estado"] == "coordenadas_encontradas" else 2


if __name__ == "__main__":
    raise SystemExit(main())
