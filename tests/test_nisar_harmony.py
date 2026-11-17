"""NASA Harmony NISAR GCOV: solicitudes mínimas, descargas acotadas y rechazo seguro.

Ninguna prueba contacta NASA ni descarga imágenes reales.
"""
from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace as NS

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from utils import nisar_harmony as h

AOI = (-76.8, 7.55, -76.55, 7.8)
GRANULE = "NISAR_L2_PR_GCOV_033_148_A_005_2005_DHDH_M_20261022T104722_20261022T104757_P05036_N_F_J_001"
CAPAS = ("HHHH", "HVHV", "mask", "numberOfLooks")
VARIABLES = ["/science/LSAR/GCOV/grids/frequencyA/" + c for c in CAPAS]


class Respuesta(io.BytesIO):
    def __init__(self, contenido, url):
        super().__init__(contenido)
        self.url = url
        self.headers = {"Content-Length": str(len(contenido))}

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def caps():
    return {"coleccion": "C3622241360-ASF", "variables": set(VARIABLES)}


def candidato(pols=("HH", "HV")):
    return NS(granule=GRANULE, nombre=NS(pol_a=pols))


def test_capacidades_publicas_mock_sin_secreto():
    payload = {"conceptId": "C3622241360-ASF", "shortName": "NISAR_L2_GCOV_V1",
               "variables": [{"name": v} for v in VARIABLES]}
    pedidos = []
    def abrir(req, timeout):
        pedidos.append(req)
        return Respuesta(json.dumps(payload).encode(), req.full_url)
    resultado = h.capacidades(abrir)
    assert resultado["coleccion"] == "C3622241360-ASF"
    assert set(VARIABLES) == resultado["variables"]
    assert len(pedidos) == 1
    assert pedidos[0].get_header("Authorization") is None


@pytest.mark.parametrize(
    ("codigo", "motivo"),
    [
        (401, "acceso rechazado"),
        (403, "acceso rechazado"),
        (404, "no encontró capacidades"),
        (429, "límite temporal"),
        (503, "fallo del servicio"),
    ],
)
def test_capacidades_http_diagnostico_seguro(codigo, motivo):
    def abrir(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url + "&signature=TOKEN_PRIVADO",
            codigo, "mensaje remoto privado", {}, None,
        )

    with pytest.raises(h.ErrorHarmony) as exc:
        h.capacidades(abrir, dormir=lambda _: None)
    mensaje = str(exc.value)
    assert f"HTTP {codigo}" in mensaje
    assert motivo in mensaje
    assert "TOKEN_PRIVADO" not in mensaje
    assert "mensaje remoto privado" not in mensaje
    assert "No se descargó ningún GeoTIFF" in mensaje


def test_capacidades_distingue_timeout_y_error_de_red():
    for causa, esperado in [
        (TimeoutError("privado"), "agotó su tiempo"),
        (urllib.error.URLError("privado"), "No se logró conectar"),
    ]:
        def abrir(req, timeout):
            raise causa

        with pytest.raises(h.ErrorHarmony) as exc:
            h.capacidades(abrir, dormir=lambda _: None)
        assert esperado in str(exc.value)
        assert "privado" not in str(exc.value)



def test_capacidades_recupera_http_transitorio_en_segundo_intento():
    llamadas = []
    esperas = []
    payload = {
        "conceptId": "C3622241360-ASF",
        "shortName": "NISAR_L2_GCOV_V1",
        "variables": [{"name": v} for v in VARIABLES],
    }

    def abrir(req, timeout):
        llamadas.append(req)
        if len(llamadas) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "error temporal", {}, None)
        return Respuesta(json.dumps(payload).encode(), req.full_url)

    resultado = h.capacidades(abrir, dormir=esperas.append)
    assert resultado["coleccion"] == "C3622241360-ASF"
    assert len(llamadas) == 2
    assert esperas == [1]
    assert all(req.get_header("Authorization") is None for req in llamadas)


def test_capacidades_recupera_error_de_red_y_limita_reintentos():
    llamadas = []
    esperas = []

    def abrir(req, timeout):
        llamadas.append(req)
        raise urllib.error.URLError("PRIVATE_URL_SIGNED_DATA")

    with pytest.raises(h.ErrorHarmony) as exc:
        h.capacidades(abrir, dormir=esperas.append)
    assert len(llamadas) == 3
    assert esperas == [1, 2]
    assert "PRIVATE_URL_SIGNED_DATA" not in str(exc.value)
    assert "No se descargó ningún GeoTIFF" in str(exc.value)


