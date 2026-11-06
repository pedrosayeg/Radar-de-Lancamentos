"""Montagem e envio do e-mail semanal.

Dois modos, escolhidos pelas variáveis de ambiente (segredos do GitHub):

1) Brevo (recomendado): BREVO_API_KEY, BREVO_LIST_ID, REMETENTE_EMAIL
   Os amigos se inscrevem pelo formulário do Brevo. O atributo de contato indicado em
   BREVO_ATRIBUTO_AREAS (padrão: AREAS) guarda as áreas escolhidas. Vazio = todas.

2) SMTP genérico: SMTP_HOST, SMTP_PORT, SMTP_USUARIO, SMTP_SENHA, REMETENTE_EMAIL e
   DESTINATARIOS no formato  email1|Direito,Filosofia;email2;email3|História
   (sem áreas = todas).

ADMIN_EMAIL (opcional) recebe os alertas de fontes quebradas.
"""
from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

BREVO = "https://api.brevo.com/v3"


def _env(nome: str) -> str:
    return os.environ.get(nome, "").strip()


def _areas_validas(bruto, todas: list[str]) -> list[str]:
    if not bruto:
        return []
    itens = bruto if isinstance(bruto, list) else str(bruto).replace(";", ",").split(",")
    norm = {a.lower(): a for a in todas}
    return [norm[i.strip().lower()] for i in itens if i and i.strip().lower() in norm]


# ---------------------------------------------------------------- destinatários
def destinatarios(config: dict) -> list[tuple[str, list[str]]]:
    todas = config["areas"]
    if _env("BREVO_API_KEY") and _env("BREVO_LIST_ID"):
        atributo = _env("BREVO_ATRIBUTO_AREAS") or "AREAS"
        saida, offset = [], 0
        while True:
            r = requests.get(f"{BREVO}/contacts/lists/{_env('BREVO_LIST_ID')}/contacts",
                             headers={"api-key": _env("BREVO_API_KEY"), "accept": "application/json"},
                             params={"limit": 100, "offset": offset}, timeout=60)
            r.raise_for_status()
            contatos = r.json().get("contacts", [])
            for c in contatos:
                if c.get("emailBlacklisted"):
                    continue
                attrs = c.get("attributes") or {}
                valor = attrs.get(atributo) or attrs.get(atributo.upper()) or attrs.get(atributo.lower())
                saida.append((c["email"], _areas_validas(valor, todas)))
            if len(contatos) < 100:
                return saida
            offset += 100
    bruto = _env("DESTINATARIOS")
    saida = []
    for parte in bruto.split(";"):
        if not parte.strip():
            continue
        email, _, areas = parte.partition("|")
        saida.append((email.strip(), _areas_validas(areas, todas)))
    return saida


# ---------------------------------------------------------------- envio
def _enviar(para: str, assunto: str, corpo_html: str, config: dict) -> None:
    remetente = _env("REMETENTE_EMAIL")
    nome = config["envio"].get("remetente_nome", "Radar de Lançamentos")
    if not remetente:
        raise RuntimeError("REMETENTE_EMAIL não configurado")
    if _env("BREVO_API_KEY"):
        r = requests.post(f"{BREVO}/smtp/email",
                          headers={"api-key": _env("BREVO_API_KEY"), "content-type": "application/json"},
                          json={"sender": {"name": nome, "email": remetente}, "to": [{"email": para}],
                                "subject": assunto, "htmlContent": corpo_html}, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"Brevo recusou o envio para {para}: {r.status_code} {r.text[:200]}")
        return
    if _env("SMTP_HOST"):
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = assunto, f"{nome} <{remetente}>", para
        msg.attach(MIMEText(corpo_html, "html", "utf-8"))
        porta = int(_env("SMTP_PORT") or 587)
        contexto = ssl.create_default_context()
        if porta == 465:
            with smtplib.SMTP_SSL(_env("SMTP_HOST"), porta, context=contexto, timeout=60) as s:
                s.login(_env("SMTP_USUARIO"), _env("SMTP_SENHA"))
                s.send_message(msg)
        else:
            with smtplib.SMTP(_env("SMTP_HOST"), porta, timeout=60) as s:
                s.starttls(context=contexto)
                s.login(_env("SMTP_USUARIO"), _env("SMTP_SENHA"))
                s.send_message(msg)
        return
    raise RuntimeError("nenhum serviço de e-mail configurado")


def configurado() -> bool:
    return bool(_env("REMETENTE_EMAIL") and (_env("BREVO_API_KEY") or _env("SMTP_HOST")))


