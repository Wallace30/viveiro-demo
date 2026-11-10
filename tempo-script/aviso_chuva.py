"""Aviso de chuva a partir das imagens do radar: onde está a chuva mais perto do viveiro, para onde ela anda e se
deve passar por ele nas próximas horas.

A imagem maxcappi da REDEMET só tem a chuva (o resto é transparente) e cobre um quadrado em latitude/longitude.
O movimento vem de comparar a imagem de agora com uma de ~40 min antes: o deslocamento que mais sobrepõe a chuva
de uma na outra é o vento que a leva. É uma extrapolação simples, como a dos aplicativos de "chuva nas próximas horas":
vale para a próxima hora ou duas, e a chuva pode crescer, sumir ou mudar de rumo no caminho.
Não depende do Django: roda também na tarefa do GitHub que atualiza a demo.
"""

from datetime import datetime, timedelta
from io import BytesIO
from math import atan2, cos, degrees, hypot, radians, sqrt
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageFilter

KM_POR_GRAU = 111.2
RAIO = 150            # km: chuva mais longe que isso não entra no aviso
PERTO = 5             # km: dentro disso, está chovendo no viveiro
PASSA = 8             # km: a chuva "passa pelo viveiro" se chegar a essa distância dele
HORIZONTE = 4         # horas: previsão de chegada só até aqui (depois de 2 h, "pode chegar")
DESLOC_MAX = 20       # pontos da imagem que a chuva pode andar entre as duas imagens (~40 km)
JANELA = 200          # km em volta do viveiro usados para medir o movimento
MIN_PONTOS = 40       # menos chuva que isso na janela: o movimento não é confiável
MIN_SOBREPOSICAO = 0.3

DIRECOES = ["norte", "nordeste", "leste", "sudeste", "sul", "sudoeste", "oeste", "noroeste"]
INTENSIDADES = ["fraca", "moderada", "forte"]


def direcao(leste, norte):
    """Uma das 8 direções para um vetor em km (leste, norte)."""
    angulo = (degrees(atan2(leste, norte)) + 360) % 360   # 0 = norte, 90 = leste
    return DIRECOES[round(angulo / 45) % 8]


def ao(d):
    """"ao norte", "ao sul", "a leste", "a noroeste"."""
    return f"ao {d}" if d in ("norte", "sul") else f"a {d}"


def intensidade(r, g, b):
    """0 fraca (azul), 1 moderada (verde), 2 forte (amarelo, laranja, vermelho) pela escala de cores do radar."""
    if r > 180 and g > 140 and b < 120 or r > 180 and g < 120:
        return 2
    if g > 140 and r < 150 and b < 150:
        return 1
    return 0


def mascara(img):
    """Onde tem chuva (modo "1"), sem os pontinhos soltos: fica o que tem chuva em pelo menos 5 dos 9 vizinhos."""
    alfa = img.getchannel("A").point(lambda a: 255 if a > 0 else 0)
    return alfa.filter(ImageFilter.BoxBlur(1)).point(lambda v: 255 if v > 141 else 0).convert("1")


class Grade:
    """Conversão entre os pontos da imagem e km a partir do viveiro (leste, norte)."""

    def __init__(self, limites, tamanho, lat, lon):
        self.l, (self.w, self.h), self.lat, self.lon = limites, tamanho, lat, lon
        self.c = cos(radians(lat))
        self.km_x = (limites["lon_max"] - limites["lon_min"]) / self.w * KM_POR_GRAU * self.c
        self.km_y = (limites["lat_max"] - limites["lat_min"]) / self.h * KM_POR_GRAU
        self.px = ((lon - limites["lon_min"]) / (limites["lon_max"] - limites["lon_min"]) * self.w,
                   (limites["lat_max"] - lat) / (limites["lat_max"] - limites["lat_min"]) * self.h)
        # o radar enxerga um círculo inscrito na imagem
        centro_lat, centro_lon = (limites["lat_min"] + limites["lat_max"]) / 2, (limites["lon_min"] + limites["lon_max"]) / 2
        self.raio_radar = (limites["lat_max"] - limites["lat_min"]) / 2 * KM_POR_GRAU
        self.centro = ((centro_lon - lon) * KM_POR_GRAU * self.c, (centro_lat - lat) * KM_POR_GRAU)

    def km(self, x, y):
        return ((x + 0.5 - self.px[0]) * self.km_x, (self.px[1] - y - 0.5) * self.km_y)

    def alcance(self):
        """Até quantos km do viveiro o radar enxerga em todas as direções."""
        return self.raio_radar - hypot(*self.centro)

    def enxerga(self, p):
        return hypot(p[0] - self.centro[0], p[1] - self.centro[1]) <= self.raio_radar


