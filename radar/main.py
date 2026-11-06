"""Execução principal: coleta, classifica, atualiza o catálogo, gera o site e envia o e-mail.

Uso:
    python -m radar.main                  coleta e gera o site; envia e-mail só no dia configurado
    python -m radar.main --enviar         força o envio do e-mail com as novidades pendentes
    python -m radar.main --sem-envio      nunca envia e-mail (útil para testes)
    python -m radar.main --fonte Boitempo  roda só uma fonte (teste)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import yaml

from . import classificar, detalhes, email_envio, site
from .coletores import COLETORES

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
FUSO = dt.timezone(dt.timedelta(hours=-3))  # horário de Brasília


def hoje() -> dt.date:
    return dt.datetime.now(FUSO).date()


def ler_json(caminho: Path, padrao):
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return padrao


def gravar_json(caminho: Path, dado) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dado, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def carregar_config() -> tuple[dict, list[dict]]:
    geral = yaml.safe_load((RAIZ / "config" / "geral.yaml").read_text(encoding="utf-8"))
    fontes = yaml.safe_load((RAIZ / "config" / "fontes.yaml").read_text(encoding="utf-8"))["fontes"]
    return geral, [f for f in fontes if f.get("ativo", True)]


def dentro_da_janela(data_iso: str | None, dia: dt.date, passado: int, futuro: int) -> bool:
    if not data_iso:
        return False
    try:
        d = dt.date.fromisoformat(data_iso)
    except ValueError:
        return False
    return dia - dt.timedelta(days=passado) <= d <= dia + dt.timedelta(days=futuro)


def limpar_descricoes(livros: list[dict]) -> None:
    """Apaga descrições que não descrevem o livro: texto genérico do site repetido em vários
    produtos, ou sumários copiados da ficha."""
    from collections import Counter
    repetidas = Counter(l.get("descricao") for l in livros if l.get("descricao"))
    for l in livros:
        d = l.get("descricao") or ""
        if d and (repetidas[d] > 1 or re.match(r"^\s*(sum[aá]rio|[ií]ndice|pref[aá]cio)\b", d, flags=re.I)):
            l["descricao"] = ""


def coletar_fonte(fonte, vistos_fonte: set, primeira: bool, config: dict, dia: dt.date, log) -> list[dict]:
    """Devolve os livros novos da fonte e atualiza `vistos_fonte`."""
    candidatos = COLETORES[fonte["tipo"]](fonte)
    if not candidatos:
        raise RuntimeError("nenhum produto encontrado (o site pode ter mudado)")
    passado, futuro = config.get("janela_inicial_dias", 30), config.get("janela_futuro_dias", 180)
    novos, abertas = [], 0
    for c in candidatos:
        url = c.get("url")
        if not url or url in vistos_fonte:
            continue
        data = c.get("data_lancamento")
        # Pré-venda muito distante: não marca como visto, para reavaliar quando estiver mais perto
        if data and data > (dia + dt.timedelta(days=futuro)).isoformat():
            continue
        if primeira:
            # Na primeira leitura, só entram livros com data recente (ou pré-venda); o resto vira base.
            vistos_fonte.add(url)
            if dentro_da_janela(data, dia, passado, futuro):
                novos.append(c)
            continue
        if c.get("precisa_detalhe"):
            if abertas >= config.get("max_paginas_por_fonte", 40):
                continue  # fica para a próxima execução
            abertas += 1
            try:
                detalhe = detalhes.ler(url, fonte)
            except Exception as e:  # noqa: BLE001
                log(f"    não consegui ler {url}: {e}")
                detalhe = None
            vistos_fonte.add(url)
            if detalhe:
                novos.append(detalhe)
            continue
        vistos_fonte.add(url)
        novos.append(c)
    return novos


def executar(args) -> int:
    config, fontes = carregar_config()
    if args.fonte:
        fontes = [f for f in fontes if args.fonte.lower() in f["nome"].lower()]
        if not fontes:
            print("Nenhuma fonte com esse nome.")
            return 1
    dia = hoje()
    log = print

    catalogo: list[dict] = ler_json(DADOS / "livros.json", [])
    vistos: dict[str, list[str]] = ler_json(DADOS / "vistos.json", {})
    estado: dict = ler_json(DADOS / "estado.json", {"fontes": {}})
    ids_catalogo = {l["url"] for l in catalogo}

    novos_total: list[dict] = []
    for fonte in fontes:
        nome = fonte["nome"]
        st = estado["fontes"].setdefault(nome, {"falhas_seguidas": 0})
        primeira = nome not in vistos
        conjunto = set(vistos.get(nome, []))
        log(f"- {nome} ({fonte['tipo']}){' [primeira leitura]' if primeira else ''}")
        try:
            novos = coletar_fonte(fonte, conjunto, primeira, config, dia, log)
            st.update({"ultima_ok": dia.isoformat(), "falhas_seguidas": 0, "ultimo_erro": "",
                       "conhecidos": len(conjunto)})
            vistos[nome] = sorted(conjunto)
            for n in novos:
                n["fonte"] = nome
                if not n.get("editora"):
                    n["editora"] = nome
            novos = [n for n in novos if n["url"] not in ids_catalogo]
            limpar_descricoes(novos)
            log(f"    {len(novos)} novo(s); {len(conjunto)} produtos conhecidos")
            novos_total += novos
        except Exception as e:  # noqa: BLE001
            st["falhas_seguidas"] = st.get("falhas_seguidas", 0) + 1
            st["ultimo_erro"] = f"{dia.isoformat()}: {str(e)[:300]}"
            log(f"    ERRO: {e}")

    if novos_total:
        log(f"Classificando {len(novos_total)} livro(s)...")
        classificar.classificar(novos_total, {f["nome"]: f for f in fontes}, config, log)
    descartar = config.get("classificacao", {}).get("descartar_nao_teoria", True)
    entram = [n for n in novos_total if n.get("teoria") or not descartar]
    for n in entram:
        n.pop("precisa_detalhe", None)
        n["visto_em"] = dia.isoformat()
        n["enviado_em"] = None
    catalogo = entram + catalogo
    log(f"{len(entram)} entraram no catálogo; {len(novos_total) - len(entram)} descartados como não teoria.")

    estado["ultima_execucao"] = dt.datetime.now(FUSO).isoformat(timespec="minutes")
    gravar_json(DADOS / "livros.json", catalogo)
    gravar_json(DADOS / "vistos.json", vistos)

    site.gerar(catalogo, estado, config, RAIZ / "docs")

    deve_enviar = args.enviar or (not args.sem_envio and dia.weekday() == config["envio"].get("dia_semana", 0)
                                  and estado.get("ultimo_envio") != dia.isoformat())
    if deve_enviar and not args.sem_envio:
        pendentes = [l for l in catalogo if not l.get("enviado_em")]
        try:
            enviados = email_envio.enviar_resumo(pendentes, config, log)
            if enviados is not None:
                for l in pendentes:
                    l["enviado_em"] = dia.isoformat()
                estado["ultimo_envio"] = dia.isoformat()
                gravar_json(DADOS / "livros.json", catalogo)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO no envio de e-mail: {e}")
            estado["ultimo_erro_envio"] = f"{dia.isoformat()}: {str(e)[:300]}"

    limite = config["envio"].get("alerta_falhas_seguidas", 3)
    quebradas = {n: s for n, s in estado["fontes"].items() if s.get("falhas_seguidas", 0) >= limite}
    if quebradas and estado.get("ultimo_alerta") != dia.isoformat() and not args.sem_envio:
        try:
            email_envio.alertar_admin(quebradas, config, log)
            estado["ultimo_alerta"] = dia.isoformat()
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao enviar alerta: {e}")

    gravar_json(DADOS / "estado.json", estado)
    # Volta a gerar o site para refletir o estado final
    site.gerar(catalogo, estado, config, RAIZ / "docs")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Radar de Lançamentos")
    p.add_argument("--enviar", action="store_true", help="força o envio do e-mail")
    p.add_argument("--sem-envio", action="store_true", help="não envia e-mail")
    p.add_argument("--fonte", help="roda só as fontes cujo nome contenha este texto")
    args = p.parse_args()
    if os.environ.get("RADAR_SEM_ENVIO") == "1":
        args.sem_envio = True
    sys.exit(executar(args))


if __name__ == "__main__":
    main()
