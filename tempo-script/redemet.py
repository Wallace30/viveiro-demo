"""REDEMET (DECEA): buscar o radar e o satélite e preparar as imagens, sem depender do Django.

Usado pelo sistema (radar.py e satelite.py, que põem a chave do .env e o cache por cima) e pela tarefa do GitHub
que atualiza a demo (demo-tempo/atualizar.py, com a chave guardada como segredo do repositório). Por isso só usa a
biblioteca padrão e o Pillow.
"""

import json
from datetime import datetime, timedelta
from datetime import timezone as tz
from io import BytesIO
from math import cos, radians
from urllib.request import Request, urlopen

from PIL import Image

API = "https://api-redemet.decea.mil.br/produtos"
RADARES = ("tm", "ga")    # Três Marias é o mais perto do viveiro; quando para, vale o de Gama (DF)
QUADROS = 6               # as últimas imagens, para animar
VELHA = timedelta(hours=1)
RECORTE = 6               # graus de latitude para cada lado do viveiro no recorte do satélite (~650 km)


def pedir(url, chave=None, agente="MapaViveiroTabuoes/1.0", timeout=20):
    """Bytes da resposta; a chave só vai para a API (as imagens são públicas)."""
    cab = {"User-Agent": agente}
    if chave:
        cab["X-Api-Key"] = chave
    with urlopen(Request(url, headers=cab), timeout=timeout) as resp:
        return resp.read()


def buscar_radar(area, chave, agente):
    return json.loads(pedir(f"{API}/radar/maxcappi?area={area}&anima={QUADROS}", chave, agente))


def buscar_satelite(chave, agente):
    return json.loads(pedir(f"{API}/satelite/realcada?anima={QUADROS}", chave, agente))


def _quando(texto):
    """A hora da REDEMET vem em UTC ("2026-11-03 00:27:13")."""
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz.utc)


def recente(quadros, agora):
    """Se a imagem mais nova tem menos de uma hora (senão o radar ou o satélite parou)."""
    return bool(quadros) and agora - datetime.fromisoformat(quadros[-1]["hora"]) <= VELHA


def quadros_radar(dados, agora):
    """{radar, limites, quadros} com as imagens do mais velho ao mais novo; None sem imagem recente."""
    quadros, info = [], None
    for quadro in dados.get("data", {}).get("radar") or []:
        for r in quadro:
            info = info or r
            if r.get("path") and r.get("data"):
                quadros.append({"imagem": r["path"], "hora": _quando(r["data"]).isoformat()})
    # a API repete o último quadro quando ainda não saiu um novo
    quadros = sorted({q["hora"]: q for q in quadros}.values(), key=lambda q: q["hora"])
    if not recente(quadros, agora):
        return None
    return {"radar": info["nome"].replace("Radar - ", ""),
            "limites": {c: float(info[c]) for c in ("lat_min", "lat_max", "lon_min", "lon_max")},
            "quadros": quadros}


def itens_satelite(dados):
    """(limites da imagem inteira, [(hora UTC, nome "202611030100", endereço da imagem)])."""
    d = dados.get("data") or {}
    ll = d.get("lat_lon") or {}
    limites = {c: float(ll[c]) for c in ("lat_min", "lat_max", "lon_min", "lon_max")}
    itens = {}
    for s in d.get("satelite") or []:
        if s.get("path") and s.get("data"):
            quando = _quando(s["data"])
            itens[quando] = (quando, quando.strftime("%Y%m%d%H%M"), s["path"])
    return limites, [itens[k] for k in sorted(itens)]


def recortar(conteudo, limites, lat, lon):
    """(PNG do recorte em volta de (lat, lon), limites do recorte em graus).

    A imagem do satélite cobre a América do Sul inteira em latitude/longitude simples (~10 km por ponto).
    """
    img = Image.open(BytesIO(conteudo))
    w, h = img.size
    graus_x = (limites["lon_max"] - limites["lon_min"]) / w
    graus_y = (limites["lat_max"] - limites["lat_min"]) / h
    meia_lon = RECORTE / cos(radians(lat))
    x0 = max(0, int((lon - meia_lon - limites["lon_min"]) / graus_x))
    x1 = min(w, int((lon + meia_lon - limites["lon_min"]) / graus_x) + 1)
    y0 = max(0, int((limites["lat_max"] - (lat + RECORTE)) / graus_y))
    y1 = min(h, int((limites["lat_max"] - (lat - RECORTE)) / graus_y) + 1)
    saida = BytesIO()
    img.crop((x0, y0, x1, y1)).save(saida, "PNG", optimize=True)
    # os limites saem dos pontos cortados, para a imagem cair no lugar exato do mapa
    return saida.getvalue(), {"lon_min": limites["lon_min"] + x0 * graus_x, "lon_max": limites["lon_min"] + x1 * graus_x,
                              "lat_max": limites["lat_max"] - y0 * graus_y, "lat_min": limites["lat_max"] - y1 * graus_y}
