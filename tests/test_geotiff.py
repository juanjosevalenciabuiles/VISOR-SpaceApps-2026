"""Pruebas básicas del cargador GeoTIFF.  Ejecutar con:  pytest"""
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.config import FENOMENOS, Fenomeno  # noqa: E402
from utils.geotiff import (  # noqa: E402
    ErrorCapa, a_web_mercator, cargar_capa, colorizar, colorizar_capa,
    colorizar_categorico, leer_geotiff, rango_visual,
)

NODATA = -9999.0


def crear_tif(ruta, crs="EPSG:4326", limites=(-76.0, 6.0, -75.0, 7.0), lado=50, tags=None, datos=None):
    if datos is None:
        datos = np.linspace(0, 1, lado * lado, dtype="float32").reshape(lado, lado)
        datos[:5, :] = NODATA
    with rasterio.open(
        ruta, "w", driver="GTiff", height=datos.shape[0], width=datos.shape[1], count=1,
        dtype="float32", crs=crs, nodata=NODATA,
        transform=from_bounds(*limites, datos.shape[1], datos.shape[0]),
    ) as dst:
        dst.write(datos, 1)
        if tags:
            dst.update_tags(**tags)
    return ruta


def test_lee_wgs84_y_enmascara_nodata(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "a.tif"))
    assert not capa.reproyectada
    assert capa.limites == pytest.approx((-76.0, 6.0, -75.0, 7.0))
    assert capa.datos.mask[:5, :].all()
    assert not capa.datos.mask[10:, :].any()
    assert capa.rango[0] >= 0  # el NoData no contamina el rango


def test_reproyecta_utm_a_wgs84(tmp_path):
    # UTM 18N: rectángulo cerca de Medellín
    ruta = crear_tif(tmp_path / "utm.tif", crs="EPSG:32618", limites=(420000, 670000, 470000, 720000))
    capa = leer_geotiff(ruta)
    assert capa.reproyectada and capa.crs_original == "EPSG:32618"
    oeste, sur, este, norte = capa.limites
    assert -76.0 < oeste < este < -75.0 and 6.0 < sur < norte < 7.0
    assert not capa.avisos


def test_nan_se_trata_como_sin_dato(tmp_path):
    datos = np.ones((20, 20), dtype="float32")
    datos[0, 0] = np.nan
    capa = leer_geotiff(crear_tif(tmp_path / "nan.tif", datos=datos))
    assert capa.datos.mask[0, 0]


def test_reduce_rasters_grandes(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "g.tif", lado=400), max_lado=100)
    assert max(capa.datos.shape) == 100
    assert capa.forma_original == (400, 400)


def test_avisa_si_queda_fuera_de_antioquia(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "f.tif", limites=(10.0, 40.0, 11.0, 41.0)))
    assert any("fuera" in a for a in capa.avisos)


def test_etiqueta_demo(tmp_path):
    assert leer_geotiff(crear_tif(tmp_path / "d.tif", tags={"VISOR_DEMO": "1"})).es_demo
    assert not leer_geotiff(crear_tif(tmp_path / "r.tif")).es_demo


def test_json_lateral_aporta_metadatos(tmp_path):
    crear_tif(tmp_path / "m.tif")
    (tmp_path / "m.json").write_text('{"fecha": "2026-05-01", "fuente": "Sentinel-1"}', encoding="utf-8")
    capa = leer_geotiff(tmp_path / "m.tif")
    assert capa.metadatos["FECHA"] == "2026-05-01"


def test_errores_legibles(tmp_path):
    with pytest.raises(ErrorCapa, match="No se encontró"):
        leer_geotiff(tmp_path / "no_existe.tif")

    (tmp_path / "roto.tif").write_bytes(b"esto no es un tif")
    with pytest.raises(ErrorCapa, match="no es un GeoTIFF"):
        leer_geotiff(tmp_path / "roto.tif")

    with rasterio.open(tmp_path / "sin_crs.tif", "w", driver="GTiff", height=5, width=5, count=1, dtype="float32") as d:
        d.write(np.ones((5, 5), dtype="float32"), 1)
    with pytest.raises(ErrorCapa, match="CRS"):
        leer_geotiff(tmp_path / "sin_crs.tif")

    todo_nodata = np.full((10, 10), NODATA, dtype="float32")
    with pytest.raises(ErrorCapa, match="píxeles válidos"):
        leer_geotiff(crear_tif(tmp_path / "vacio.tif", datos=todo_nodata))


