"""Ferramenta de teste isolada para validar geocodificação de moradas portuguesas.

Não altera o GPS do Android/BlueStacks nem interage com a MobiCTT.
Serve para testar a extração do código postal, a geocodificação e o registo
do resultado antes de integrar qualquer comportamento num ambiente de QA autorizado.

Uso:
    python localizacao_teste.py "Rua Exemplo, 2775-305 Parede, Portugal"
    python localizacao_teste.py --morada "Rua Exemplo, Lisboa, Portugal"
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

POSTAL_CODE = re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{3})(?!\d)")
API_URL = "https://nominatim.openstreetmap.org/search"
CACHE_FILE = Path(__file__).resolve().parent / "cache_geocodificacao.json"
LOG_FILE = Path(__file__).resolve().parent / "resultados_localizacao_teste.csv"
USER_AGENT = "CiTiTi-TestHarness/1.0 (geocoding QA; configure a contact address before production use)"


def extrair_codigo_postal(morada: str) -> str | None:
    """Extrai e normaliza um código postal português, se existir."""
    match = POSTAL_CODE.search(morada or "")
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _ler_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def geocodificar(texto: str, *, codigo_postal: str | None = None) -> dict | None:
    """Pesquisa uma localização; respeita o limite de 1 pedido/s e guarda resultados em cache.

    O resultado de um código postal pode ser o centro aproximado da área postal,
    não a porta exata. Quando disponível, a morada completa é mais específica.
    """
    consulta = f"postal:{codigo_postal}" if codigo_postal else f"address:{texto.strip()}"
    cache = _ler_cache()
    if consulta in cache:
        return cache[consulta]

    params = {
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "pt",
        "addressdetails": 1,
    }
    if codigo_postal:
        params["postalcode"] = codigo_postal
        params["country"] = "Portugal"
    else:
        params["q"] = texto.strip()
    headers = {"User-Agent": USER_AGENT}

    # Atraso conservador entre consultas para respeitar a política do serviço público.
    time.sleep(1.1)
    response = requests.get(API_URL, params=params, headers=headers, timeout=15)
    response.raise_for_status()
    resultados = response.json()
    if not resultados:
        return None

    item = resultados[0]
    resultado = {
        "latitude": float(item["lat"]),
        "longitude": float(item["lon"]),
        "nome_resultado": item.get("display_name", ""),
        "tipo_resultado": item.get("type", ""),
        "origem_consulta": "codigo_postal" if codigo_postal else "morada_completa",
        "precisao": "aproximada" if codigo_postal else "dependente_do_resultado",
        "atribuicao": "© OpenStreetMap contributors",
    }
    cache[consulta] = resultado
    _guardar_cache(cache)
    return resultado


def resolver_morada(morada: str) -> dict:
    """Tenta código postal primeiro e, se não houver resultado, tenta a morada completa."""
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
            "origem_consulta": None, "precisao": None}


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
    except (requests.RequestException, ValueError, KeyError) as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 1

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(f"Registo guardado em: {LOG_FILE}")
    print("Fonte de dados: © OpenStreetMap contributors (Nominatim).")
    return 0 if resultado["estado"] == "coordenadas_encontradas" else 2


if __name__ == "__main__":
    raise SystemExit(main())