def chuvas_perto(img, masc, grade):
    """[(leste_km, norte_km, intensidade)] de cada ponto de chuva a até RAIO km do viveiro."""
    px, cores = masc.load(), img.load()
    r_x, r_y = RAIO / grade.km_x, RAIO / grade.km_y
    x0, x1 = max(0, int(grade.px[0] - r_x)), min(grade.w, int(grade.px[0] + r_x) + 1)
    y0, y1 = max(0, int(grade.px[1] - r_y)), min(grade.h, int(grade.px[1] + r_y) + 1)
    pontos = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[x, y]:
                p = grade.km(x, y)
                if hypot(*p) <= RAIO and grade.enxerga(p):
                    pontos.append((p[0], p[1], intensidade(*cores[x, y][:3])))
    return pontos


def movimento(antes, agora, grade, horas):
    """(leste, norte) em km/h da chuva em volta do viveiro, ou None quando não dá para saber."""
    rx, ry = int(JANELA / grade.km_x), int(JANELA / grade.km_y)
    fx, fy = int(grade.px[0]), int(grade.px[1])
    caixa = (fx - rx, fy - ry, fx + rx, fy + ry)
    a = agora.crop(caixa)
    total = antes.crop(caixa).histogram()[255]
    if total < MIN_PONTOS or horas <= 0:
        return None
    melhor, desloc = -1, (0, 0)
    for dy in range(-DESLOC_MAX, DESLOC_MAX + 1):
        for dx in range(-DESLOC_MAX, DESLOC_MAX + 1):
            # a chuva andou (dx, dy): o que está em p agora estava em p - (dx, dy)
            b = antes.crop((caixa[0] - dx, caixa[1] - dy, caixa[2] - dx, caixa[3] - dy))
            n = ImageChops.logical_and(a, b).histogram()[255]
            if n > melhor:
                melhor, desloc = n, (dx, dy)
    if melhor < MIN_SOBREPOSICAO * total:
        return None
    return (desloc[0] * grade.km_x / horas, -desloc[1] * grade.km_y / horas)


def chegada(p, v):
    """Em quantas horas a chuva no ponto p (km) chega a PASSA km do viveiro andando com v (km/h); None se não chega."""
    v2 = v[0] ** 2 + v[1] ** 2
    if v2 < 1:   # parada (menos de 1 km/h)
        return None
    t = -(p[0] * v[0] + p[1] * v[1]) / v2   # quando fica mais perto
    perto = hypot(p[0] + v[0] * t, p[1] + v[1] * t)
    if t <= 0 or perto > PASSA:
        return None
    return max(0.0, t - sqrt(PASSA ** 2 - perto ** 2) / sqrt(v2))


def avisar(agora_img, antes_img, limites, lat, lon, horas):
    """O aviso: {texto, chovendo, distancia_km, direcao, intensidade, chega_em_horas, alcance_km}.

    antes_img pode ser None (só a posição, sem movimento); horas é o tempo entre as duas imagens.
    """
    grade = Grade(limites, agora_img.size, lat, lon)
    masc = mascara(agora_img)
    pontos = chuvas_perto(agora_img, masc, grade)
    alcance = max(0, min(RAIO, round(grade.alcance())))
    aviso = {"chovendo": False, "distancia_km": None, "direcao": None, "intensidade": None, "chega_em_horas": None,
             "move_para": None, "velocidade_kmh": None, "alcance_km": alcance}
    if not pontos:
        aviso["texto"] = f"Sem chuva no radar num raio de {alcance} km do viveiro."
        return aviso
    mais_perto = min(pontos, key=lambda p: hypot(p[0], p[1]))
    dist = hypot(mais_perto[0], mais_perto[1])
    # a força da chuva é a mais forte que está a até 10 km do ponto mais perto
    forca = max(p[2] for p in pontos if hypot(p[0] - mais_perto[0], p[1] - mais_perto[1]) <= 10)
    aviso.update(distancia_km=round(dist), direcao=direcao(mais_perto[0], mais_perto[1]), intensidade=INTENSIDADES[forca])
    if dist <= PERTO:
        aviso["chovendo"] = True
        aviso["texto"] = f"Chuva {INTENSIDADES[forca]} no viveiro agora."
        return aviso

    v = movimento(mascara(antes_img), masc, grade, horas) if antes_img is not None else None
    onde = f"Chuva {INTENSIDADES[forca]} a {round(dist)} km {ao(aviso['direcao'])}"
    if v is None:
        aviso["texto"] = f"{onde} do viveiro."
        return aviso
    aviso.update(move_para=direcao(*v) if hypot(*v) >= 3 else None, velocidade_kmh=round(hypot(*v)))
    chegam = [(t, p) for p in pontos if (t := chegada(p[:2], v)) is not None and t <= HORIZONTE]
    if chegam:
        # a que vem não é sempre a mais perto: a distância e a direção passam a ser as da primeira que chega
        t, vem = min(chegam, key=lambda c: c[0])
        forca_vem = max(p[2] for tc, p in chegam if tc <= t + 0.5)
        aviso.update(chega_em_horas=round(t, 2), intensidade=INTENSIDADES[forca_vem],
                     distancia_km=round(hypot(vem[0], vem[1])), direcao=direcao(vem[0], vem[1]))
        aviso["texto"] = (f"Chuva {INTENSIDADES[forca_vem]} vindo para o viveiro, "
                          f"a {aviso['distancia_km']} km {ao(aviso['direcao'])}.")
    elif aviso["move_para"]:
        aviso["texto"] = f"{onde} do viveiro, andando para {aviso['move_para']}: não deve passar pelo viveiro nas próximas {HORIZONTE} horas."
    else:
        aviso["texto"] = f"{onde} do viveiro, quase parada."
    return aviso


