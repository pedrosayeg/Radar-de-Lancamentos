"""Geração do site estático (pasta docs/, publicada pelo GitHub Pages) e dos feeds RSS."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import unicodedata
from email.utils import format_datetime
from pathlib import Path

MODELO = Path(__file__).with_name("modelo_site.html")
CAMPOS = ("titulo", "autores", "editora", "url", "imagem", "descricao", "areas", "data_lancamento", "visto_em")


def _slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _rss(livros: list[dict], titulo: str, link: str) -> str:
    e = html.escape
    itens = []
    for l in livros[:100]:
        data = dt.datetime.fromisoformat(l["visto_em"] + "T09:00:00-03:00")
        autores = f'{l["autores"]} · ' if l.get("autores") else ""
        itens.append(
            f"<item><title>{e(l['titulo'])}</title><link>{e(l['url'])}</link><guid isPermaLink=\"true\">{e(l['url'])}</guid>"
            f"<pubDate>{format_datetime(data)}</pubDate>"
            f"<description>{e(autores + (l.get('editora') or '') + '. ' + (l.get('descricao') or ''))}</description>"
            + "".join(f"<category>{e(a)}</category>" for a in l.get("areas") or [])
            + "</item>"
        )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            f"<title>{e(titulo)}</title><link>{e(link)}</link><description>{e(titulo)}</description>"
            f"<language>pt-br</language>{''.join(itens)}</channel></rss>\n")


def gerar(catalogo: list[dict], estado: dict, config: dict, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "feeds").mkdir(exist_ok=True)
    (destino / ".nojekyll").write_text("")

    publico = [{k: l.get(k) for k in CAMPOS} for l in catalogo]
    (destino / "livros.json").write_text(json.dumps(publico, ensure_ascii=False), encoding="utf-8")

    e = html.escape
    linhas = []
    for nome, s in sorted(estado.get("fontes", {}).items()):
        situacao = "ok" if not s.get("falhas_seguidas") else f"falhou {s['falhas_seguidas']}x"
        linhas.append(f"<tr><td>{e(nome)}</td><td>{e(situacao)}</td><td>{e(s.get('ultima_ok') or '-')}</td></tr>")
    tabela = ("<table><tr><th>Editora</th><th>Situação</th><th>Última leitura ok</th></tr>" + "".join(linhas) + "</table>"
              if linhas else "<p>Ainda não houve leitura.</p>")

    inscricao = config.get("url_inscricao") or ""
    botao = (f'<a class="principal" href="{e(inscricao)}" target="_blank" rel="noopener">Receber por e-mail</a>'
             if inscricao else '<a class="principal" href="#" onclick="alert(\'Inscrição por e-mail em breve.\');return false">Receber por e-mail</a>')

    pagina = (MODELO.read_text(encoding="utf-8")
              .replace("__TITULO__", e(config["titulo"]))
              .replace("__DESCRICAO__", e(config["descricao"]))
              .replace("__BOTAO_INSCRICAO__", botao)
              .replace("__ATUALIZADO__", e(estado.get("ultima_execucao", "-").replace("T", " às ")))
              .replace("__TABELA_FONTES__", tabela)
              .replace("__AREAS_JSON__", json.dumps(config["areas"], ensure_ascii=False)))
    (destino / "index.html").write_text(pagina, encoding="utf-8")

    url = config.get("url_site", "")
    (destino / "feeds" / "todos.xml").write_text(_rss(catalogo, config["titulo"], url), encoding="utf-8")
    for area in config["areas"]:
        da_area = [l for l in catalogo if area in (l.get("areas") or [])]
        (destino / "feeds" / f"{_slug(area)}.xml").write_text(
            _rss(da_area, f"{config['titulo']}: {area}", url), encoding="utf-8")
