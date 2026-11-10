"""Radar, satélite e aviso de chuva da demo: roda na tarefa do GitHub (tempo.yml), a cada ~15 min.

A demo é um site público sem servidor, então a chave da REDEMET não pode ir nela. Esta tarefa usa a chave guardada
como segredo do repositório (REDEMET_API_KEY), busca os dados e grava os arquivos que a demo lê em ./tempo/:
  radar.json      o mesmo formato de /api/radar/ do sistema (as imagens da chuva são endereços públicos da REDEMET)
  satelite.json   o mesmo formato de /api/satelite/, apontando para os recortes ao lado
  sat-<hora>.png  as nuvens recortadas em volta do viveiro
Usa os mesmos módulos do sistema (backend/viveiro/redemet.py e aviso_chuva.py, copiados pelo publicar-demo.sh).
Se a REDEMET não responder, o arquivo daquela parte não é gravado e a demo só não mostra o radar ou as nuvens.

Uso: REDEMET_API_KEY=... python atualizar.py <pasta de saída>
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import aviso_chuva
import redemet

# o viveiro (o mesmo PREVISAO_LAT/LON do sistema)
LOCAL, LAT, LON = "Coromandel (MG)", -18.719932, -46.916948
AGENTE = "MapaViveiroTabuoes/1.0 (demonstração do sistema interno do viveiro)"
FONTE = "REDEMET / DECEA"


def avisar(msg):
    """Problema na busca: na tarefa do GitHub vira um aviso (::warning::), que aparece no resumo da execução."""
    print(f"::warning::{msg}" if os.environ.get("GITHUB_ACTIONS") else msg)


def baixar(url):
    return redemet.pedir(url, agente=AGENTE)


def radar(chave, agora):
    for area in redemet.RADARES:
        try:
            resumo = redemet.quadros_radar(redemet.buscar_radar(area, chave, AGENTE), agora)
        except Exception as erro:
            avisar(f"radar {area} indisponível: {type(erro).__name__}: {erro}")
            continue
        if resumo:
            resumo.update(local={"nome": LOCAL, "lat": LAT, "lon": LON}, fonte=FONTE)
            try:
                resumo["aviso"] = aviso_chuva.do_radar(resumo["quadros"], resumo["limites"], LAT, LON, baixar, agora)
            except Exception as erro:
                avisar(f"aviso indisponível: {type(erro).__name__}: {erro}")
                resumo["aviso"] = None
            return resumo
        print(f"radar {area} sem imagem recente")
    avisar("nenhum radar com imagem recente")
    return None


def satelite(chave, agora, pasta):
    limites, itens = redemet.itens_satelite(redemet.buscar_satelite(chave, AGENTE))
    quadros, recorte = [], None
    for quando, nome, endereco in itens:
        png, recorte = redemet.recortar(baixar(endereco), limites, LAT, LON)
        (pasta / f"sat-{nome}.png").write_bytes(png)
        quadros.append({"hora": quando.isoformat(), "imagem": f"tempo/sat-{nome}.png"})
    if not redemet.recente(quadros, agora):
        return None
    return {"quadros": quadros, "limites": recorte, "fonte": FONTE}


def main(destino):
    chave = os.environ.get("REDEMET_API_KEY", "").strip()
    if not chave:
        avisar("sem REDEMET_API_KEY: a demo fica sem radar")
        return
    pasta = Path(destino)
    pasta.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc)
    dados = radar(chave, agora)
    if dados:
        (pasta / "radar.json").write_text(json.dumps(dados, ensure_ascii=False))
        print(f"radar {dados['radar']}, {dados['quadros'][-1]['hora']}: {dados['aviso'] and dados['aviso']['texto']}")
    try:
        nuvens = satelite(chave, agora, pasta)
    except Exception as erro:
        avisar(f"satélite indisponível: {type(erro).__name__}: {erro}")
        nuvens = None
    if nuvens:
        (pasta / "satelite.json").write_text(json.dumps(nuvens))
        print(f"satélite: {len(nuvens['quadros'])} imagens, a última de {nuvens['quadros'][-1]['hora']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tempo")