def test_capacidades_no_reintenta_http_403():
    llamadas = []

    def abrir(req, timeout):
        llamadas.append(req)
        raise urllib.error.HTTPError(req.full_url, 403, "prohibido", {}, None)

    with pytest.raises(h.ErrorHarmony, match="HTTP 403"):
        h.capacidades(abrir, dormir=lambda _: pytest.fail("no debe reintentar 403"))
    assert len(llamadas) == 1


def test_capacidades_json_invalido_sin_filtrar_respuesta():
    def abrir(req, timeout):
        return Respuesta(b"no es JSON", req.full_url)

    with pytest.raises(h.ErrorHarmony, match="JSON inválidos"):
        h.capacidades(abrir)


def test_solo_polarizaciones_presentes_y_mascara():
    s = h.especificar(candidato(), AOI, caps())
    assert s.capas == CAPAS
    assert s.variables == tuple(VARIABLES)
    assert s.bbox == AOI
    assert s.coleccion == "C3622241360-ASF"
    with pytest.raises(h.ErrorHarmony, match="variables necesarias"):
        h.especificar(candidato(), AOI, {"coleccion": s.coleccion,
                                          "variables": {VARIABLES[0], VARIABLES[1]}})
    with pytest.raises(h.ErrorHarmony, match="polarización copolar"):
        h.especificar(candidato(pols=("HV",)), AOI, caps())


def test_no_resample_ni_crs_en_solicitud():
    pytest.importorskip("harmony")
    spec = h.especificar(candidato(), AOI, caps())
    req = h.construir_solicitud(spec)
    assert list(req.variables) == list(VARIABLES)
    assert req.crs is None and req.width is None and req.height is None
    assert req.spatial.w == AOI[0]
    assert req.max_results == 1
    assert req.format == "image/tiff"


def test_no_urls_ajenas_o_http_ni_capa_b():
    h._url_datos("https://harmony.earthdata.nasa.gov/results/nisar_HHHH.tif")
    h._url_datos("https://harmony-test.s3.us-west-2.amazonaws.com/a.tif?firma=abc")
    for url in ("http://harmony.earthdata.nasa.gov/a.tif",
                "https://example.com/a.tif",
                "https://127.0.0.1/a.tif",
                "https://user:password@harmony.earthdata.nasa.gov/a.tif"):
        with pytest.raises(h.ErrorHarmony):
            h._url_datos(url)
    assert h._etiqueta("https://harmony.earthdata.nasa.gov/x_frequencyA_HHHH.tif", CAPAS) == "HHHH"
    with pytest.raises(h.ErrorHarmony):
        h._etiqueta("https://harmony.earthdata.nasa.gov/x_frequencyB_HHHH.tif", CAPAS)
    with pytest.raises(h.ErrorHarmony):
        h._etiqueta("https://harmony.earthdata.nasa.gov/no_identificable.tif", CAPAS)


def tiff(dtype="float32", cambio_x=0):
    memoria = MemoryFile()
    datos = np.ones((32, 32), dtype=dtype)
    with memoria.open(driver="GTiff", width=32, height=32, count=1,
                      dtype=dtype, crs="EPSG:32618",
                      transform=from_origin(310000 + cambio_x, 850000, 20, 20)) as dst:
        dst.write(datos, 1)
    return memoria.read()


def test_descarga_limitada_sin_token_ni_part(monkeypatch, tmp_path):
    url = "https://harmony.earthdata.nasa.gov/frequencyA_HHHH.tif?signature=PRIVATE"
    data = tiff()
    assert len(data) > 1024
    seen = []
    def abrir(req, timeout):
        seen.append(req)
        return Respuesta(data, url)
    p = tmp_path / "HHHH.tif"
    size, sha = h._descargar_cota(url, p, len(data) + 1, abrir=abrir)
    assert size == len(data) and len(sha) == 64
    assert p.read_bytes() == data and not list(tmp_path.glob("*.part"))
    assert seen[0].get_header("Authorization") is None
    with pytest.raises(h.ErrorHarmony):
        h._descargar_cota(url, tmp_path / "otro.tif", len(data) - 1, abrir=abrir)
    assert not list(tmp_path.glob("*.part"))


class ClienteFake:
    def __init__(self):
        self.cancelado = False
        self.solicitudes = []

    def submit(self, req):
        self.solicitudes.append(req)
        return "job_1234567890123"

    def status(self, job):
        return {"status": "successful", "progress": 100}

    def result_urls(self, job):
        return [f"https://harmony.earthdata.nasa.gov/NISAR_frequencyA_{c}.tif"
                for c in CAPAS]

    def cancel(self, job):
        self.cancelado = True


