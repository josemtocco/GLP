#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de lista M3U (SS IPTV) a partir do Globoplay - TV Globo ao vivo.

Fonte-semente: https://globoplay.globo.com/tv-globo/ao-vivo/6120663/

Caracteristicas:
- Somente biblioteca padrao do Python (sem pip).
- Descobre os canais ao vivo do Globoplay, resolve o HLS de cada um,
  valida se esta no ar e gera 'playlist.m3u' otimizada para SS IPTV.
- Reconciliacao com estado persistido em 'estado_canais.json':
    * mantem os canais que estao ativos (zera o contador de falhas);
    * remove os inativos apenas apos 6 atualizacoes seguidas falhando;
    * acrescenta automaticamente os canais novos encontrados.
- Agrupa por categoria (group-title) conforme o site.
- Protecao anti-bloqueio: se a origem inteira estiver inacessivel
  (geo-bloqueio / 403 / sem login), NAO penaliza canal nenhum e
  preserva a lista/estado anteriores (evita que runs dos EUA apaguem
  a lista pela regra das 6 falhas).

Uso:
    python gerar_globoplay.py
    python gerar_globoplay.py --no-drm     # ignora canais com Widevine DRM
    python gerar_globoplay.py --debug      # log detalhado

Credenciais (via variaveis de ambiente / GitHub Secrets):
    GLOBO_EMAIL, GLOBO_PASSWORD   -> login automatico
    GLBID                         -> cookie de sessao ja autenticado

Variaveis opcionais:
    GLOBO_DEBUG=1                 -> equivale a --debug
    INCLUDE_DRM=0                 -> equivale a --no-drm
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import http.cookiejar

# --------------------------------------------------------------------------
# Configuracao
# --------------------------------------------------------------------------
DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(DIR, "config.json")
ESTADO_PATH = os.path.join(DIR, "estado_canais.json")
PLAYLIST_PATH = os.path.join(DIR, "playlist.m3u")

# Numero de atualizacoes seguidas falhando antes de remover o canal.
MAX_FALHAS = 6

# Canal-semente informado pelo usuario.
SEED_MEDIA_ID = "6120663"
SEED_URL = "https://globoplay.globo.com/tv-globo/ao-vivo/6120663/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEBUG = False


def log(msg):
    print(msg, flush=True)


def dbg(msg):
    if DEBUG:
        print("[debug] " + msg, flush=True)


# --------------------------------------------------------------------------
# HTTP helpers (stdlib)
# --------------------------------------------------------------------------
COOKIES = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(COOKIES)
)


def _headers(extra=None):
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    if extra:
        h.update(extra)
    return h


def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=_headers(headers), method="GET")
    with OPENER.open(req, timeout=timeout) as resp:
        raw = resp.read()
        enc = resp.headers.get_content_charset() or "utf-8"
        return resp.status, raw.decode(enc, "replace")


def http_post_json(url, payload, headers=None, timeout=25):
    data = json.dumps(payload).encode("utf-8")
    h = _headers(headers)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with OPENER.open(req, timeout=timeout) as resp:
        raw = resp.read()
        enc = resp.headers.get_content_charset() or "utf-8"
        return resp.status, raw.decode(enc, "replace")


def stream_online(url, timeout=15):
    """Verifica se o HLS responde (manifesto .m3u8 acessivel)."""
    try:
        req = urllib.request.Request(url, headers=_headers(), method="GET")
        with OPENER.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            head = resp.read(4096).decode("utf-8", "replace")
            return "#EXTM3U" in head or ".ts" in head or ".m3u8" in head
    except Exception as e:
        dbg("stream offline %s (%s)" % (url, e))
        return False


