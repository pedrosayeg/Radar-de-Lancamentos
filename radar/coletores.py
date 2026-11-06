"""Coletores por tipo de loja. Cada um devolve uma lista de livros (dicionários) com os campos:

    url, titulo, autores, editora, descricao, categorias, imagem, data_lancamento

`data_lancamento` é uma data ISO (AAAA-MM-DD) quando a loja informa, ou None.
Coletores do tipo sitemap devolvem apenas a URL e o campo `precisa_detalhe=True`;
os detalhes são lidos depois, só para as URLs novas (ver detalhes.py).
"""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import urljoin

from . import http


def limpar_html(t: str | None, limite: int = 600) -> str:
    if not t:
        return ""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limite].rsplit(" ", 1)[0] + "…" if len(t) > limite else t


def _data(valor: str | None) -> str | None:
    if not valor:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(valor))
    return m.group(1) if m else None


# ---------------------------------------------------------------- Shopify
def shopify(fonte: dict) -> list[dict]:
    base = fonte["url"].rstrip("/")
    livros = []
    for pagina in range(1, 5):  # até 1000 produtos, do mais novo para o mais antigo na maioria das lojas
        dados = http.json(f"{base}/products.json?limit=250&page={pagina}")
        produtos = dados.get("products", [])
        if not produtos:
            break
        for p in produtos:
            imagens = p.get("images") or []
            livros.append({
                "url": f"{base}/products/{p['handle']}",
                "titulo": p.get("title", "").strip(),
                "autores": "",
                "editora": p.get("vendor") or fonte["nome"],
                "descricao": limpar_html(p.get("body_html")),
                "categorias": [c for c in [p.get("product_type")] + list(p.get("tags") or []) if c],
                "imagem": imagens[0]["src"] if imagens else "",
                "data_lancamento": _data(p.get("published_at") or p.get("created_at")),
            })
        if len(produtos) < 250:
            break
    return livros


# ---------------------------------------------------------------- WooCommerce
def woocommerce(fonte: dict) -> list[dict]:
    base = fonte["url"].rstrip("/")
    livros = []
    for pagina in (1, 2):  # os 100 produtos mais recentes
        dados = http.json(
            f"{base}/wp-json/wc/store/v1/products?per_page=50&page={pagina}&orderby=date&order=desc"
        )
        if not dados:
            break
        for p in dados:
            if p.get("type") not in (None, "simple", "variable", "external"):
                continue
            autores, editora = [], fonte["nome"]
            for a in p.get("attributes") or []:
                nome = (a.get("name") or "").lower()
                termos = [t.get("name", "") for t in a.get("terms") or []]
                if "autor" in nome or "author" in nome:
                    autores += termos
                elif "editora" in nome and termos:
                    editora = termos[0]
            imagens = p.get("images") or []
            livros.append({
                "url": p.get("permalink"),
                "titulo": html.unescape(p.get("name", "")).strip(),
                "autores": ", ".join(autores),
                "editora": editora,
                "descricao": limpar_html(p.get("short_description") or p.get("description")),
                "categorias": [html.unescape(c.get("name", "")) for c in p.get("categories") or []],
                "imagem": imagens[0].get("src", "") if imagens else "",
                "data_lancamento": None,
            })
        if len(dados) < 50:
            break
    return livros


# ---------------------------------------------------------------- VTEX
def _juntar_autores(valores: list[str]) -> str:
    nomes: dict[str, str] = {}
    for v in valores:
        for n in re.split(r"[,;]", v or ""):
            n = re.sub(r"\s+", " ", n).strip()
            chave = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", n.lower()).encode("ascii", "ignore").decode())
            if n and chave not in nomes:
                nomes[chave] = n
    return ", ".join(nomes.values())


