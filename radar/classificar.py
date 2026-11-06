"""Classificação dos livros por área e filtro do que é (ou não) livro de teoria.

Com a variável ANTHROPIC_API_KEY, usa o Claude. Sem ela, usa palavras-chave.
A classificação automática pode errar. O campo `classificado_por` registra qual método foi usado.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

import requests


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# ---------------------------------------------------------------- heurística
PALAVRAS = {
    "Direito": ["direito", "juridic", "constitucion", "processo civil", "processo penal", "penal", "tributar",
                "stf", "jurisprud", "codigo civil", "licitac", "contrato", "advocacia", "magistratura",
                "criminolog", "law", "legal", "hermeneutica juridica", "lei ", "leis "],
    "Política": ["politic", "democracia", "estado", "marxis", "socialis", "comunis", "fascis", "liberalis",
                 "neoliberal", "capitalis", "revoluc", "poder", "imperialis", "eleic", "partido", "geopolit",
                 "colonial", "populis", "extrema direita", "bolsonar", "lula", "movimento social"],
    "Sociologia": ["sociolog", "sociedade", "social", "classe trabalhadora", "trabalho", "racismo", "raca",
                   "genero", "feminis", "desigualdade", "urban", "violencia", "juventude", "religiao"],
    "Filosofia": ["filosof", "etica", "metafisic", "fenomenolog", "hegel", "kant", "nietzsche", "heidegger",
                  "foucault", "adorno", "benjamin", "espinosa", "spinoza", "aristotel", "platao", "dialetica",
                  "ontolog", "teoria critica", "estetica", "philosoph"],
    "Psicanálise": ["psicanal", "freud", "lacan", "inconsciente", "winnicott", "klein", "clinica psicanal",
                    "psicanalit"],
    "História": ["historia", "historic", "histori", "ditadura", "escravid", "imperio", "seculo", "guerra",
                 "memoria", "biografia de", "brasil colonia", "republica"],
    "Economia": ["economi", "financ", "mercado", "inflac", "desenvolvimento economico", "renda", "fiscal"],
    "Antropologia": ["antropolog", "etnograf", "indigena", "povos originarios", "cosmolog", "xama"],
}

NAO_TEORIA = ["romance", "ficcao", "conto", "contos", "poesia", "poemas", "infantil", "infanto", "juvenil",
              "young adult", "hq", "quadrinho", "graphic novel", "manga", "culinaria", "receita", "autoajuda",
              "auto-ajuda", "desenvolvimento pessoal", "colorir", "livro-jogo", "agenda ", "calendario",
              "carreira e desenvolvimento", "espiritualidade", "dieta", "fantasia", "thriller", "suspense",
              "literatura brasileira", "literatura estrangeira", "box ", "kit ", "combo", "caneca", "ecobag",
              "camiseta", "vade mecum", "vendas", "marketing", "lideranca", "empreended",
              "gestao de pessoas", "produtividade", "financas pessoais", "investimentos", "questoes comentadas", "concurso", "oab 1a fase", "resumo para"]


# Indícios de ficção ou de livro infantil na sinopse
SINAIS_FICCAO = ["protagonista", "trama", "personagem", "saga", "thriller", "best-seller", "bestseller",
                 "romance ", "romances", "aventura", "misterio", "assassin", "detetive", "apaixon",
                 "criancas", "pequenos leitores", "ilustrac", "conto de fadas", "magia", "reino",
                 "volume da serie", "da serie", "trilogia", "leitores jovens", "jovem adulto", "fas de"]
NAO_LIVRO = ["estojo", "calice", "ciborio", "caneca", "ecobag", "camiseta", "marcador", "poster", "pôster",
             "vale-presente", "cartao presente", "assinatura do clube"]


def heuristica(livro: dict, fonte: dict, areas_validas: list[str]) -> dict:
    titulo = _norm(livro.get("titulo", ""))
    cabecalho = _norm(" ".join(livro.get("categorias") or []) + " " + livro.get("titulo", ""))
    descricao = _norm(livro.get("descricao", "")[:500])

    # "Não ficção" não pode disparar o filtro de "ficção"
    sem_nf = re.sub(r"nao[ -]ficcao", " ", cabecalho)
    nao = any(p in sem_nf for p in NAO_TEORIA) or any(p in sem_nf for p in NAO_LIVRO)
    if sum(descricao.count(s) for s in SINAIS_FICCAO) >= 2 or re.search(r"\(vol\. ?\d+", titulo):
        nao = True

    forte, pontos = {}, {}
    for area, palavras in PALAVRAS.items():
        n_cab = sum(cabecalho.count(p) for p in palavras)
        n_desc = sum(descricao.count(p) for p in palavras)
        if n_cab or n_desc:
            pontos[area] = 3 * n_cab + n_desc
            forte[area] = n_cab > 0 or n_desc >= 3
    areas = [a for a, _ in sorted(pontos.items(), key=lambda x: -x[1])[:2] if a in areas_validas]

    # Editoras generalistas (que publicam muita ficção) exigem indício forte de tema teórico
    if fonte.get("generalista") and not any(forte.get(a) for a in areas):
        nao = True
    if not areas:
        areas = list(fonte.get("areas_padrao") or ["Outras humanidades"])
    return {"areas": areas, "teoria": not nao, "classificado_por": "palavras-chave"}


# ---------------------------------------------------------------- IA (Claude)
PROMPT = """Você classifica lançamentos de editoras brasileiras para uma lista de leitores interessados em livros de teoria \
(não ficção acadêmica ou ensaística) nas áreas: {areas}.

