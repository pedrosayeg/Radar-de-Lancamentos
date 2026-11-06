"""Ajuda a descobrir o tipo de uma loja nova.

Uso: python -m radar.diagnostico https://site-da-editora.com.br
"""
from __future__ import annotations

import re
import sys

from . import http

TESTES = {
    "shopify": "/products.json?limit=1",
    "woocommerce": "/wp-json/wc/store/v1/products?per_page=1",
    "vtex": "/api/catalog_system/pub/products/search?_from=0&_to=0",
}


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    base = sys.argv[1].rstrip("/")
    for tipo, caminho in TESTES.items():
        try:
            r = http.baixar(base + caminho, tentativas=1)
            ok = r.status_code in (200, 206) and r.text.strip()[:1] in "[{"
            print(f"{tipo:12} {'FUNCIONA' if ok else 'não'} (HTTP {r.status_code})")
        except Exception as e:  # noqa: BLE001
            print(f"{tipo:12} erro: {e}")
    try:
        robots = http.texto(base + "/robots.txt", tentativas=1)
        mapas = re.findall(r"Sitemap:\s*(\S+)", robots, flags=re.I)
    except Exception:  # noqa: BLE001
        mapas = []
    mapas = mapas or [base + "/sitemap.xml"]
    for m in mapas[:3]:
        try:
            xml = http.texto(m, tentativas=1)
            n = len(re.findall(r"<loc>", xml))
            print(f"sitemap      {m}: {n} endereços{' (índice)' if '<sitemapindex' in xml else ''}")
        except Exception as e:  # noqa: BLE001
            print(f"sitemap      {m}: erro {e}")


if __name__ == "__main__":
    main()