def abrir(conteudo):
    """Imagem do radar (bytes do PNG) em RGBA."""
    return Image.open(BytesIO(conteudo)).convert("RGBA")


BRASILIA = ZoneInfo("America/Sao_Paulo")
INTERVALO = timedelta(minutes=40)       # o movimento sai da imagem nova e de uma de mais ou menos 40 min antes
INTERVALO_MIN = timedelta(minutes=20)


def por_volta(quando):
    """"por volta das 15h30", "por volta da 1h", "por volta da meia-noite"."""
    h, m = quando.hour, f"{quando.minute:02d}" if quando.minute else ""
    if h == 0:
        return "por volta da meia-noite" + (f" e {quando.minute}" if m else "")
    if h == 12:
        return "por volta do meio-dia" + (f" e {quando.minute}" if m else "")
    return f"por volta {'da' if h == 1 else 'das'} {h}h{m}"


def duracao(horas):
    minutos = max(10, round(horas * 60 / 10) * 10)
    return f"{minutos} min" if minutos < 60 else f"{minutos // 60}h{minutos % 60:02d}".replace("h00", "h")


def do_radar(quadros, limites, lat, lon, baixar, agora):
    """O aviso com a imagem mais nova e uma de ~40 min antes, já com a hora de chegada no texto.

    quadros: [{imagem, hora}] do mais velho ao mais novo; baixar(url) devolve os bytes de uma imagem.
    """
    novo = quadros[-1]
    hora_novo = datetime.fromisoformat(novo["hora"])
    antes = [q for q in quadros[:-1] if hora_novo - datetime.fromisoformat(q["hora"]) >= INTERVALO_MIN]
    velho = min(antes, key=lambda q: abs(hora_novo - datetime.fromisoformat(q["hora"]) - INTERVALO)) if antes else None
    img = abrir(baixar(novo["imagem"]))
    img_velho = abrir(baixar(velho["imagem"])) if velho else None
    horas = (hora_novo - datetime.fromisoformat(velho["hora"])).total_seconds() / 3600 if velho else 0
    dados = avisar(img, img_velho, limites, lat, lon, horas)
    dados["hora_imagem"] = novo["hora"]
    dados["chega_em"] = None
    if dados["chega_em_horas"] is not None:
        chega = hora_novo + timedelta(hours=dados["chega_em_horas"])
        dados["chega_em"] = chega.isoformat()
        if chega <= agora + timedelta(minutes=10):
            dados["texto"] += " Deve chegar a qualquer momento."
        else:
            # a hora de chegada redonda de 15 em 15 min: a conta não tem precisão de minutos
            local = chega.astimezone(BRASILIA)
            local = local.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=round(local.minute / 15) * 15)
            # de longe a extrapolação erra mais: até 2 h "deve chegar", depois "pode chegar"
            verbo = "Deve" if dados["chega_em_horas"] <= 2 else "Pode"
            dados["texto"] += f" {verbo} chegar {por_volta(local)} (em uns {duracao((chega - agora).total_seconds() / 3600)})."
    return dados
