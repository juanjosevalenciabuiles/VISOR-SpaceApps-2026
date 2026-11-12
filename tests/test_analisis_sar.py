"""Pruebas del motor de análisis temporal SAR, con rásteres sintéticos pequeños.

Ningún dato de estas pruebas es real: son matrices fabricadas para comprobar
la aritmética, la alineación espacial y el manejo de errores.
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils import analisis_sar as sar  # noqa: E402
from utils.analisis_sar import (  # noqa: E402
    AUMENTO, BAJA_EN_AMBAS, DISMINUCION, NODATA_DB, NODATA_MASCARA, SIN_CAMBIO,
    ErrorSAR, ParametrosCambio, analizar_par, describir_escena,
)
from utils.geotiff import leer_geotiff  # noqa: E402

ANTES = "S1C_IW_20260924T231502_DVP_RTC30_G_gpuned_1A2B_VV.tif"
DESPUES = "S1C_IW_20261006T231503_DVP_RTC30_G_gpuned_3C4D_VV.tif"
X0, Y0, RES = 300_000.0, 860_000.0, 30.0        # UTM 18N, cerca de Urabá
SIN_FILTRO = ParametrosCambio(ventana_speckle=1)


def crear_rtc(ruta, datos, x0=X0, y0=Y0, res=RES, crs="EPSG:32618", nodata=0.0, tags=None):
    datos = np.asarray(datos, dtype="float32")
    perfil = dict(driver="GTiff", height=datos.shape[0], width=datos.shape[1], count=1,
                  dtype="float32", transform=from_origin(x0, y0, res, res))
    if crs:
        perfil["crs"] = crs
    if nodata is not None:
        perfil["nodata"] = nodata
    with rasterio.open(ruta, "w", **perfil) as dst:
        dst.write(datos, 1)
        if tags:
            dst.update_tags(**tags)
    return ruta


def campo(lado=60, valor=0.1):
    """Potencia uniforme (0.1 = −10 dB)."""
    return np.full((lado, lado), valor, dtype="float32")


def par(tmp_path, antes=None, despues=None, **kw_despues):
    a = crear_rtc(tmp_path / ANTES, campo() if antes is None else antes)
    d = crear_rtc(tmp_path / DESPUES, campo() if despues is None else despues, **kw_despues)
    return a, d


def leer(ruta):
    with rasterio.open(ruta) as src:
        return src.read(1, masked=True), src


# ---------------------------------------------------------------------------
# Conversión a decibelios
# ---------------------------------------------------------------------------

def test_potencia_a_db_valores_conocidos():
    potencia = np.ma.masked_array(np.array([[1.0, 0.1, 0.01, 10.0]], dtype="float32"))
    db = sar.potencia_a_db(potencia)
    assert db[0].tolist() == pytest.approx([0.0, -10.0, -20.0, 10.0], abs=1e-5)
    assert db.dtype == np.float32 and not db.mask.any()


def test_potencia_a_db_nulos_y_no_positivos_quedan_sin_dato():
    datos = np.array([[0.0, -0.5, np.nan, np.inf, 0.2, 1e-12]], dtype="float32")
    db = sar.potencia_a_db(np.ma.masked_array(datos, mask=[[0, 0, 0, 0, 0, 0]]))
    assert db.mask.tolist() == [[True, True, True, True, False, False]]
    assert np.isfinite(np.ma.getdata(db)).all()                 # sin −inf ni NaN ocultos
    ya_enmascarado = np.ma.masked_array(np.array([[0.5, 0.5]], dtype="float32"), mask=[[True, False]])
    assert sar.potencia_a_db(ya_enmascarado).mask.tolist() == [[True, False]]


def test_a_potencia_segun_escala():
    datos = np.ma.masked_array(np.array([[0.5, 0.0, -1.0]], dtype="float32"))
    assert sar.a_potencia(datos, "power").mask.tolist() == [[False, True, True]]
    amplitud = sar.a_potencia(datos, "amplitude")
    assert float(amplitud[0, 0]) == pytest.approx(0.25) and amplitud.mask.tolist() == [[False, True, True]]
    en_db = sar.a_potencia(np.ma.masked_array(np.array([[-10.0, 0.0, -20.0]], dtype="float32")), "db")
    assert en_db[0].tolist() == pytest.approx([0.1, 1.0, 0.01], rel=1e-5)   # en dB el 0 y los negativos son válidos
    with pytest.raises(ErrorSAR):
        sar.a_potencia(datos, "lineal")


# ---------------------------------------------------------------------------
# Lectura y validación de escenas
# ---------------------------------------------------------------------------

def test_describir_escena_lee_el_nombre_hyp3(tmp_path):
    e = describir_escena(crear_rtc(tmp_path / ANTES, campo()))
    assert (e.plataforma, e.polarizacion, e.radiometria, e.escala) == ("S1C", "VV", "gamma0", "power")
    assert e.fecha == datetime(2026, 9, 24, 23, 15, 2) and e.es_hyp3
    assert e.crs.to_epsg() == 32618 and e.resolucion == (30.0, 30.0) and e.nodata == 0.0
    assert (e.ancho, e.alto) == (60, 60) and not e.avisos
    assert e.limites == pytest.approx((X0, Y0 - 1800, X0 + 1800, Y0))


def test_describir_escena_otras_variantes_del_nombre(tmp_path):
    vh = describir_escena(crear_rtc(tmp_path / "S1A_IW_20250101T101010_SHP_RTC10_G_sdufed_AB12_HH.tif", campo()))
    assert (vh.plataforma, vh.polarizacion, vh.radiometria, vh.escala) == ("S1A", "HH", "sigma0", "db")
    recortado = describir_escena(crear_rtc(tmp_path / ANTES.replace("_VV.tif", "_VH_clip.tif"), campo()))
    assert recortado.polarizacion == "VH" and recortado.es_hyp3


def test_escena_sin_nombre_hyp3_necesita_polarizacion(tmp_path):
    ruta = crear_rtc(tmp_path / "recorte.tif", campo(), nodata=None)
    with pytest.raises(ErrorSAR, match="polarización"):
        describir_escena(ruta)
    e = describir_escena(ruta, polarizacion="vh", fecha="2026-09-24")
    assert e.polarizacion == "VH" and e.fecha == datetime(2026, 9, 24) and e.escala == "power"
    assert not e.es_hyp3 and e.plataforma is None
    assert any("NoData" in a for a in e.avisos) and any("convención" in a for a in e.avisos)
    assert any("se asume potencia" in a for a in e.avisos)
    with pytest.raises(ErrorSAR, match="Fecha no reconocida"):
        describir_escena(ruta, polarizacion="VH", fecha="24 de septiembre")
    with pytest.raises(ErrorSAR, match="Escala"):
        describir_escena(ruta, polarizacion="VH", escala="lineal")


def test_polarizacion_indicada_no_puede_contradecir_el_nombre(tmp_path):
    with pytest.raises(ErrorSAR, match="según su nombre"):
        describir_escena(crear_rtc(tmp_path / ANTES, campo()), polarizacion="VH")


def test_errores_de_archivo(tmp_path):
    with pytest.raises(ErrorSAR, match="No se encontró"):
        describir_escena(tmp_path / ANTES)
    (tmp_path / "roto_VV.tif").write_bytes(b"no soy un tif")
    with pytest.raises(ErrorSAR, match="no es un GeoTIFF"):
        describir_escena(tmp_path / "roto_VV.tif", polarizacion="VV")
    with pytest.raises(ErrorSAR, match="CRS"):
        describir_escena(crear_rtc(tmp_path / "sin_crs.tif", campo(), crs=None), polarizacion="VV")
    with pytest.raises(ErrorSAR, match="pequeño"):
        describir_escena(crear_rtc(tmp_path / "mini.tif", np.ones((1, 1))), polarizacion="VV")
    with rasterio.open(tmp_path / "sin_geo.tif", "w", driver="GTiff", height=5, width=5, count=1,
                       dtype="float32", crs="EPSG:32618") as dst:
        dst.write(np.ones((5, 5), dtype="float32"), 1)
    with pytest.raises(ErrorSAR, match="georreferenciación"):
        describir_escena(tmp_path / "sin_geo.tif", polarizacion="VV")


def test_validar_par(tmp_path):
    a = describir_escena(crear_rtc(tmp_path / ANTES, campo()))
    d = describir_escena(crear_rtc(tmp_path / DESPUES, campo()))
    assert sar.validar_par(a, d) == []
    with pytest.raises(ErrorSAR, match="invertido"):
        sar.validar_par(d, a)
    with pytest.raises(ErrorSAR, match="mismo archivo"):
        sar.validar_par(a, a)

    vh = describir_escena(crear_rtc(tmp_path / DESPUES.replace("_VV", "_VH"), campo()))
    with pytest.raises(ErrorSAR, match="Polarizaciones distintas"):
        sar.validar_par(a, vh)
    mismo_dia = describir_escena(crear_rtc(tmp_path / ANTES.replace("T231502", "T110000").replace("1A2B", "9999"), campo()))
    with pytest.raises(ErrorSAR, match="misma fecha"):
        sar.validar_par(mismo_dia, a)
    en_db = describir_escena(crear_rtc(tmp_path / DESPUES.replace("gpuned", "gduned"), campo()))
    with pytest.raises(ErrorSAR, match="Escalas distintas"):
        sar.validar_par(a, en_db)
    sigma = describir_escena(crear_rtc(tmp_path / DESPUES.replace("gpuned", "spuned"), campo()))
    with pytest.raises(ErrorSAR, match="Radiometrías distintas"):
        sar.validar_par(a, sigma)

    s1a = describir_escena(crear_rtc(tmp_path / DESPUES.replace("S1C", "S1A"), campo()))
    assert any("Satélites distintos" in x for x in sar.validar_par(a, s1a))
    sin_fecha = describir_escena(crear_rtc(tmp_path / "b.tif", campo()), polarizacion="VV")
    assert any("orden temporal" in x for x in sar.validar_par(a, sin_fecha))


# ---------------------------------------------------------------------------
# Alineación espacial
# ---------------------------------------------------------------------------

def patron(lado=60):
    """Potencia distinta en cada píxel, para detectar cualquier desplazamiento."""
    return (0.01 + np.arange(lado * lado, dtype="float32").reshape(lado, lado) / (lado * lado))


def test_misma_cuadricula_se_lee_sin_modificar_valores(tmp_path):
    a, d = par(tmp_path, antes=patron(), despues=patron() * 2)
    ea, ed = describir_escena(a), describir_escena(d)
    cuad = sar.cuadricula_comun(ea, ed)
    assert (cuad.ancho, cuad.alto) == (60, 60) and cuad.transform == ea.transform
    datos_a, metodo_a = sar.leer_en_cuadricula(ea, cuad)
    datos_d, metodo_d = sar.leer_en_cuadricula(ed, cuad)
    assert "directa" in metodo_a and "directa" in metodo_d
    assert np.array_equal(np.ma.getdata(datos_a), patron()) and np.array_equal(np.ma.getdata(datos_d), patron() * 2)


def test_desplazamiento_de_pixeles_enteros_compara_el_mismo_terreno(tmp_path):
    # La imagen posterior empieza 7 columnas al este y 4 filas al sur, pero
    # ambas "ven" el mismo terreno: valor = función de la coordenada.
    terreno = patron(80)
    a = crear_rtc(tmp_path / ANTES, terreno[:60, :60])
    d = crear_rtc(tmp_path / DESPUES, terreno[4:64, 7:67], x0=X0 + 7 * RES, y0=Y0 - 4 * RES)
    ea, ed = describir_escena(a), describir_escena(d)
    cuad = sar.cuadricula_comun(ea, ed)
    assert (cuad.ancho, cuad.alto) == (53, 56)                      # solo la zona común
    assert cuad.limites == pytest.approx((X0 + 210, Y0 - 1800, X0 + 1800, Y0 - 120))
    datos_a, _ = sar.leer_en_cuadricula(ea, cuad)
    datos_d, metodo = sar.leer_en_cuadricula(ed, cuad)
    assert "directa" in metodo
    assert np.array_equal(np.ma.getdata(datos_a), np.ma.getdata(datos_d))   # píxel a píxel, mismo terreno

    r = analizar_par(a, d, tmp_path / "out", parametros=SIN_FILTRO)
    dif, _ = leer(r.diferencia)
    assert np.abs(dif).max() == 0.0                                 # sin falsos cambios por desalineación
    assert r.estadisticas["clases"][str(SIN_CAMBIO)]["porcentaje_de_validos"] == 100.0


def test_sin_alinear_el_mismo_par_daria_cambios_falsos(tmp_path):
    """Control: restar las matrices tal cual (sin georreferencia) sí inventa cambios."""
    terreno = patron(80)
    ingenuo = 10 * np.log10(terreno[4:64, 7:67]) - 10 * np.log10(terreno[:60, :60])
    assert np.abs(ingenuo).max() > 3.0


def test_medio_pixel_de_desfase_obliga_a_remuestrear(tmp_path):
    a, d = par(tmp_path, x0=X0 + RES / 2, y0=Y0 - RES / 2)
    ea, ed = describir_escena(a), describir_escena(d)
    cuad = sar.cuadricula_comun(ea, ed)
    assert cuad.transform.c == pytest.approx(X0) or (cuad.transform.c - X0) % RES == pytest.approx(0)
    datos_d, metodo = sar.leer_en_cuadricula(ed, cuad)
    assert "remuestreo" in metodo and datos_d.shape == (cuad.alto, cuad.ancho)
    r = analizar_par(a, d, tmp_path / "out", parametros=SIN_FILTRO)
    assert any("remuestreó" in x for x in r.avisos)
    dif, _ = leer(r.diferencia)
    assert np.abs(dif.compressed()).max() < 0.01                    # campo uniforme: sigue sin cambio


def test_otra_resolucion_y_otro_crs_se_llevan_a_la_cuadricula_anterior(tmp_path):
    a = crear_rtc(tmp_path / ANTES, campo(60, 0.1))
    limites = transform_bounds("EPSG:32618", "EPSG:4326", X0 - 600, Y0 - 2400, X0 + 2400, Y0 + 600)
    lado = 200
    geo = np.full((lado, lado), 0.05, dtype="float32")
    with rasterio.open(tmp_path / DESPUES, "w", driver="GTiff", height=lado, width=lado, count=1,
                       dtype="float32", crs="EPSG:4326", nodata=0.0,
                       transform=rasterio.transform.from_bounds(*limites, lado, lado)) as dst:
        dst.write(geo, 1)
    r = analizar_par(a, tmp_path / DESPUES, tmp_path / "out", parametros=SIN_FILTRO)
    dif, src = leer(r.diferencia)
    assert src.crs.to_epsg() == 32618 and src.transform == describir_escena(a).transform
    assert dif.shape == (60, 60) and dif.count() == 3600
    assert float(dif.mean()) == pytest.approx(10 * np.log10(0.05 / 0.1), abs=0.01)   # ≈ −3.01 dB
    assert any("CRS distintos" in x for x in r.avisos) and any("Resoluciones distintas" in x for x in r.avisos)
    assert "remuestreo" in r.procedencia["alineacion"]["despues"]
    assert "directa" in r.procedencia["alineacion"]["antes"]


def test_el_nodata_no_contamina_los_bordes_al_remuestrear(tmp_path):
    despues = campo(60, 0.1)
    despues[:, :20] = 0.0                                           # franja sin dato
    a, d = par(tmp_path, despues=despues, x0=X0 + RES / 2)          # desfase → remuestreo
    r = analizar_par(a, d, tmp_path / "out", parametros=SIN_FILTRO)
    dif, _ = leer(r.diferencia)
    assert dif.count() > 0 and np.abs(dif.compressed()).max() < 0.01   # ningún valor "a medias" con el cero


def test_imagenes_que_no_se_superponen(tmp_path):
    a, d = par(tmp_path, x0=X0 + 100_000)
    with pytest.raises(ErrorSAR, match="no se superponen"):
        analizar_par(a, d, tmp_path / "out")


# ---------------------------------------------------------------------------
# Recorte por AOI
# ---------------------------------------------------------------------------

def aoi_utm(x0, y0, x1, y1):
    return transform_bounds("EPSG:32618", "EPSG:4326", x0, y0, x1, y1)


def test_recorte_por_aoi(tmp_path):
    a, d = par(tmp_path, antes=patron(), despues=patron())
    aoi = aoi_utm(X0 + 300, Y0 - 900, X0 + 900, Y0 - 300)           # 20×20 px centrales
    r = analizar_par(a, d, tmp_path / "out", aoi=aoi, parametros=SIN_FILTRO)
    dif, src = leer(r.diferencia)
    assert 20 <= src.width <= 23 and 20 <= src.height <= 23         # ajustado a píxeles enteros, hacia afuera
    assert (src.transform.c - X0) % RES == pytest.approx(0, abs=1e-6)
    assert (Y0 - src.transform.f) % RES == pytest.approx(0, abs=1e-6)
    oeste, sur, este, norte = src.bounds
    assert oeste <= X0 + 300 and este >= X0 + 900 and sur <= Y0 - 900 and norte >= Y0 - 300
    assert oeste >= X0 + 240 and este <= X0 + 960                   # sin cargar la escena completa
    assert r.procedencia["aoi_lonlat"] == pytest.approx(list(aoi))
    assert r.procedencia["cuadricula"]["ancho"] == src.width


def test_aoi_mayor_que_la_escena_se_limita_a_la_zona_comun(tmp_path):
    a, d = par(tmp_path)
    r = analizar_par(a, d, tmp_path / "out", aoi=aoi_utm(X0 - 5000, Y0 - 9000, X0 + 9000, Y0 + 5000))
    assert (r.procedencia["cuadricula"]["ancho"], r.procedencia["cuadricula"]["alto"]) == (60, 60)


def test_aoi_invalido_o_fuera(tmp_path):
    a, d = par(tmp_path)
    with pytest.raises(ErrorSAR, match="fuera"):
        analizar_par(a, d, tmp_path / "out", aoi=(-70.0, 1.0, -69.9, 1.1))
    with pytest.raises(ErrorSAR, match="AOI inválido"):
        analizar_par(a, d, tmp_path / "out", aoi=(-76.0, 8.0, -77.0, 7.0))
    with pytest.raises(ErrorSAR, match="AOI inválido"):
        analizar_par(a, d, tmp_path / "out", aoi=(-76.0, 7.0, -75.0, 97.0))
    assert not (tmp_path / "out").exists()                          # un error no deja archivos a medias


def test_limite_de_pixeles_exige_aoi(tmp_path):
    a, d = par(tmp_path)
    with pytest.raises(ErrorSAR, match="AOI más pequeño"):
        analizar_par(a, d, tmp_path / "out", max_pixeles=1000)
    aoi = aoi_utm(X0 + 300, Y0 - 900, X0 + 900, Y0 - 300)
    assert analizar_par(a, d, tmp_path / "out", aoi=aoi, max_pixeles=1000).diferencia.exists()


# ---------------------------------------------------------------------------
# Diferencia temporal y máscara
# ---------------------------------------------------------------------------

def escena_con_parches():
    """Posterior: un parche cae 6 dB, otro sube 6 dB, otro cae solo 2 dB."""
    despues = campo(60, 0.1)
    despues[5:15, 5:15] = 0.1 * 10 ** (-0.6)      # −6 dB
    despues[30:40, 30:40] = 0.1 * 10 ** (0.6)     # +6 dB
    despues[45:55, 5:15] = 0.1 * 10 ** (-0.2)     # −2 dB
    return despues


def test_diferencia_temporal_en_db(tmp_path):
    a, d = par(tmp_path, despues=escena_con_parches())
    r = analizar_par(a, d, tmp_path / "out", parametros=SIN_FILTRO)
    dif, src = leer(r.diferencia)
    assert src.nodata == NODATA_DB and dif.dtype == np.float32
    assert float(dif[10, 10]) == pytest.approx(-6.0, abs=1e-4)      # posterior − anterior
    assert float(dif[35, 35]) == pytest.approx(6.0, abs=1e-4)
    assert float(dif[50, 10]) == pytest.approx(-2.0, abs=1e-4)
    assert float(dif[0, 59]) == pytest.approx(0.0, abs=1e-5)


def test_mascara_con_umbrales_configurables(tmp_path):
    a, d = par(tmp_path, despues=escena_con_parches())
    por_defecto = analizar_par(a, d, tmp_path / "o1", parametros=SIN_FILTRO)
    m, src = leer(por_defecto.mascara)
    assert src.nodata == NODATA_MASCARA and m.dtype == np.uint8
    assert m[10, 10] == DISMINUCION and m[35, 35] == AUMENTO
    assert m[50, 10] == SIN_CAMBIO and m[0, 59] == SIN_CAMBIO       # −2 dB no alcanza el umbral de 3
    clases = por_defecto.estadisticas["clases"]
    assert clases[str(DISMINUCION)]["pixeles"] == 100 and clases[str(AUMENTO)]["pixeles"] == 100
    assert clases[str(DISMINUCION)]["area_ha"] == pytest.approx(9.0)   # 100 px × 0.09 ha

    sensible = analizar_par(a, d, tmp_path / "o2", parametros=ParametrosCambio(1.5, 1.5, 1))
    assert leer(sensible.mascara)[0][50, 10] == DISMINUCION         # ahora −2 dB sí cuenta
    estricto = analizar_par(a, d, tmp_path / "o3", parametros=ParametrosCambio(8.0, 8.0, 1))
    assert set(np.unique(leer(estricto.mascara)[0].compressed())) == {SIN_CAMBIO}
    sin_aumentos = analizar_par(a, d, tmp_path / "o4", parametros=ParametrosCambio(3.0, None, 1))
    assert leer(sin_aumentos.mascara)[0][35, 35] == SIN_CAMBIO
    assert sin_aumentos.procedencia["parametros"]["umbral_aumento_db"] is None


def test_umbral_exacto_cuenta_como_cambio():
    dif = np.ma.masked_array(np.array([[-3.0, -2.999, 3.0, 2.999]], dtype="float32"))
    assert sar.mascara_cambios(dif, SIN_FILTRO).tolist() == [[DISMINUCION, SIN_CAMBIO, AUMENTO, SIN_CAMBIO]]


def test_sin_dato_en_cualquiera_de_las_fechas_no_es_cambio(tmp_path):
    antes, despues = campo(), campo()
    antes[0:5, :] = 0.0                    # NoData declarado en la anterior
    despues[20:25, :] = np.nan             # no finito en la posterior
    despues[40:45, :] = -0.3               # potencia negativa: no física
    a, d = par(tmp_path, antes=antes, despues=despues)
    r = analizar_par(a, d, tmp_path / "out", parametros=SIN_FILTRO)
    dif, _ = leer(r.diferencia)
    m, _ = leer(r.mascara)
    for filas in (slice(0, 5), slice(20, 25), slice(40, 45)):
        assert dif.mask[filas].all() and m.mask[filas].all()
    assert not dif.mask[10].any() and set(np.unique(m.compressed())) == {SIN_CAMBIO}
    assert r.estadisticas["pixeles_validos"] == 3600 - 3 * 5 * 60


def test_par_sin_ningun_pixel_comun_con_dato(tmp_path):
    antes, despues = campo(), campo()
    antes[:, :30] = 0.0
    despues[:, 30:] = 0.0
    a, d = par(tmp_path, antes=antes, despues=despues)
    with pytest.raises(ErrorSAR, match="ningún píxel con dato"):
        analizar_par(a, d, tmp_path / "out", parametros=SIN_FILTRO)


def test_clase_baja_en_ambas_fechas_es_opcional(tmp_path):
    antes, despues = campo(), escena_con_parches()
    antes[20:28, 45:55] = 0.005            # −23 dB en las dos fechas (p. ej. agua permanente)
    despues[20:28, 45:55] = 0.005
    a, d = par(tmp_path, antes=antes, despues=despues)
    sin_clase = analizar_par(a, d, tmp_path / "o1", parametros=SIN_FILTRO)
    assert leer(sin_clase.mascara)[0][24, 50] == SIN_CAMBIO
    con_clase = analizar_par(a, d, tmp_path / "o2", parametros=ParametrosCambio(3.0, 3.0, 1, umbral_oscuro_db=-18.0))
    m = leer(con_clase.mascara)[0]
    assert m[24, 50] == BAJA_EN_AMBAS and m[10, 10] == DISMINUCION and m[0, 59] == SIN_CAMBIO
    assert sar.UMBRAL_OSCURO_SUGERIDO["VV"] > sar.UMBRAL_OSCURO_SUGERIDO["VH"]


def test_parametros_invalidos():
    for malos in (dict(umbral_disminucion_db=0), dict(umbral_disminucion_db=-3), dict(umbral_aumento_db=-1),
                  dict(ventana_speckle=4), dict(ventana_speckle=0)):
        with pytest.raises(ErrorSAR):
            ParametrosCambio(**malos)


# ---------------------------------------------------------------------------
# Filtro de speckle
# ---------------------------------------------------------------------------

def test_filtro_de_speckle_promedia_en_potencia():
    datos = np.ma.masked_array(np.full((9, 9), 0.1, dtype="float32"))
    datos[4, 4] = 1.0
    filtrado = sar.filtrar_speckle(datos, 3)
    assert float(filtrado[4, 4]) == pytest.approx((8 * 0.1 + 1.0) / 9, rel=1e-5)   # media aritmética de potencias
    assert float(filtrado[0, 0]) == pytest.approx(0.1, rel=1e-5)                    # bordes: solo píxeles reales
    assert sar.filtrar_speckle(datos, 1) is datos
    with pytest.raises(ErrorSAR):
        sar.filtrar_speckle(datos, 4)


def test_filtro_ignora_y_conserva_los_pixeles_sin_dato():
    valores = np.full((7, 7), 0.2, dtype="float32")
    valores[3, 3] = 999.0
    datos = np.ma.masked_array(valores, mask=np.zeros((7, 7), bool))
    datos[3, 3] = np.ma.masked
    filtrado = sar.filtrar_speckle(datos, 3)
    assert filtrado.mask[3, 3] and filtrado.mask.sum() == 1
    assert float(filtrado[2, 2]) == pytest.approx(0.2, rel=1e-5)    # el 999 enmascarado no se cuela


def test_filtro_reduce_falsos_cambios_por_speckle(tmp_path):
    rng = np.random.default_rng(7)
    ruido = lambda: (0.1 * rng.exponential(1.0, (120, 120))).astype("float32") + 1e-6  # noqa: E731
    a, d = par(tmp_path, antes=ruido(), despues=ruido())            # mismo terreno, solo cambia el speckle
    crudo = analizar_par(a, d, tmp_path / "o1", parametros=ParametrosCambio(3.0, 3.0, 1))
    filtrado = analizar_par(a, d, tmp_path / "o2", parametros=ParametrosCambio(3.0, 3.0, 7))
    falsos = lambda r: sum(r.estadisticas["clases"][str(c)]["porcentaje_de_validos"] for c in (DISMINUCION, AUMENTO))  # noqa: E731
    assert falsos(crudo) > 30 and falsos(filtrado) < 2
    assert filtrado.estadisticas["diferencia_db"]["desviacion"] < crudo.estadisticas["diferencia_db"]["desviacion"] / 4


# ---------------------------------------------------------------------------
# Exportación y procedencia
# ---------------------------------------------------------------------------

def test_salidas_georreferenciadas_y_con_procedencia(tmp_path):
    a, d = par(tmp_path, despues=escena_con_parches())
    r = analizar_par(a, d, tmp_path / "out", parametros=ParametrosCambio(4.0, 5.0, 3), guardar_db=True)
    assert r.diferencia.name == "cambio_VV_20260924_20261006_dif_db.tif"
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(
        f"cambio_VV_20260924_20261006_{s}" for s in (
            "dif_db.tif", "dif_db.json", "mascara.tif", "mascara.json", "analisis.json",
            "antes_db.tif", "antes_db.json", "despues_db.tif", "despues_db.json"))

    for ruta in (r.diferencia, r.mascara, *r.extras.values()):
        with rasterio.open(ruta) as src:
            assert src.crs.to_epsg() == 32618 and src.transform == from_origin(X0, Y0, RES, RES)
            assert (src.width, src.height) == (60, 60) and src.nodata is not None
            tags = src.tags()
            assert tags["VISOR_ANALISIS"] == "1" and tags["POLARIZACION"] == "VV"
            assert tags["ENTRADA_ANTES"] == ANTES and tags["ENTRADA_DESPUES"] == DESPUES
            assert json.loads(tags["PARAMETROS"])["umbral_disminucion_db"] == 4.0
            assert "No confirma inundaciones" in tags["ADVERTENCIA"]
    antes_db, _ = leer(r.extras["antes_db"])
    assert float(antes_db.mean()) == pytest.approx(-10.0, abs=1e-4)

    p = json.loads(r.informe.read_text(encoding="utf-8"))
    assert p == json.loads(json.dumps(r.procedencia))               # el informe es lo que devuelve la función
    assert p["entradas"]["antes"]["fecha"] == "2026-09-24T23:15:02" and p["entradas"]["despues"]["plataforma"] == "S1C"
    assert p["entradas"]["antes"]["polarizacion"] == "VV" and p["entradas"]["antes"]["radiometria"] == "gamma0"
    assert p["entradas"]["antes"]["archivo"] == ANTES               # nombre, no la ruta local completa
    assert str(tmp_path) not in r.informe.read_text(encoding="utf-8")
    assert p["parametros"] == {"umbral_disminucion_db": 4.0, "umbral_aumento_db": 5.0,
                               "ventana_speckle": 3, "umbral_oscuro_db": None}
    assert p["cuadricula"]["crs"] == "EPSG:32618" and len(p["cuadricula"]["limites_lonlat"]) == 4
    assert p["version_motor"] == sar.VERSION_MOTOR and p["generado_utc"].endswith("+00:00")
    assert len(p["limitaciones"]) >= 6 and "No confirma" in p["advertencia"]
    oeste, sur, este, norte = p["cuadricula"]["limites_lonlat"]
    assert -77.0 < oeste < este < -76.5 and 7.5 < sur < norte < 8.0


def test_fuente_solo_menciona_hyp3_si_los_nombres_lo_respaldan(tmp_path):
    a, d = par(tmp_path)
    r = analizar_par(a, d, tmp_path / "o1")
    assert "ASF HyP3 RTC gamma0" in json.loads(r.diferencia.with_suffix(".json").read_text())["fuente"]
    x = crear_rtc(tmp_path / "antes.tif", campo())
    y = crear_rtc(tmp_path / "despues.tif", campo())
    r = analizar_par(x, y, tmp_path / "o2", polarizacion="VV", fecha_antes="2026-09-24", fecha_despues="2026-10-06")
    lateral = json.loads(r.diferencia.with_suffix(".json").read_text())
    assert "HyP3" not in lateral["fuente"] and "antes.tif" in lateral["fuente"]
    assert lateral["fecha"] == "2026-09-24 / 2026-10-06" and lateral["unidades"] == "dB"
    assert r.diferencia.name == "cambio_VV_20260924_20261006_dif_db.tif"
    with pytest.raises(ErrorSAR, match="prefijo"):
        analizar_par(x, y, tmp_path / "o3", polarizacion="VV", prefijo="../fuera")


def test_ninguna_etiqueta_afirma_una_inundacion():
    textos = [e for _, e, _ in sar.CLASES_MASCARA] + [sar.ADVERTENCIA]
    for _, etiqueta, _ in sar.CLASES_MASCARA:
        assert "inunda" not in etiqueta.lower() and "agua" not in etiqueta.lower()
    assert "No confirma inundaciones" in sar.ADVERTENCIA and len(textos) == 5
    temas = " ".join(sar.LIMITACIONES).lower()
    for tema in ("vegetación", "humedad", "relieve", "speckle", "agua permanente"):
        assert tema in temas


def test_el_visor_puede_leer_los_resultados(tmp_path):
    a, d = par(tmp_path, despues=escena_con_parches())
    r = analizar_par(a, d, tmp_path / "out", parametros=SIN_FILTRO)
    capa = leer_geotiff(r.diferencia)
    assert capa.reproyectada and not capa.es_demo and not capa.avisos
    assert capa.metadatos["FUENTE"].startswith("Sentinel-1 (S1C)") and capa.metadatos["UNIDADES"] == "dB"
    assert capa.metadatos["FECHA"] == "2026-09-24 / 2026-10-06"
    assert capa.rango[0] == pytest.approx(-6.0, abs=0.2) and capa.rango[1] == pytest.approx(6.0, abs=0.2)
    mascara = leer_geotiff(r.mascara, categorico=True)
    assert set(np.unique(mascara.datos.compressed())) <= {0.0, 1.0, 2.0}


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------

def test_linea_de_comandos(tmp_path):
    a, d = par(tmp_path, despues=escena_con_parches())
    guion = [sys.executable, str(RAIZ / "scripts" / "analizar_sar.py")]
    r = subprocess.run([*guion, str(a), str(d), "--salida", str(tmp_path / "out"), "--ventana", "1",
                        "--umbral-disminucion", "4", "--umbral-aumento", "0"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "Disminución significativa de retrodispersión: 2.78%" in r.stdout
    assert "No confirma inundaciones" in r.stdout
    informe = json.loads((tmp_path / "out" / "cambio_VV_20260924_20261006_analisis.json").read_text())
    assert informe["parametros"]["umbral_aumento_db"] is None and informe["parametros"]["umbral_disminucion_db"] == 4.0

    r = subprocess.run([*guion, str(d), str(a), "--salida", str(tmp_path / "out2")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "invertido" in r.stderr and "Traceback" not in r.stderr


# ---------------------------------------------------------------------------
# Página de Streamlit
# ---------------------------------------------------------------------------

PAGINA = str(RAIZ / "pages" / "1_Analisis_SAR.py")


def abrir_pagina(monkeypatch, carpeta_sar, carpeta_salida):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("VISOR_SAR_DIR", str(carpeta_sar))
    monkeypatch.setenv("VISOR_ANALISIS_DIR", str(carpeta_salida))
    monkeypatch.chdir(RAIZ)
    return AppTest.from_file(PAGINA, default_timeout=120).run()


def test_pagina_sin_archivos_explica_que_hacer(tmp_path, monkeypatch):
    at = abrir_pagina(monkeypatch, tmp_path / "no_existe", tmp_path / "out")
    assert not at.exception
    assert "data/sar/" in at.info[0].value and len(at.button) == 0
    assert any("No confirma inundaciones" in m.value for m in at.markdown)


def test_pagina_ejecuta_el_analisis_y_muestra_el_resultado(tmp_path, monkeypatch):
    entrada = tmp_path / "sar"
    entrada.mkdir()
    crear_rtc(entrada / ANTES, campo())
    crear_rtc(entrada / DESPUES, escena_con_parches())
    crear_rtc(entrada / DESPUES.replace("_VV", "_VH"), campo())            # otra polarización
    crear_rtc(entrada / ANTES.replace("_VV", "_dem"), campo())             # auxiliar: se omite
    at = abrir_pagina(monkeypatch, entrada, tmp_path / "out")
    assert not at.exception
    antes, despues = at.selectbox(key="sar_antes"), at.selectbox(key="sar_despues")
    assert antes.value.ruta.name == ANTES and despues.value.ruta.name == DESPUES   # par VV, en orden temporal

    at.radio(key="sar_zona").set_value("Toda la zona común (puede ser muy grande)").run()
    at.button[0].click().run()
    assert not at.exception and len(at.error) == 0, [e.value for e in at.error]
    assert at.success[0].value == "Análisis terminado."
    informe = json.loads((tmp_path / "out" / "cambio_VV_20260924_20261006_analisis.json").read_text())
    assert informe["parametros"]["umbral_disminucion_db"] == 3.0 and informe["parametros"]["ventana_speckle"] == 5
    assert informe["aoi_lonlat"] is None
    textos = " ".join(m.value for m in at.markdown)
    assert "2026-09-24 → 2026-10-06" in textos and "Vegetación" in textos and "Speckle" in textos
    assert "Disminución significativa de retrodispersión" in textos        # leyenda de la máscara


def test_pagina_muestra_el_error_del_motor_sin_caerse(tmp_path, monkeypatch):
    entrada = tmp_path / "sar"
    entrada.mkdir()
    crear_rtc(entrada / ANTES, campo())
    crear_rtc(entrada / DESPUES, campo(), x0=X0 + 500_000)                 # no se superponen
    at = abrir_pagina(monkeypatch, entrada, tmp_path / "out")
    at.radio(key="sar_zona").set_value("Toda la zona común (puede ser muy grande)").run()
    at.button[0].click().run()
    assert not at.exception and "no se superponen" in at.error[0].value
    assert not (tmp_path / "out").exists()


def test_la_pagina_principal_sigue_intacta(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(RAIZ)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
    assert not at.exception and len(at.error) == 0
    # Desde la interfaz Mission Control el explorador ya no está en la barra lateral.
    assert len(at.radio(key="fenomeno").options) == 3
    for demo in ("inundacion.tif", "deslizamiento.tif", "deforestacion.tif"):
        assert (RAIZ / "data" / demo).exists()                             # capas demostrativas presentes
