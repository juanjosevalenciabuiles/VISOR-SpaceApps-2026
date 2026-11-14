"""ECO (guía flotante) y la ficha del lugar del panel derecho: estados, clips, Wikipedia y chips (sin red)."""
import io
import json
import subprocess
import shutil
import tomllib
import urllib.error
from pathlib import Path

import pytest

from components import eco
from utils import trabajos, wikipedia_lugar

RAIZ = Path(__file__).resolve().parents[1]
CLIPS = RAIZ / "static" / "eco"


# --------------------------------------------------------------------------- ECO: estados

def test_eco_saluda_sin_zona():
    e = eco.decidir(None, False, False, None, False, False)
    assert e.clip == "saludo" and e.animado and "Busca un lugar de Colombia" in e.mensaje


def test_eco_enfoca_la_zona_y_dice_donde_esta():
    e = eco.decidir("Chigorodó, Antioquia", True, True, None, False, False)
    assert e.clip == "enfoque" and "Chigorodó, Antioquia" in e.mensaje and "revisando" in e.mensaje
    e = eco.decidir("Chigorodó, Antioquia", True, False, None, False, False)
    assert "Analizar" in e.mensaje


@pytest.mark.parametrize("estado", trabajos.ACTIVOS)
def test_eco_escanea_mientras_hay_un_trabajo(estado):
    e = eco.decidir("X", True, False, {"estado": estado}, False, False)
    assert e.clip == "escaneo" and e.animado


def test_eco_celebra_solo_con_resultado_y_no_inventa_hallazgos():
    e = eco.decidir("X", True, False, {"estado": trabajos.APTO}, True, False)
    assert e.clip == "listo" and "no una inundación confirmada" in e.mensaje
    assert not any(c.isdigit() for c in e.mensaje), "ECO no da cifras propias"
    assert "historial" in eco.decidir("X", True, False, None, True, True).mensaje


@pytest.mark.parametrize("estado", [trabajos.ERROR, trabajos.BLOQUEADO, trabajos.CANCELADO])
def test_eco_no_celebra_errores(estado):
    e = eco.decidir("X", True, False, {"estado": estado, "error": "faltan RTC"}, False, False)
    assert e.clip != "listo" and not e.animado
    if estado != trabajos.CANCELADO:
        assert "faltan RTC" in e.mensaje and e.tono == "alerta"


def test_html_de_eco_video_mudo_en_bucle_con_respaldo():
    h = eco.avatar_html(eco.decidir(None, False, False, None, False, False))
    for atributo in ("autoplay", "loop", "muted", "playsinline"):
        assert atributo in h
    assert "eco_01_saludo.webm" in h and "eco_01_saludo.mp4" in h and "eco_01_saludo.webp" in h
    quieto = eco.avatar_html(eco.EstadoEco("enfoque", "x", animado=False))
    assert "<video" not in quieto and "eco_02_enfoque.webp" in quieto
    assert "&lt;b&gt;" in eco.burbuja_html(eco.EstadoEco("saludo", "<b>")), "el mensaje se escapa"


# --------------------------------------------------------------------------- ECO: archivos

def test_clips_existen_son_ligeros_y_se_sirven():
    for nombre in eco.CLIPS.values():
        for ext, limite in ((".webm", 300_000), (".mp4", 300_000), (".webp", 60_000)):
            f = CLIPS / f"{nombre}{ext}"
            assert f.is_file() and 0 < f.stat().st_size < limite, f
    config = tomllib.loads((RAIZ / ".streamlit" / "config.toml").read_text())
    assert config["server"]["enableStaticServing"] is True
    assert not any(p.suffix in (".tif", ".h5", ".json") for p in (RAIZ / "static").rglob("*")), "static/ no lleva datos"


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="sin ffprobe")
def test_clips_sin_audio_cuadrados_y_cortos():
    for f in sorted(CLIPS.glob("*.webm")) + sorted(CLIPS.glob("*.mp4")):
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                          str(f)], capture_output=True, text=True, check=True).stdout)
        tipos = [s["codec_type"] for s in info["streams"]]
        assert tipos == ["video"], f"{f.name}: {tipos}"
        v = info["streams"][0]
        assert v["width"] == v["height"] == 320
        assert 1.5 <= float(info["format"]["duration"]) <= 2.5


# --------------------------------------------------------------------------- Wikipedia (sin red)

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _abridor(respuestas: dict):
    """Simula urlopen: busca la primera clave contenida en la URL."""
    llamadas = []

    def abrir(req, timeout=None):
        url = req.full_url
        llamadas.append(url)
        for clave, valor in respuestas.items():
            if clave in url:
                if valor == 404:
                    raise urllib.error.HTTPError(url, 404, "no", {}, None)
                return _Resp(json.dumps(valor).encode())
        raise AssertionError(f"URL inesperada {url}")
    abrir.llamadas = llamadas
    return abrir


