"""Acesso HTTP com cabeçalhos de navegador, novas tentativas e pausa entre requisições."""
from __future__ import annotations

import gzip
import time
from urllib.parse import urlparse

import requests

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 RadarDeLancamentos/1.0"
)

_sessao = requests.Session()
_sessao.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
_ultimo_acesso: dict[str, float] = {}
PAUSA_POR_HOST = 1.0  # segundos entre requisições ao mesmo site


def _esperar(url: str) -> None:
    host = urlparse(url).netloc
    agora = time.monotonic()
    falta = PAUSA_POR_HOST - (agora - _ultimo_acesso.get(host, 0))
    if falta > 0:
        time.sleep(falta)
    _ultimo_acesso[host] = time.monotonic()


def baixar(url: str, tentativas: int = 3, timeout: int = 40, **kw) -> requests.Response:
    """GET com até `tentativas` tentativas. Levanta exceção se todas falharem."""
    erro: Exception | None = None
    for i in range(tentativas):
        _esperar(url)
        try:
            r = _sessao.get(url, timeout=timeout, **kw)
            if r.status_code == 429:
                espera = r.headers.get("Retry-After", "")
                time.sleep(min(int(espera), 90) if espera.isdigit() else 20 * (i + 1))
                raise requests.HTTPError("HTTP 429 (limite de acessos do site)")
            if r.status_code in (500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            # Alguns servidores devolvem corpo vazio de forma intermitente
            if r.status_code == 200 and not r.content:
                raise requests.HTTPError("resposta vazia")
            return r
        except Exception as e:  # noqa: BLE001
            erro = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"falha ao acessar {url}: {erro}")


def texto(url: str, **kw) -> str:
    r = baixar(url, **kw)
    r.raise_for_status()
    conteudo = r.content
    if conteudo[:2] == b"\x1f\x8b":
        conteudo = gzip.decompress(conteudo)
    try:
        return conteudo.decode("utf-8").lstrip("﻿")
    except UnicodeDecodeError:
        return conteudo.decode(r.encoding or "latin-1", errors="replace")


def json(url: str, **kw):
    r = baixar(url, **kw)
    r.raise_for_status()
    return r.json()