def test_colorizar_transparencia(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "c.tif"))
    rgba = colorizar(capa.datos, ("#000000", "#00F0FF"))
    assert rgba.shape == capa.datos.shape + (4,) and rgba.dtype == np.uint8
    assert (rgba[:5, :, 3] == 0).all()   # NoData transparente
    assert rgba[-1, -1, 3] == 255        # máximo indicio, opaco
    assert tuple(rgba[-1, -1, :3]) == (0, 240, 255)


def test_colorizar_invertido(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "i.tif"))
    rgba = colorizar(capa.datos, ("#000000", "#FFFFFF"), invertir=True)
    assert rgba[5, 0, 3] > rgba[-1, -1, 3]


def test_configuracion_de_fenomenos():
    assert set(FENOMENOS) == {"inundacion", "deslizamiento", "deforestacion"}
    for f in FENOMENOS.values():
        assert f.archivo.endswith(".tif") and len(f.colores) >= 2 and f.advertencias


def test_a_web_mercator_conserva_colores_y_forma():
    rgba = np.zeros((40, 10, 4), dtype="uint8")
    rgba[:20] = (255, 45, 85, 255)  # mitad norte de color
    salida = a_web_mercator(rgba, sur=5.0, norte=9.0)
    assert salida.shape == rgba.shape and salida.dtype == np.uint8
    assert tuple(salida[0, 0]) == (255, 45, 85, 255) and salida[-1, 0, 3] == 0
    assert set(map(tuple, salida.reshape(-1, 4))) == {(255, 45, 85, 255), (0, 0, 0, 0)}
    assert abs(int((salida[:, 0, 3] > 0).sum()) - 20) <= 1  # casi sin distorsión a esta latitud


# ---------------------------------------------------------------------------
# v1.1
# ---------------------------------------------------------------------------