def test_obtener_solo_4_geotiff_validos_con_trazabilidad(monkeypatch, tmp_path):
    data = {c: tiff(dtype="uint8" if c == "mask" else "float32") for c in CAPAS}
    monkeypatch.setattr(h.shutil, "disk_usage", lambda _: NS(free=2 * 1024**3))
    c = ClienteFake()
    def abrir(req, timeout):
        capa = h._etiqueta(req.full_url, CAPAS)
        return Respuesta(data[capa], req.full_url)
    spec = h.especificar(candidato(), AOI, caps())
    meta = h.obtener(spec, tmp_path, cliente=c, abrir=abrir, dormir=lambda _: None, limite_bytes=8 * 1024**2)
    assert meta["estado"] == "INSUMOS_GCOV_SIN_CLASIFICAR"
    assert meta["bytes_totales"] == sum(map(len, data.values()))
    assert set(a["capa"] for a in meta["archivos"]) == set(CAPAS)
    assert all(len(a["sha256"]) == 64 for a in meta["archivos"])
    final = tmp_path / meta["carpeta_relativa"]
    assert (final / "manifest.json").exists()
    assert not list(tmp_path.glob(".preparando-*"))
    assert h.obtener(spec, tmp_path, cliente=c, abrir=abrir, limite_bytes=8 * 1024**2) == meta
    assert len(c.solicitudes) == 1
    assert c.solicitudes[0].crs is None  # mantener resolución nativa


def test_no_publicar_si_capas_no_coinciden(monkeypatch, tmp_path):
    monkeypatch.setattr(h.shutil, "disk_usage", lambda _: NS(free=2 * 1024**3))
    c = ClienteFake()
    c.result_urls = lambda _: ["https://harmony.earthdata.nasa.gov/NISAR_frequencyA_HHHH.tif"]
    with pytest.raises(h.ErrorHarmony, match="Faltan capas"):
        h.obtener(h.especificar(candidato(), AOI, caps()), tmp_path, cliente=c,
                  dormir=lambda _: None)
    assert c.cancelado
    assert not list(tmp_path.glob(".preparando-*"))


def test_cap_8_mb_es_pequeno_para_hdf5_pero_suficiente_cog(monkeypatch, tmp_path):
    monkeypatch.setattr(h.shutil, "disk_usage", lambda _: NS(free=2 * 1024**3))
    spec = h.especificar(candidato(), AOI, caps())
    c = ClienteFake()
    c.status = lambda _: {"status": "failed"}
    with pytest.raises(h.ErrorHarmony):
        h.obtener(spec, tmp_path, cliente=c, dormir=lambda _: None, limite_bytes=8 * 1024**2)
    assert not any(p.suffix == ".h5" for p in tmp_path.rglob("*"))



def test_html_login_10kb_no_se_guarda_como_tiff(tmp_path):
    url = "https://harmony.earthdata.nasa.gov/resultados_frequencyA_HHHH.tif"
    pagina_login = b"<html><body>Earthdata Login</body></html>" + b" " * 10000
    destino = tmp_path / "HHHH.tif"
    with pytest.raises(h.ErrorHarmony, match="cabecera TIFF"):
        h._descargar_cota(url, destino, 1024**2,
                          abrir=lambda req, timeout: Respuesta(pagina_login, url))
    assert not destino.exists()
    assert not list(tmp_path.glob("*.part"))


def test_content_type_html_rechazado_antes_de_guardar(tmp_path):
    url = "https://harmony.earthdata.nasa.gov/frequencyA_HHHH.tif"
    class Html(Respuesta):
        def __init__(self):
            super().__init__(b"<html>Login</html>" * 200, url)
            self.headers["Content-Type"] = "text/html; charset=utf-8"

    with pytest.raises(h.ErrorHarmony, match="página de autenticación"):
        h._descargar_cota(url, tmp_path / "HHHH.tif", 1024**2,
                          abrir=lambda req, timeout: Html())
    assert not list(tmp_path.iterdir())


def test_descarga_usa_sesion_autenticada_de_cliente(tmp_path):
    url = "https://harmony.earthdata.nasa.gov/frequencyA_HHHH.tif"
    data = tiff()

    class RespuestaRequests:
        headers = {"Content-Type": "image/tiff"}
        status_code = 200

        def __init__(self):
            self.url = url

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Sesion:
        llamadas = 0

        def get(self, url_arg, *, stream, timeout, headers):
            assert url_arg == url
            assert stream is True
            assert headers["Accept-Encoding"] == "identity"
            self.llamadas += 1
            return RespuestaRequests()

    sesion = Sesion()
    cliente = NS(session=sesion)
    destino = tmp_path / "HHHH.tif"
    tam, digest = h._descargar_cota(url, destino, 1024**2, cliente=cliente)
    assert sesion.llamadas == 1
    assert tam == len(data) and len(digest) == 64
    assert destino.read_bytes() == data