# ---------------------------------------------------------------- conteúdo
def montar_html(livros: list[dict], config: dict, areas_escolhidas: list[str]) -> str:
    e = html.escape
    por_area: dict[str, list[dict]] = {}
    for l in livros:
        areas_livro = l.get("areas") or ["Outras humanidades"]
        # Agrupa pela primeira área do livro que o leitor escolheu
        principal = next((a for a in areas_livro if a in areas_escolhidas), areas_livro[0])
        por_area.setdefault(principal, []).append(l)
    ordem = [a for a in config["areas"] if a in por_area]
    partes = [
        '<div style="font-family:Georgia,serif;max-width:680px;margin:auto;color:#222">',
        f'<h1 style="font-size:22px;margin-bottom:4px">{e(config["titulo"])}</h1>',
        f'<p style="color:#666;margin-top:0">{len(livros)} novidade(s) desde o último envio'
        + (f' nas áreas: {e(", ".join(areas_escolhidas))}' if areas_escolhidas else "") + "</p>",
    ]
    for area in ordem:
        partes.append(f'<h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:28px">{e(area)}</h2>')
        for l in por_area[area]:
            data = ""
            if l.get("data_lancamento"):
                d = l["data_lancamento"]
                data = f" · lançamento {d[8:10]}/{d[5:7]}/{d[:4]}"
            autores = f'{e(l["autores"])} · ' if l.get("autores") else ""
            desc = e((l.get("descricao") or "")[:280])
            partes.append(
                '<div style="margin:14px 0">'
                f'<a href="{e(l["url"])}" style="font-size:16px;color:#1a4d8f;text-decoration:none"><b>{e(l["titulo"])}</b></a><br>'
                f'<span style="color:#555;font-size:13px">{autores}{e(l.get("editora") or "")}{data}</span>'
                + (f'<div style="font-size:14px;color:#333;margin-top:4px">{desc}</div>' if desc else "")
                + "</div>"
            )
    url_site = config.get("url_site", "")
    inscricao = config.get("url_inscricao", "")
    partes.append(
        '<hr style="margin-top:30px;border:none;border-top:1px solid #ddd">'
        '<p style="font-size:12px;color:#777">A lista é montada automaticamente a partir dos sites das editoras e '
        'a classificação por área pode conter erros. '
        + (f'Catálogo completo: <a href="{e(url_site)}">{e(url_site)}</a>. ' if url_site else "")
        + (f'Para mudar suas áreas, preencha de novo o <a href="{e(inscricao)}">formulário</a>. ' if inscricao else "")
        + "Para deixar de receber, responda este e-mail pedindo o descadastro.</p></div>"
    )
    return "".join(partes)


def enviar_resumo(pendentes: list[dict], config: dict, log=print) -> int | None:
    """Envia o resumo para cada destinatário. Devolve quantos e-mails saíram, ou None se nada foi feito."""
    if not configurado():
        log("E-mail não configurado (faltam segredos); pulando envio.")
        return None
    if not pendentes:
        log("Nenhuma novidade pendente; nada a enviar.")
        return 0
    lista = destinatarios(config)
    if not lista:
        log("Nenhum destinatário cadastrado; pulando envio.")
        return None
    enviados, falhas = 0, []
    for email, areas in lista:
        selecao = [l for l in pendentes if not areas or set(l.get("areas") or []) & set(areas)]
        if not selecao:
            continue
        try:
            _enviar(email, config["envio"]["assunto"], montar_html(selecao, config, areas), config)
            enviados += 1
        except Exception as ex:  # noqa: BLE001
            falhas.append(f"{email}: {ex}")
    log(f"E-mails enviados: {enviados}; falhas: {len(falhas)}")
    for f in falhas:
        log("   " + f)
    if falhas and not enviados:
        raise RuntimeError("todos os envios falharam")
    return enviados


def alertar_admin(quebradas: dict, config: dict, log=print) -> None:
    admin = _env("ADMIN_EMAIL")
    if not admin or not configurado():
        return
    itens = "".join(f"<li><b>{html.escape(n)}</b>: {html.escape(s.get('ultimo_erro', ''))}</li>"
                    for n, s in quebradas.items())
    _enviar(admin, "Radar de Lançamentos: fontes com problema",
            f"<p>Estas fontes falharam {config['envio'].get('alerta_falhas_seguidas', 3)} vezes seguidas ou mais. "
            f"Provavelmente o site mudou e o arquivo config/fontes.yaml precisa de ajuste.</p><ul>{itens}</ul>", config)
    log(f"Alerta enviado para o administrador ({len(quebradas)} fonte(s)).")