Para cada livro abaixo, responda:
- "teoria": true se for livro de teoria, ensaio, pesquisa, obra acadêmica ou doutrina jurídica relevante; \
false se for ficção, poesia, infantil/juvenil, quadrinhos, autoajuda, culinária, espiritualidade, material de concurso, \
vade mecum, produto que não é livro, ou divulgação muito superficial.
- "areas": de 1 a 2 áreas da lista acima, exatamente como escritas, da mais para a menos relevante.

Responda SOMENTE com um array JSON, um objeto por livro, no formato [{{"i": 0, "teoria": true, "areas": ["Filosofia"]}}].

Livros:
{livros}"""


def _ia_lote(lote: list[tuple[int, dict]], areas: list[str], modelo: str, chave: str) -> dict[int, dict]:
    linhas = []
    for i, l in lote:
        linhas.append(json.dumps({
            "i": i, "titulo": l.get("titulo"), "autores": l.get("autores"), "editora": l.get("editora"),
            "categorias": (l.get("categorias") or [])[:8], "descricao": (l.get("descricao") or "")[:500],
        }, ensure_ascii=False))
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": chave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": modelo, "max_tokens": 4000,
              "messages": [{"role": "user", "content": PROMPT.format(areas=", ".join(areas), livros="\n".join(linhas))}]},
        timeout=120,
    )
    r.raise_for_status()
    texto = "".join(b.get("text", "") for b in r.json().get("content", []))
    m = re.search(r"\[.*\]", texto, flags=re.S)
    if not m:
        raise ValueError("resposta da IA sem JSON")
    saida = {}
    for item in json.loads(m.group(0)):
        validas = [a for a in item.get("areas") or [] if a in areas][:2]
        saida[int(item["i"])] = {"teoria": bool(item.get("teoria")), "areas": validas or ["Outras humanidades"],
                                 "classificado_por": "ia"}
    return saida


def classificar(livros: list[dict], fontes_por_nome: dict, config: dict, log=print) -> None:
    """Preenche `areas`, `teoria` e `classificado_por` em cada livro (altera a lista no lugar)."""
    areas = config["areas"]
    chave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    modelo = config.get("classificacao", {}).get("modelo", "claude-haiku-5-5")
    resultados: dict[int, dict] = {}
    if chave and livros:
        indexados = list(enumerate(livros))
        for k in range(0, len(indexados), 25):
            lote = indexados[k:k + 25]
            try:
                resultados.update(_ia_lote(lote, areas, modelo, chave))
            except Exception as e:  # noqa: BLE001
                log(f"  aviso: classificação por IA falhou neste lote ({e}); usando palavras-chave")
    for i, livro in enumerate(livros):
        fonte = fontes_por_nome.get(livro.get("fonte"), {})
        r = resultados.get(i) or heuristica(livro, fonte, areas)
        if r["areas"] == ["Outras humanidades"] and fonte.get("areas_padrao"):
            r["areas"] = list(fonte["areas_padrao"])
        livro.update(r)