# --------------------------------------------------------------------------
# Config / estado
# --------------------------------------------------------------------------
def carregar_config():
    cfg = {
        "seed_media_id": SEED_MEDIA_ID,
        "seed_url": SEED_URL,
        # Lista de canais ao vivo do Globoplay (media_id + categoria do site).
        # Pode ser editada manualmente para forcar inclusao/ordem.
        "canais_fixos": [],
        # Endpoints da Globo (podem ser ajustados sem mexer no codigo).
        "api_affiliates": "https://api.affiliates.globo.com/v1/affiliates/info",
        "api_playback": "https://playback.video.globo.com/v4/video-session",
        "api_graphql": "https://jarvis.globo.com/graphql",
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg or {})
            dbg("config.json carregado")
        except Exception as e:
            log("Aviso: nao foi possivel ler config.json (%s). Usando padrao." % e)
    return cfg


def carregar_estado():
    if os.path.exists(ESTADO_PATH):
        try:
            with open(ESTADO_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log("Aviso: estado_canais.json invalido (%s). Recriando." % e)
    return {"canais": {}, "ultima_atualizacao": None}


def salvar_estado(estado):
    estado["ultima_atualizacao"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Regiao
# --------------------------------------------------------------------------
def regiao_do_ip():
    try:
        _, body = http_get("https://ipinfo.io/country", timeout=10)
        return body.strip().upper()
    except Exception as e:
        dbg("falha ao detectar regiao: %s" % e)
        return "?"


# --------------------------------------------------------------------------
# Autenticacao Globo
# --------------------------------------------------------------------------
def autenticar():
    """Obtem uma sessao autenticada na Globo.

    Preferencia:
      1) cookie GLBID direto (ja autenticado);
      2) GLOBO_EMAIL + GLOBO_PASSWORD (login automatico).
    Retorna o GLBID (string) ou None.
    """
    glbid = os.environ.get("GLBID", "").strip()
    if glbid:
        log("Usando cookie GLBID fornecido via ambiente.")
        return glbid

    email = os.environ.get("GLOBO_EMAIL", "").strip()
    senha = os.environ.get("GLOBO_PASSWORD", "").strip()
    if not (email and senha):
        log("Sem credenciais (GLBID ou GLOBO_EMAIL/GLOBO_PASSWORD). "
            "Prosseguindo sem login (sera possivel apenas para canais abertos).")
        return None

    log("Efetuando login em login.globo.com ...")
    try:
        payload = {
            "payload": {
                "email": email,
                "password": senha,
                "serviceId": 4654,  # servico padrao do Globoplay
            },
            "captcha": "",
        }
        status, body = http_post_json(
            "https://login.globo.com/api/authentication",
            payload,
            headers={"Origin": "https://login.globo.com"},
        )
        dbg("login status=%s" % status)
        data = json.loads(body)
        glbid = data.get("glbId") or data.get("glbid")
        if glbid:
            log("Login OK (GLBID obtido).")
            return glbid
        log("Login respondeu sem GLBID: %s" % body[:200])
    except urllib.error.HTTPError as e:
        log("Falha no login (HTTP %s). Verifique email/senha." % e.code)
    except Exception as e:
        log("Falha no login: %s" % e)
    return None


def auth_headers(glbid):
    h = {"Origin": "https://globoplay.globo.com",
         "Referer": "https://globoplay.globo.com/"}
    if glbid:
        h["Cookie"] = "GLBID=%s" % glbid
        h["Authorization"] = "Bearer %s" % glbid
    return h


# --------------------------------------------------------------------------
# Descoberta dos canais ao vivo
# --------------------------------------------------------------------------
def descobrir_canais(cfg, glbid):
    """Descobre os canais ao vivo do Globoplay.

    Estrategia:
      1) canais_fixos do config.json (se houver) tem prioridade;
      2) raspa a pagina de canais ao vivo procurando media_ids e titulos;
      3) complementa com o canal-semente (6120663 = TV Globo).

    Retorna lista de dicts: {media_id, nome, categoria, logo}
    """
    canais = []
    vistos = set()

    def add(media_id, nome, categoria, logo=""):
        media_id = str(media_id).strip()
        if not media_id or media_id in vistos:
            return
        vistos.add(media_id)
        canais.append({
            "media_id": media_id,
            "nome": (nome or "").strip() or ("Canal %s" % media_id),
            "categoria": (categoria or "TV Globo").strip(),
            "logo": logo or "",
        })

    # 1) Canais fixos definidos manualmente
    for c in cfg.get("canais_fixos", []) or []:
        add(c.get("media_id"), c.get("nome"), c.get("categoria", "TV Globo"),
            c.get("logo", ""))

    # 2) Raspagem da pagina de canais ao vivo
    paginas = [
        cfg.get("seed_url", SEED_URL),
        "https://globoplay.globo.com/canais/",
        "https://globoplay.globo.com/agora/",
    ]
    for url in paginas:
        try:
            status, html = http_get(url, headers=auth_headers(glbid))
            dbg("GET %s -> %s (%d bytes)" % (url, status, len(html)))
            _extrair_canais_do_html(html, add)
        except urllib.error.HTTPError as e:
            log("Pagina %s retornou HTTP %s" % (url, e.code))
            if e.code in (403, 451):
                # geo-bloqueio / sem permissao -> sinaliza outage
                raise OrigemBloqueada("HTTP %s em %s" % (e.code, url))
        except OrigemBloqueada:
            raise
        except Exception as e:
            dbg("falha ao ler %s: %s" % (url, e))

    # 3) Garante o canal-semente
    add(cfg.get("seed_media_id", SEED_MEDIA_ID), "TV Globo", "TV Globo")

    return canais


class OrigemBloqueada(Exception):
    """Levantada quando a origem inteira esta inacessivel (geo-bloqueio)."""
    pass


_RE_MEDIA = re.compile(r'/ao-vivo/(\d+)')
_RE_JSON_MEDIA = re.compile(r'"mediaId"\s*:\s*"?(\d+)"?')


def _extrair_canais_do_html(html, add):
    # media ids em links /ao-vivo/<id>/ e em JSON embutido
    ids = set(_RE_MEDIA.findall(html)) | set(_RE_JSON_MEDIA.findall(html))
    for mid in ids:
        nome = _nome_proximo(html, mid)
        add(mid, nome, "TV Globo")
    # tenta JSON __NEXT_DATA__ ou "channels":[...]
    for m in re.finditer(
        r'"title"\s*:\s*"([^"]{2,80})"[^{}]{0,400}?"mediaId"\s*:\s*"?(\d+)"?',
        html,
    ):
        add(m.group(2), m.group(1), "TV Globo")


def _nome_proximo(html, mid):
    idx = html.find("/ao-vivo/%s" % mid)
    if idx == -1:
        return ""
    janela = html[max(0, idx - 300):idx + 300]
    m = re.search(r'(?:title|aria-label|alt)="([^"]{2,80})"', janela)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------
# Resolucao do HLS (playback API)
# --------------------------------------------------------------------------
def resolver_stream(cfg, media_id, glbid):
    """Resolve o media_id para um stream HLS.

    Retorna dict: {url, drm (bool)} ou None.
    A API de playback da Globo resolve o HLS dinamicamente e sinaliza
    protecao Widevine quando o canal usa DRM.
    """
    url = cfg.get("api_playback", "https://playback.video.globo.com/v4/video-session")
    payload = {
        "player_type": "desktop",
        "video_id": str(media_id),
        "quality": "max",
        "content_protection": "widevine",
        "tz": "America/Sao_Paulo",
        "capabilities": {"low_latency": True},
        "consumption": "streaming",
        "metadata": {"name": "web", "device": {"type": "desktop"}},
        "version": 2,
    }
    try:
        status, body = http_post_json(url, payload, headers=auth_headers(glbid))
        dbg("playback %s -> %s" % (media_id, status))
        data = json.loads(body)
    except urllib.error.HTTPError as e:
        code = e.code
        if code in (401, 403):
            dbg("playback %s negado (HTTP %s) - precisa login/regiao BR" % (media_id, code))
        else:
            dbg("playback %s HTTP %s" % (media_id, code))
        return None
    except Exception as e:
        dbg("playback %s falhou: %s" % (media_id, e))
        return None

    sources = data.get("sources") or []
    hls_url = ""
    drm = False
    for s in sources:
        u = s.get("url") or ""
        if ".m3u8" in u or "hls" in (s.get("protocol") or "").lower():
            hls_url = u
            if s.get("protection") or s.get("protectionData") or s.get("drm"):
                drm = True
            break
    if not hls_url:
        # fallback: campos planos
        hls_url = data.get("url") or data.get("playback", {}).get("url", "")
        if data.get("protection") or data.get("drm"):
            drm = True
    if not hls_url:
        dbg("sem HLS para %s" % media_id)
        return None
    return {"url": hls_url, "drm": bool(drm)}


# --------------------------------------------------------------------------
# Reconciliacao
# --------------------------------------------------------------------------
def reconciliar(estado, resultados):
    """Aplica a regra de reconciliacao.

    resultados: dict media_id -> {nome, categoria, logo, url, drm, online}
    estado['canais']: media_id -> {nome, categoria, logo, url, drm,
                                     falhas, ativo, visto_em}

    Regras:
      - canal ONLINE agora        -> falhas = 0, ativo = True (mantem/atualiza).
      - canal OFFLINE agora       -> falhas += 1; so remove se falhas >= MAX_FALHAS.
      - canal NOVO (nao estava)    -> adicionado se online.
    """
    canais = estado.setdefault("canais", {})
    agora = time.strftime("%Y-%m-%d %H:%M:%S")

    # 1) Atualiza / incrementa falhas para quem ja existia
    for mid, info in list(canais.items()):
        # Canais adicionados manualmente (preservar) nao entram na regra
        # de remocao por falhas - sao gerenciados pelo usuario.
        if info.get("preservar"):
            continue
        novo = resultados.get(mid)
        if novo and novo.get("online"):
            info.update({
                "media_id": mid,
                "nome": novo["nome"],
                "categoria": novo["categoria"],
                "logo": novo.get("logo", info.get("logo", "")),
                "url": novo["url"],
                "drm": novo.get("drm", False),
                "falhas": 0,
                "ativo": True,
                "visto_em": agora,
            })
        else:
            info["falhas"] = int(info.get("falhas", 0)) + 1
            info["ativo"] = False
            if info["falhas"] >= MAX_FALHAS:
                log("  - REMOVIDO (%d falhas seguidas): %s"
                    % (info["falhas"], info.get("nome", mid)))
                del canais[mid]
            else:
                log("  - inativo (%d/%d falhas, mantido): %s"
                    % (info["falhas"], MAX_FALHAS, info.get("nome", mid)))

    # 2) Acrescenta canais novos que estao online
    for mid, novo in resultados.items():
        if mid in canais:
            continue
        if novo.get("online"):
            log("  + NOVO canal: %s" % novo["nome"])
            canais[mid] = {
                "media_id": mid,
                "nome": novo["nome"],
                "categoria": novo["categoria"],
                "logo": novo.get("logo", ""),
                "url": novo["url"],
                "drm": novo.get("drm", False),
                "falhas": 0,
                "ativo": True,
                "visto_em": agora,
            }
    return estado


# --------------------------------------------------------------------------
# Geracao do M3U (otimizado para SS IPTV)
# --------------------------------------------------------------------------
def gerar_m3u(estado, incluir_drm=True):
    canais = estado.get("canais", {})
    # Apenas canais atualmente ativos (com stream valido) entram no M3U.
    ativos = [c for c in canais.values() if c.get("ativo") and c.get("url")]
    if not incluir_drm:
        ativos = [c for c in ativos if not c.get("drm")]

    # Ordena por categoria e depois por nome -> agrupa por categoria no SS IPTV.
    def chave(c):
        return (c.get("categoria", "TV Globo").lower(), c.get("nome", "").lower())
    ativos.sort(key=chave)

    linhas = ['#EXTM3U url-tvg="" x-tvg-url=""']
    for c in ativos:
        nome = c["nome"]
        if c.get("drm"):
            nome = nome + " (DRM)"
        categoria = c.get("categoria", "TV Globo")
        logo = c.get("logo", "")
        tvg_id = "globo.%s" % c.get("media_id", "") if c.get("media_id") else ""
        attrs = [
            'tvg-id="%s"' % tvg_id,
            'tvg-name="%s"' % c["nome"],
            'tvg-logo="%s"' % logo,
            'group-title="%s"' % categoria,
        ]
        linhas.append('#EXTINF:-1 %s,%s' % (" ".join(attrs), nome))
        linhas.append(c["url"])

    conteudo = "\n".join(linhas) + "\n"
    with open(PLAYLIST_PATH, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return len(ativos)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    global DEBUG
    parser = argparse.ArgumentParser(
        description="Gera playlist.m3u (SS IPTV) do Globoplay TV Globo ao vivo.")
    parser.add_argument("--no-drm", action="store_true",
                        help="Ignora canais que usam Widevine DRM.")
    parser.add_argument("--debug", action="store_true",
                        help="Log detalhado.")
    args = parser.parse_args()

    DEBUG = args.debug or os.environ.get("GLOBO_DEBUG", "") in ("1", "true", "True")
    incluir_drm = not (args.no_drm or os.environ.get("INCLUDE_DRM", "") in ("0", "false", "False"))

    log("=" * 64)
    log(" Gerador M3U Globoplay (TV Globo ao vivo) -> SS IPTV")
    log("=" * 64)

    cfg = carregar_config()
    estado = carregar_estado()

    regiao = regiao_do_ip()
    log("Regiao detectada pelo IP: %s" % regiao)
    if regiao not in ("BR", "?"):
        log("AVISO: IP fora do Brasil (%s). O Globoplay bloqueia por regiao;" % regiao)
        log("       runs dos EUA costumam falhar com HTTP 403.")

    glbid = autenticar()

    # 0) Canais adicionados manualmente por link (sempre incluidos)
    processar_canais_adicionais(cfg, estado, glbid)

    # 1) Descoberta
    try:
        log("Descobrindo canais ao vivo...")
        canais = descobrir_canais(cfg, glbid)
        log("Canais descobertos: %d" % len(canais))
    except OrigemBloqueada as e:
        log("!! ORIGEM BLOQUEADA: %s" % e)
        log("   Preservando a lista e o estado anteriores (sem penalizar canais).")
        salvar_estado(estado)  # mantem contadores inalterados
        total = gerar_m3u(estado, incluir_drm=incluir_drm)
        log("playlist.m3u preservada com %d canais." % total)
        log("Gere a partir de um IP do Brasil para atualizar a lista.")
        return 0

    # 2) Resolve HLS + health-check
    resultados = {}
    for c in canais:
        mid = c["media_id"]
        info = resolver_stream(cfg, mid, glbid)
        online = False
        url = ""
        drm = False
        if info:
            url = info["url"]
            drm = info["drm"]
            online = stream_online(url)
        dbg("%s | %s | online=%s drm=%s" % (mid, c["nome"], online, drm))
        resultados[mid] = {
            "media_id": mid,
            "nome": c["nome"],
            "categoria": c["categoria"],
            "logo": c.get("logo", ""),
            "url": url,
            "drm": drm,
            "online": online,
        }

    online_count = sum(1 for r in resultados.values() if r["online"])
    log("Canais online agora: %d de %d" % (online_count, len(resultados)))

    # Protecao: se NENHUM canal respondeu, provavelmente e outage/geo-bloqueio.
    # Nao penaliza ninguem e preserva a lista anterior.
    if resultados and online_count == 0 and estado.get("canais"):
        log("!! Nenhum canal online - tratado como outage da origem.")
        log("   Preservando lista/estado (sem contar falhas).")
        salvar_estado(estado)
        total = gerar_m3u(estado, incluir_drm=incluir_drm)
        log("playlist.m3u preservada com %d canais." % total)
        return 0

    # 3) Reconciliacao
    log("Reconciliando (manter ativos / remover apos %d falhas / add novos)..." % MAX_FALHAS)
    estado = reconciliar(estado, resultados)
    salvar_estado(estado)

    # 4) Geracao do M3U
    total = gerar_m3u(estado, incluir_drm=incluir_drm)
    log("-" * 64)
    log("playlist.m3u gerada com %d canais ativos%s."
        % (total, "" if incluir_drm else " (sem DRM)"))
    log("Estado salvo em estado_canais.json")
    log("=" * 64)
    return 0


# --------------------------------------------------------------------------
# Canais adicionais (links diretos tipo FAST da Globo)
# --------------------------------------------------------------------------
def _jwt_exp(url):
    """Le o 'exp' (expiracao) do token de um link /j/<JWT>/... da Globo.

    Retorna epoch (int) ou None se nao houver token decodificavel.
    """
    try:
        if "/j/" not in url:
            return None
        jwt = url.split("/j/", 1)[1].split("/live/", 1)[0]
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return int(data.get("exp"))
    except Exception as e:
        dbg("falha ao ler exp do token: %s" % e)
        return None


def processar_canais_adicionais(cfg, estado, glbid):
    """Inclui/atualiza os canais adicionados manualmente por link.

    Regra por canal:
      - Se 'media_id' estiver preenchido -> re-resolve um link NOVO a cada
        execucao pela API de playback (renovacao automatica pelo GitHub).
      - Senao -> usa 'url_atual'; avisa se o token ja expirou. Esses canais
        tem 'preservar=true' e NAO sao removidos pela regra das %d falhas
        (voce os gerencia manualmente, colando um link novo quando expirar).
    """ % MAX_FALHAS
    adicionais = cfg.get("canais_adicionais", []) or []
    if not adicionais:
        return
    canais = estado.setdefault("canais", {})
    agora = time.strftime("%Y-%m-%d %H:%M:%S")
    agora_epoch = int(time.time())

    log("Processando %d canal(is) adicional(is)..." % len(adicionais))
    for c in adicionais:
        slug = (c.get("slug") or c.get("nome") or "").strip()
        key = "add:%s" % slug
        nome = (c.get("nome") or slug).strip()
        categoria = (c.get("categoria") or "Globo").strip()
        logo = c.get("logo", "")
        media_id = str(c.get("media_id") or "").strip()
        preservar = bool(c.get("preservar", True))
        url = (c.get("url_atual") or "").strip()
        drm = False
        online = None

        if media_id:
            # Renovacao automatica: pede um link novo a cada execucao.
            info = resolver_stream(cfg, media_id, glbid)
            if info and info.get("url"):
                url = info["url"]
                drm = info.get("drm", False)
                online = stream_online(url)
                log("  * %s: link renovado via API (online=%s)" % (nome, online))
            else:
                log("  * %s: nao consegui renovar via API (uso o ultimo link)."
                    % nome)
                antigo = canais.get(key, {})
                if antigo.get("url"):
                    url = antigo["url"]
        else:
            # Link manual: checa validade do token.
            exp = _jwt_exp(url)
            if exp is not None:
                if exp <= agora_epoch:
                    log("  * %s: ATENCAO - token EXPIRADO em %s. Cole um link "
                        "novo em config.json (ou preencha 'media_id' para "
                        "renovar automatico)."
                        % (nome, time.strftime("%Y-%m-%d %H:%M UTC",
                                               time.gmtime(exp))))
                else:
                    restam = (exp - agora_epoch) // 60
                    log("  * %s: token valido por mais ~%d min." % (nome, restam))

        canais[key] = {
            "media_id": media_id,
            "nome": nome,
            "categoria": categoria,
            "logo": logo,
            "url": url,
            "drm": drm,
            "falhas": 0,
            # Se tem media_id e resolveu online=False, ainda mantemos (preservar).
            "ativo": bool(url),
            "preservar": preservar,
            "manual": not bool(media_id),
            "visto_em": agora,
        }


if __name__ == "__main__":
    sys.exit(main())