def test_no_descarga_anonima_si_falta_cliente(tmp_path):
    with pytest.raises(h.ErrorHarmony, match="cliente Harmony autenticado"):
        h._descargar_cota("https://harmony.earthdata.nasa.gov/a.tif",
                          tmp_path / "a.tif", 1024**2)



def test_modo_cambio_solicita_solo_tres_capas_de_uso_real():
    """V9: gamma0 copolar y las dos QA; HV/HVHV no se usa para ΔdB."""
    spec = h.especificar(candidato(), AOI, caps(), solo_cambio=True)
    assert spec.capas == ("HHHH", "mask", "numberOfLooks")
    assert len(spec.variables) == 3
    assert all("HVHV" not in item for item in spec.variables)
    assert h.especificar(candidato(), AOI, caps()).capas == CAPAS
    vv = candidato(pols=("VV", "VH"))
    vv_caps = {"coleccion": "C3622241360-ASF",
               "variables": {"/science/LSAR/GCOV/grids/frequencyA/" + c
                             for c in ("VVVV", "VHVH", "mask", "numberOfLooks")}}
    assert h.especificar(vv, AOI, vv_caps, solo_cambio=True).capas == (
        "VVVV", "mask", "numberOfLooks",
    )


def test_cog_grande_se_rechaza_antes_de_transferir_y_sin_fugar_url(tmp_path):
    """No solicitar bytes enormes ni exponer parámetros firmados de NASA."""
    url = "https://harmony.earthdata.nasa.gov/frequencyA_HHHH.tif?secret=NO_MOSTRAR"
    contenido = tiff()
    class COGGigante(Respuesta):
        def __init__(self):
            super().__init__(contenido, url)
            self.headers["Content-Length"] = str(300 * 1024**2)
    destino = tmp_path / "HHHH.tif"
    llamados = []
    def abrir(req, timeout):
        llamados.append(req)
        return COGGigante()
    with pytest.raises(h.ErrorHarmony, match="COG_DEMASIADO_GRANDE") as exc:
        h._descargar_cota(url, destino, max_bytes=100 * 1024**2, abrir=abrir)
    assert "300.0 MiB" in str(exc.value)
    assert "100.0 MiB" in str(exc.value)
    assert "NO_MOSTRAR" not in str(exc.value)
    assert len(llamados) == 1
    assert not destino.exists() and not destino.with_suffix(".tif.part").exists()



def test_harmony_1gib_compartido_con_tope_estricto_por_capa():
    """El entorno dispone de disco, pero los límites por operación persisten."""
    assert h.MAX_TOTAL_BYTES == 1024 * 1024**2
    assert h.MAX_UN_ARCHIVO == 512 * 1024**2
    assert h.BLOQUE <= 2 * 1024**2


def test_harmony_rechaza_presupuesto_superior_a_1gib_antes_de_crear_archivos(tmp_path):
    """Ni con mucho almacenamiento se permite descargar sin un techo."""
    spec = h.especificar(candidato(), AOI, caps(), solo_cambio=True)
    with pytest.raises(h.ErrorHarmony, match="fuera del límite"):
        h.obtener(spec, tmp_path, limite_bytes=h.MAX_TOTAL_BYTES + 1,
                  cliente=ClienteFake())
    assert not any(tmp_path.iterdir())


def test_harmony_usa_tope_individual_aun_con_presupuesto_1gib(monkeypatch, tmp_path):
    """Un COG de 600 MiB no se acepta por tener 1 GiB para todo el par."""
    spec = h.especificar(candidato(), AOI, caps(), solo_cambio=True)
    monkeypatch.setattr(h.shutil, "disk_usage",
                        lambda _: NS(free=3 * 1024**3))
    class ClienteTres(ClienteFake):
        def result_urls(self, job):
            return [f"https://harmony.earthdata.nasa.gov/NISAR_frequencyA_{c}.tif"
                    for c in spec.capas]
    class RespuestaGrande(Respuesta):
        def __init__(self, url):
            super().__init__(tiff(), url)
            self.headers["Content-Length"] = str(600 * 1024**2)
    calls = []
    def abrir(req, timeout):
        calls.append(req.full_url)
        return RespuestaGrande(req.full_url)
    with pytest.raises(h.ErrorHarmony, match="COG_DEMASIADO_GRANDE"):
        h.obtener(spec, tmp_path, limite_bytes=1024 * 1024**2,
                  cliente=ClienteTres(), abrir=abrir, dormir=lambda _: None)
    assert len(calls) == 1
    assert not list(tmp_path.glob(".preparando-*"))
