"""Leitura dos dados de uma página de produto (usada pelas fontes do tipo sitemap).

Procura, nesta ordem: dados estruturados JSON-LD (Product/Book), metatags Open Graph e o <h1>.
"""
from __future__ import annotations

import html
import json
import re

from . import http
from .coletores import limpar_html


def _meta(pagina: str, prop: str) -> str:
    for padrao in (
        rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']',
    ):
        m = re.search(padrao, pagina, flags=re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def _jsonld(pagina: str) -> list[dict]:
    blocos = []
    for bruto in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', pagina, flags=re.S | re.I):
        try:
            dado = json.loads(bruto.strip())
        except ValueError:
            continue
        pilha = dado if isinstance(dado, list) else [dado]
        while pilha:
            d = pilha.pop()
            if isinstance(d, dict):
                blocos.append(d)
                for v in d.values():
                    if isinstance(v, (list, dict)):
                        pilha.extend(v if isinstance(v, list) else [v])
            elif isinstance(d, list):
                pilha.extend(d)
    return blocos


def _nomes(valor) -> str:
    if not valor:
        return ""
    itens = valor if isinstance(valor, list) else [valor]
    nomes = [(i.get("name") if isinstance(i, dict) else str(i)) for i in itens]
    return ", ".join(n.strip() for n in nomes if n)


_genericas: dict[str, str] = {}


def _descricao_do_site(url: str) -> str:
    """Descrição da página inicial do site, usada para reconhecer textos genéricos."""
    raiz = re.sub(r"^(https?://[^/]+).*$", r"\1", url)
    if raiz not in _genericas:
        try:
            inicio = http.texto(raiz + "/", tentativas=1)
            _genericas[raiz] = limpar_html(_meta(inicio, "og:description") or _meta(inicio, "description"))
        except Exception:  # noqa: BLE001
            _genericas[raiz] = ""
    return _genericas[raiz]


def ler(url: str, fonte: dict) -> dict | None:
    pagina = http.texto(url)
    if len(pagina) < 500:
        raise RuntimeError("página vazia ou bloqueada")
    produto = next(
        (b for b in _jsonld(pagina) if str(b.get("@type", "")).lower() in ("product", "book")
         or (isinstance(b.get("@type"), list) and {"Product", "Book"} & set(b["@type"]))),
        {},
    )
    og_tipo = _meta(pagina, "og:type").lower()
    eh_produto = bool(produto) or any(t in og_tipo for t in ("product", "book")) or bool(
        re.search(r'(product:price:amount|itemprop=["\']price["\']|"@type"\s*:\s*"(Product|Book|Offer)")', pagina, flags=re.I))
    titulo = produto.get("name") or _meta(pagina, "og:title")
    if not titulo:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", pagina, flags=re.S | re.I)
        titulo = limpar_html(m.group(1), 300) if m else ""
    if not titulo:
        return None
    titulo = html.unescape(titulo)
    nome_fonte = re.escape(fonte["nome"].split(" (")[0])
    # Remove sufixos como " - Editora Todavia" ou " | Boitempo"
    titulo = re.sub(r"\s+[|\-–]\s+[^|\-–]*(" + nome_fonte + r"|editora)[^|\-–]*$", "", titulo, flags=re.I)
    autores = _nomes(produto.get("author"))
    if not autores:
        m = re.search(r",\s+de\s+([A-ZÀ-Ý][^,]{2,80})$", titulo)
        if m:
            autores, titulo = m.group(1).strip(), titulo[:m.start()]
    if not autores and " — " in titulo:
        # Formato "TÍTULO — Autor"
        titulo, autores = (p.strip() for p in titulo.rsplit(" — ", 1))
    if not autores:
        # Formato "TÍTULO - Sobrenome, Nome; Sobrenome, Nome"
        m = re.search(r"\s+-\s+([A-ZÀ-Ý][^\-–|]*?,\s*[A-ZÀ-Ý][^\-–|]*)$", titulo)
        if m:
            autores, titulo = m.group(1).strip(), titulo[:m.start()]

    imagem = produto.get("image")
    if isinstance(imagem, list):
        imagem = imagem[0] if imagem else ""
    if isinstance(imagem, dict):
        imagem = imagem.get("url", "")

    descricao = produto.get("description") or ""
    if len(limpar_html(descricao)) < 40:  # alguns sites põem números ou textos genéricos aqui
        descricao = _meta(pagina, "og:description") or _meta(pagina, "description") or descricao
    descricao = limpar_html(descricao)
    generica = _descricao_do_site(url)
    if len(descricao) < 40 or (generica and descricao[:60] == generica[:60]):
        descricao = ""
    return {
        "url": url,
        "titulo": titulo.strip(),
        "autores": autores,
        "editora": fonte.get("editora") or fonte["nome"],
        "descricao": descricao,
        "categorias": [c for c in [produto.get("category")] if isinstance(c, str)],
        "imagem": imagem or _meta(pagina, "og:image"),
        "data_lancamento": None,
        "eh_produto": eh_produto,
    }