def mascara_clases(lado=400):
    """Máscara 0/1/2 en bandas verticales, sin NoData."""
    datos = np.zeros((lado, lado), dtype="float32")
    datos[:, lado // 3:] = 1
    datos[:, 2 * lado // 3:] = 2
    return datos


def test_cache_se_invalida_al_cambiar_solo_el_json(tmp_path):
    ruta = crear_tif(tmp_path / "c.tif")
    marca_tif = ruta.stat().st_mtime_ns
    assert "FECHA" not in cargar_capa(ruta).metadatos

    lateral = tmp_path / "c.json"
    lateral.write_text('{"fecha": "2026-05-01"}', encoding="utf-8")
    assert cargar_capa(ruta).metadatos["FECHA"] == "2026-05-01"

    lateral.write_text('{"fecha": "2026-06-15", "fuente": "Sentinel-1"}', encoding="utf-8")
    capa = cargar_capa(ruta)
    assert capa.metadatos["FECHA"] == "2026-06-15" and capa.metadatos["FUENTE"] == "Sentinel-1"

    lateral.unlink()
    assert "FECHA" not in cargar_capa(ruta).metadatos
    assert ruta.stat().st_mtime_ns == marca_tif  # el GeoTIFF nunca se tocó


def test_cache_se_invalida_al_cambiar_el_geotiff(tmp_path):
    ruta = crear_tif(tmp_path / "t.tif", datos=np.full((10, 10), 1.0, dtype="float32"))
    assert cargar_capa(ruta).rango == (1.0, 1.0)
    crear_tif(ruta, datos=np.full((12, 12), 5.0, dtype="float32"))
    assert cargar_capa(ruta).rango == (5.0, 5.0)


def test_mascara_categorica_usa_nearest(tmp_path):
    ruta = crear_tif(tmp_path / "m.tif", datos=mascara_clases())
    categorica = leer_geotiff(ruta, max_lado=90, categorico=True)
    assert categorica.categorico
    assert set(np.unique(categorica.datos.compressed())) == {0.0, 1.0, 2.0}
    # El mismo archivo leído como continuo sí mezcla valores en los bordes.
    continua = leer_geotiff(ruta, max_lado=90)
    assert not set(np.unique(continua.datos.compressed())) <= {0.0, 1.0, 2.0}


def test_mascara_categorica_reproyectada_no_inventa_clases(tmp_path):
    ruta = crear_tif(
        tmp_path / "mu.tif", crs="EPSG:32618", limites=(420000, 670000, 470000, 720000),
        datos=mascara_clases(120),
    )
    capa = leer_geotiff(ruta, categorico=True)
    assert capa.reproyectada
    assert set(np.unique(capa.datos.compressed())) <= {0.0, 1.0, 2.0}


def test_colorizar_categorico():
    datos = np.ma.masked_values(np.array([[0, 1, 2, 7, -9999]], dtype="float32"), -9999)
    clases = ((0, "Sin cambio", None), (1, "Clase A", "#00F0FF"), (2, "Clase B", "#FF2D55"))
    rgba = colorizar_categorico(datos, clases)
    assert rgba[0, 0, 3] == 0                              # clase transparente por configuración
    assert tuple(rgba[0, 1]) == (0, 240, 255, 255)
    assert tuple(rgba[0, 2]) == (255, 45, 85, 255)
    assert tuple(rgba[0, 3]) == (142, 142, 147, 255)       # clase no configurada: gris, no oculta
    assert rgba[0, 4, 3] == 0                              # NoData


def test_valores_constantes(tmp_path):
    datos = np.full((20, 20), 0.7, dtype="float32")
    datos[0, :] = NODATA
    capa = leer_geotiff(crear_tif(tmp_path / "k.tif", datos=datos))
    assert capa.rango == pytest.approx((0.7, 0.7))
    assert any("mismo valor" in a for a in capa.avisos)
    for modo in ("gradual", "nodata"):
        rgba = colorizar(capa.datos, ("#000000", "#FFFFFF"), transparencia=modo)
        validos = rgba[1:]
        assert (validos[..., 3] > 0).all()                  # visibles
        assert len(np.unique(validos.reshape(-1, 4), axis=0)) == 1  # un solo color, sin NaN
        assert (rgba[0, :, 3] == 0).all()
    # Con rango fijo, un valor constante sí cae en su sitio de la escala.
    rgba = colorizar(capa.datos, ("#000000", "#FFFFFF"), vmin=0.0, vmax=0.7, transparencia="nodata")
    assert tuple(rgba[5, 5]) == (255, 255, 255, 255)


def test_valores_validos_bajos_no_se_ocultan(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "b.tif"))
    valido = ~np.ma.getmaskarray(capa.datos)

    gradual = colorizar(capa.datos, ("#000000", "#00F0FF"))
    assert gradual[valido][:, 3].min() == round(0.25 * 255)  # el mínimo válido sigue visible
    assert (gradual[~valido][:, 3] == 0).all()               # solo NoData es transparente

    opaco = colorizar(capa.datos, ("#000000", "#00F0FF"), transparencia="nodata")
    assert (opaco[valido][:, 3] == 255).all() and (opaco[~valido][:, 3] == 0).all()

    tenue = colorizar(capa.datos, ("#000000", "#00F0FF"), alfa_min=0.6)
    assert tenue[valido][:, 3].min() == round(0.6 * 255)

    with pytest.raises(ValueError):
        colorizar(capa.datos, ("#000000", "#00F0FF"), transparencia="umbral")


def test_cero_es_un_dato_valido_no_nodata(tmp_path):
    datos = np.zeros((10, 10), dtype="float32")
    datos[5:, :] = 1.0
    capa = leer_geotiff(crear_tif(tmp_path / "z.tif", datos=datos))
    assert capa.datos.count() == 100
    assert (colorizar(capa.datos, ("#000000", "#FFFFFF"))[..., 3] > 0).all()


def test_normalizacion_configurable():
    datos = np.ma.masked_invalid(np.array([[-20.0, -10.0, 0.0, 10.0, np.nan]], dtype="float32"))
    rampa = ("#000000", "#FFFFFF")

    assert rango_visual(datos, vmin=-10, vmax=0) == (-10.0, 0.0)
    assert rango_visual(datos, percentiles=(0, 100)) == (-20.0, 10.0)
    assert rango_visual(datos, vmin=-5, percentiles=(0, 100)) == (-5.0, 10.0)

    fijo = colorizar(datos, rampa, vmin=-10, vmax=0, transparencia="nodata")
    assert [int(v) for v in fijo[0, :4, 0]] == [0, 0, 255, 255]      # satura fuera del rango
    amplio = colorizar(datos, rampa, vmin=-20, vmax=10, transparencia="nodata")
    assert int(amplio[0, 1, 0]) == 85                                 # -10 queda a 1/3

    # Escala invertida: el extremo intenso de la rampa va en los valores BAJOS.
    invertido = colorizar(datos, rampa, vmin=-20, vmax=10, invertir=True)
    assert tuple(invertido[0, 0]) == (255, 255, 255, 255)
    assert invertido[0, 3, 3] == round(0.25 * 255)
    assert invertido[0, 4, 3] == 0


def test_perfil_del_fenomeno_controla_la_visualizacion(tmp_path):
    capa = leer_geotiff(crear_tif(tmp_path / "p.tif"))
    base = dict(clave="x", nombre="X", icono="", archivo="x.tif", descripcion="", producto="",
                advertencias=("a",), colores=("#000000", "#FFFFFF"))
    normal = colorizar_capa(capa, Fenomeno(**base))
    invertido = colorizar_capa(capa, Fenomeno(**base, invertir=True))
    opaco = colorizar_capa(capa, Fenomeno(**base, transparencia="nodata"))
    assert normal[-1, -1, 0] == 255 and invertido[-1, -1, 0] == 0
    assert (opaco[10:, :, 3] == 255).all()

    clases = ((0, "Sin cambio", None), (1, "Cambio", "#39FF14"))
    categorico = Fenomeno(**base, tipo_valores="categorico", clases=clases)
    binaria = np.ma.masked_array(np.array([[0, 1]], dtype="float32"))
    capa.datos = binaria
    assert tuple(colorizar_capa(capa, categorico)[0, 1]) == (57, 255, 20, 255)

    with pytest.raises(ValueError):
        Fenomeno(**base, tipo_valores="categorico")          # faltan las clases
    with pytest.raises(ValueError):
        Fenomeno(**base, vmin=1.0, vmax=1.0)
    with pytest.raises(ValueError):
        Fenomeno(**base, transparencia="magia")


@pytest.mark.parametrize("contenido", ['{"fecha": ', "[1, 2, 3]", '"solo texto"', ""])
def test_json_de_metadatos_invalido_no_tumba_la_capa(tmp_path, contenido):
    crear_tif(tmp_path / "j.tif")
    (tmp_path / "j.json").write_text(contenido, encoding="utf-8")
    capa = leer_geotiff(tmp_path / "j.tif")
    assert "FECHA" not in capa.metadatos
    assert any("metadatos" in a for a in capa.avisos)


def test_json_de_metadatos_no_puede_ocultar_que_es_demo(tmp_path):
    crear_tif(tmp_path / "d.tif", tags={"VISOR_DEMO": "1"})
    (tmp_path / "d.json").write_text(
        '{"visor_demo": "0", "fuente": "Sentinel-1", "anidado": {"x": 1}}', encoding="utf-8")
    capa = leer_geotiff(tmp_path / "d.tif")
    assert capa.es_demo
    assert capa.metadatos["FUENTE"] == "Sentinel-1" and "ANIDADO" not in capa.metadatos
    assert not capa.avisos


def test_json_binario_ilegible(tmp_path):
    crear_tif(tmp_path / "x.tif")
    (tmp_path / "x.json").write_bytes(b"\xff\xfe\x00\x01")
    assert any("metadatos" in a for a in leer_geotiff(tmp_path / "x.tif").avisos)


def test_region_de_interes(tmp_path):
    # Totalmente fuera: se carga igual, con aviso.
    fuera = leer_geotiff(crear_tif(tmp_path / "f.tif", limites=(-60.0, -20.0, -59.0, -19.0)))
    assert fuera.datos.count() > 0 and any("fuera" in a for a in fuera.avisos)
    # Parcialmente dentro (cruza el borde occidental): sin aviso.
    borde = leer_geotiff(crear_tif(tmp_path / "b.tif", limites=(-78.0, 6.0, -77.0, 7.0)))
    assert not any("fuera" in a for a in borde.avisos)
    # Fuera y en UTM: la validación se hace después de reproyectar.
    utm = leer_geotiff(crear_tif(tmp_path / "u.tif", crs="EPSG:32618", limites=(420000, 1500000, 470000, 1550000)))
    assert any("fuera" in a for a in utm.avisos)


def test_extension_geografica_invalida(tmp_path):
    with pytest.raises(ErrorCapa, match="extensión"):
        leer_geotiff(crear_tif(tmp_path / "e.tif", limites=(-76.0, 80.0, -75.0, 95.0)))


def test_perfiles_actuales_y_datos_sinteticos():
    for f in FENOMENOS.values():
        assert f.tipo_valores == "continuo" and f.unidades and f.leyenda_min and f.leyenda_max
        assert not hasattr(f, "fuente")  # la fuente solo sale de metadatos del archivo
        if f.ruta.exists():  # los sintéticos incluidos siguen siendo compatibles
            capa = leer_geotiff(f.ruta, categorico=f.categorico)
            assert capa.es_demo and "FUENTE" not in capa.metadatos
            rgba = colorizar_capa(capa, f)
            assert rgba.shape == capa.datos.shape + (4,)
            assert (rgba[~np.ma.getmaskarray(capa.datos)][:, 3] > 0).all()