def vtex(fonte: dict) -> list[dict]:
    base = fonte["url"].rstrip("/")
    livros = []
    for inicio in (0, 50):
        dados = http.json(
            f"{base}/api/catalog_system/pub/products/search?O=OrderByReleaseDateDESC&_from={inicio}&_to={inicio + 49}"
        )
        for p in dados:
            autores = []
            for chave in ("Autor 1", "Autor 2", "Autor 3", "Autor", "Autores", "Autor(es)"):
                v = p.get(chave)
                if v:
                    autores += v if isinstance(v, list) else [v]
            classif = []
            for chave in ("Classificação principal BISAC", "Outras classificações BISAC",
                          "Classificação principal Thema", "Outras classificações Thema", "Palavra-chave"):
                v = p.get(chave)
                if v:
                    classif += v if isinstance(v, list) else [v]
            imagem = ""
            try:
                imagem = p["items"][0]["images"][0]["imageUrl"]
            except (KeyError, IndexError, TypeError):
                pass
            livros.append({
                "url": p.get("link") or urljoin(base + "/", f"{p.get('linkText')}/p"),
                "titulo": (p.get("productName") or "").strip(),
                "autores": _juntar_autores(autores),
                "editora": p.get("brand") or fonte["nome"],
                "descricao": limpar_html(p.get("description") or p.get("metaTagDescription")),
                "categorias": [c.strip("/") for c in p.get("categories") or []] + classif,
                "imagem": imagem,
                "data_lancamento": _data(p.get("releaseDate")),
            })
        if len(dados) < 50:
            break
    return livros


# ---------------------------------------------------------------- Sitemap
def _locs(xml: str) -> list[str]:
    return [html.unescape(u.strip()) for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml, flags=re.S)]


def sitemap(fonte: dict) -> list[dict]:
    """Lista as URLs de produto do sitemap. Os detalhes são lidos só para URLs novas."""
    incluir = re.compile(fonte["incluir_url"]) if fonte.get("incluir_url") else None
    excluir = re.compile(fonte["excluir_url"]) if fonte.get("excluir_url") else None
    filtros_sub = [s.lower() for s in fonte.get("sitemaps_incluir") or []]

    urls: list[str] = []
    fila, vistos = [fonte["url"]], set()
    while fila and len(vistos) < 60:
        atual = fila.pop(0)
        if atual in vistos:
            continue
        vistos.add(atual)
        xml = http.texto(atual)
        if "<sitemapindex" in xml:
            for sub in _locs(xml):
                if not filtros_sub or any(f in sub.lower() for f in filtros_sub):
                    fila.append(sub)
            continue
        urls += _locs(xml)

    if not urls:
        raise RuntimeError("sitemap sem URLs (o site pode ter mudado ou bloqueado o acesso)")

    raiz = re.sub(r"^(https?://[^/]+).*$", r"\1", fonte["url"])
    saida = []
    for u in dict.fromkeys(urls):
        caminho = u[len(raiz):] if u.startswith(raiz) else re.sub(r"^https?://[^/]+", "", u)
        if caminho in ("", "/"):
            continue
        if incluir and not incluir.search(u):
            continue
        if excluir and excluir.search(caminho):
            continue
        saida.append({"url": u, "precisa_detalhe": True})
    return saida


# ---------------------------------------------------------------- Páginas de vitrine
def pagina(fonte: dict) -> list[dict]:
    """Para sites sem sitemap útil. Lê uma ou mais páginas (em geral a inicial ou a de lançamentos)
    e pega os links de produto que casam com `incluir_url`. Os detalhes são lidos só para links novos."""
    if not fonte.get("incluir_url"):
        raise RuntimeError("fonte do tipo pagina precisa de incluir_url")
    incluir = re.compile(fonte["incluir_url"])
    excluir = re.compile(fonte["excluir_url"]) if fonte.get("excluir_url") else None
    saida: dict[str, dict] = {}
    for endereco in fonte.get("paginas") or [fonte["url"]]:
        conteudo = http.texto(endereco)
        for href in re.findall(r'href=["\']([^"\'#]+)["\']', conteudo):
            url = urljoin(endereco, html.unescape(href)).split("?")[0]
            if incluir.search(url) and not (excluir and excluir.search(url)):
                saida.setdefault(url, {"url": url, "precisa_detalhe": True})
    if not saida:
        raise RuntimeError("nenhum link de produto encontrado na página (o site pode ter mudado)")
    return list(saida.values())


COLETORES = {
    "pagina": pagina,
    "shopify": shopify,
    "woocommerce": woocommerce,
    "vtex": vtex,
    "sitemap": sitemap,
}