RESUMEN = {"type": "standard", "title": "Chigorodó", "description": "municipio de Antioquia, Colombia",
           "extract": "Chigorodó es un municipio de Colombia, ubicado en la subregión de Urabá del departamento de "
                      "Antioquia. Limita por el norte con Turbo y Carepa. " + "Texto largo. " * 40,
           "content_urls": {"desktop": {"page": "https://es.wikipedia.org/wiki/Chigorod%C3%B3"}},
           "thumbnail": {"source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Iglesia_(X).jpg/320px-Iglesia_(X).jpg"},
           "originalimage": {"source": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Iglesia_(X).jpg", "width": 2000}}
CREDITO = {"query": {"pages": {"1": {"imageinfo": [{"extmetadata": {
    "Artist": {"value": "<a href='x'>Ana Pérez</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}}}}


def test_wikipedia_prueba_primero_municipio_departamento_y_trae_foto_con_credito():
    abrir = _abridor({"Chigorod%C3%B3_%28Antioquia%29": 404, "summary/Chigorod%C3%B3": RESUMEN, "w/api.php": CREDITO})
    r = wikipedia_lugar.consultar("Chigorodó", "Antioquia", abrir=abrir)
    assert "Antioquia%29" in abrir.llamadas[0], "primero «Municipio (Departamento)»"
    f = r["items"][0]
    assert r["estado"] == "CON_RESULTADOS" and f["title"] == "Chigorodó"
    assert f["imagen"].endswith("640px-Iglesia_(X).jpg")
    assert f["credito"] == {"licencia": "CC BY-SA 4.0", "autor": "Ana Pérez",
                            "pagina": "https://commons.wikimedia.org/wiki/File:Iglesia_%28X%29.jpg"}
    assert len(f["extract"]) <= wikipedia_lugar.LARGO_RESUMEN + 1 and f["extract"].endswith(".")


def test_wikipedia_sin_licencia_no_hay_foto():
    abrir = _abridor({"%28Antioquia%29": RESUMEN, "w/api.php": {"query": {"pages": {"1": {"imageinfo": [{}]}}}}})
    f = wikipedia_lugar.consultar("Chigorodó", "Antioquia", abrir=abrir)["items"][0]
    assert f["imagen"] is None and f["credito"] is None and f["extract"]


def test_wikipedia_rechaza_paginas_de_otro_lugar_o_desambiguacion():
    espana = {**RESUMEN, "title": "Granada", "description": "ciudad de España", "extract": "Granada es una ciudad española."}
    desamb = {**RESUMEN, "type": "disambiguation"}
    abrir = _abridor({"%28Antioquia%29": desamb, "summary/Granada": espana})
    assert wikipedia_lugar.consultar("Granada", "Antioquia", abrir=abrir)["estado"] == "SIN_COINCIDENCIAS"
    assert not wikipedia_lugar.es_del_lugar({"extract": "municipio de Colombia en Boyacá"}, "Antioquia")


# --------------------------------------------------------------------------- Ficha: chips y foto

def test_chips_reflejan_el_estado_real_de_cada_fuente():
    from components import contexto_zona as cz
    from utils.contexto_local import ContextoLocal, Municipio
    local = ContextoLocal(municipios=[Municipio("Chigorodó", "Antioquia", "05172", .63),
                                      Municipio("Carepa", "Antioquia", "05147", .25)], area_km2=764.2)
    alerta = {"estado": "CON_RESULTADOS", "items": [{"gravedad": 2}, {"gravedad": 1}]}
    h = cz.chips(local, {"ideam": alerta, "eonet": {"estado": "SIN_COINCIDENCIAS", "items": []}})
    assert "764 km²" in h and "2 municipios" in h and "2 alertas naranja" in h and "0 eventos NASA" in h
    h = cz.chips(local, {"ideam": {"estado": "ERROR_FUENTE"}, "eonet": {"estado": "CONSULTANDO"}})
    assert "IDEAM no disponible" in h and "NASA: consultando" in h and "Sin alertas" not in h
    barra = cz.barra_municipios(local)
    assert "Chigorodó <b>63 %</b>" in barra and "width:25.0%" in barra


def test_foto_cae_a_la_vista_satelital_con_credito():
    from components import contexto_zona as cz
    zona = {"clave": "k", "limites": (-76.80, 7.55, -76.55, 7.80)}
    h = cz._foto(zona, {"estado": "DESACTIVADO"})
    assert 'data-origen="satelite"' in h and "tiles.maps.eox.at" in h and "EOX" in h
    url = cz.tesela_satelital(zona["limites"])
    assert "/10/" in url, url
