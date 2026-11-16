"""NISAR selection by common footprint: offline, no NASA token, no downloads."""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import folium
import pytest
from shapely.geometry import box

from components import cobertura_nisar as visual
from components import v9_experiencia as ui
from utils import nisar_catalogo as cat, nisar_coberturas as geo

AOI = (-76.80, 7.55, -76.55, 7.80)
INI, FIN = date(2026, 10, 20), date(2026, 11, 10)


def _par(a: str, b: str, region, *, dias=12, bytes_por_escena=150_000_000):
    d1, d2 = datetime(2026, 10, 28, tzinfo=timezone.utc), datetime(2026, 11, 9, tzinfo=timezone.utc)

    def escena(nombre, fecha, huella):
        return NS(
            granule=nombre, huella=huella, tamano_bytes=bytes_por_escena,
            url_h5=f"https://nisar.asf.earthdatacloud.nasa.gov/{nombre}.h5",
            madurez="VALIDATED",
            nombre=NS(inicio=fecha, track=148, frame=5, pol_a=("HH", "HV")),
        )

    pre = escena(a, d1, region)
    post = escena(b, d2, region)
    return cat.ParNISAR(pre, post, dias, 0.5, ("HH", "HV"), [], [])


def _resultado(pares):
    return cat.ResultadoNISAR(
        region=NS(limites=AOI), inicio=INI, fin=FIN, madurez="VALIDATED",
        url="https://cmr.earthdata.nasa.gov/search/granules.umm_json",
        total_catalogo=2 * len(pares), candidatos=[x for p in pares for x in (p.antes, p.despues)],
        descartes=[], pares=pares, bloqueos=[], avisos=[],
    )


def test_area_geodesica_elige_interseccion_de_ambas_fechas_no_la_mayor_escena():
    a = _par("A1", "A2", box(-76.8, 7.55, -76.56, 7.8))
    # Ambas huellas no son iguales: T2 recorta casi todo T1.
    a.despues.huella = box(-76.8, 7.55, -76.74, 7.8)
    b = _par("B1", "B2", box(-76.76, 7.55, -76.56, 7.8))
    r = _resultado([a, b])
    candidatos = geo.opciones(r, r.pares, punto_prioritario=None)
    assert candidatos[0]["id"] == geo.identificador(b)
    assert candidatos[0]["cobertura"] > candidatos[1]["cobertura"]
    assert candidatos[0]["cobertura"] == pytest.approx(0.8, abs=0.015)
    assert candidatos[1]["cobertura"] == pytest.approx(0.24, abs=0.015)
    assert candidatos[0]["plan"].granules == ("B1", "B2")
    assert candidatos[1]["plan"] is None, "par menor al umbral de 40% no es analizable"


def test_punto_prioritario_evitan_par_que_no_cubre_pueblo():
    oeste = _par("O1", "O2", box(-76.8, 7.55, -76.68, 7.8))
    este = _par("E1", "E2", box(-76.70, 7.55, -76.55, 7.8))
    r = _resultado([oeste, este])
    candidatos = geo.opciones(r, r.pares, punto_prioritario=(-76.62, 7.67))
    assert candidatos[0]["id"] == geo.identificador(este)
    assert candidatos[0]["cubre_punto"] is True
    assert candidatos[1]["cubre_punto"] is False
    assert candidatos[0]["plan"] is not None


def test_busqueda_solo_cmr_sin_descarga_ni_token(monkeypatch):
    r = _resultado([_par("A1", "A2", box(*AOI))])
    estado = {}
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    llamadas = []
    monkeypatch.setattr(ui.cat, "buscar", lambda *a, **k: llamadas.append((a, k)) or r)
    import components.nisar_auto_ui as auto_ui
    monkeypatch.setattr(auto_ui, "_ejecutar_en_cola",
                        lambda *_args: pytest.fail("Buscar metadatos NO descarga"))
    salida = ui._consultar_coberturas(AOI, INI, FIN)
    assert len(llamadas) == 1
    assert salida["seleccionado"] == geo.identificador(r.pares[0])
    assert salida["firma"] == ui._firma(AOI, INI, FIN)
    assert salida["opciones"][0]["plan"].tipo == "PAR"
    assert "v9_preparacion" not in estado
    assert "nisar_auto_job" not in estado


def test_click_mapa_con_solapamiento_no_selecciona_arbitrariamente(monkeypatch):
    a = _par("A1", "A2", box(-76.80, 7.55, -76.65, 7.8))
    b = _par("B1", "B2", box(-76.73, 7.55, -76.55, 7.8))
    candidatos = geo.opciones(_resultado([a, b]), [a, b])
    estado = {
        "zona": {"limites": list(AOI)}, "v9_inicio_periodo": INI,
        "v9_fin_periodo": FIN,
        "v9_coberturas": {
            "firma": ui._firma(AOI, INI, FIN), "opciones": candidatos,
            "seleccionado": candidatos[0]["id"],
        },
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    assert ui.seleccionar_desde_mapa({"lat": 7.67, "lng": -76.69}, "mapa_prueba")
    assert set(estado["v9_pares_solapados"]) == {x["id"] for x in candidatos}
    assert estado["v9_coberturas"]["seleccionado"] == candidatos[0]["id"]
    ui._elegir_par(candidatos[1]["id"])
    assert estado["v9_coberturas"]["seleccionado"] == candidatos[1]["id"]
    assert not estado["v9_pares_solapados"]
    assert not ui.seleccionar_desde_mapa({"lat": 7.67, "lng": -76.69}, "mapa_prueba")


def test_cambio_aoi_invalida_seleccion_y_protege_archivos(monkeypatch):
    par = _par("A1", "A2", box(*AOI))
    opciones = geo.opciones(_resultado([par]), [par])
    estado = {
        "zona": {"limites": list(AOI)}, "v9_inicio_periodo": INI, "v9_fin_periodo": FIN,
        "v9_coberturas": {
            "firma": ui._firma(AOI, INI, FIN), "opciones": opciones,
            "seleccionado": opciones[0]["id"],
        },
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    assert ui._coberturas_actuales() is not None
    estado["zona"] = {"limites": [-76.70, 7.60, -76.61, 7.69]}
    assert ui._coberturas_actuales() is None
    assert ui.grupos_mapa() == []
    assert not ui.seleccionar_desde_mapa({"lat": 7.67, "lng": -76.69}, "mapa_viejo")


def test_coberturas_cmr_t1_t2_y_area_sin_cobertura_no_son_rasters(monkeypatch):
    par = _par("T1", "T2", box(-76.80, 7.55, -76.67, 7.8))
    r = _resultado([par])
    opciones = geo.opciones(r, r.pares)
    firma = ui._firma(AOI, INI, FIN)
    estado = {"firma": firma, "opciones": opciones, "seleccionado": opciones[0]["id"]}
    grupos = visual.grupos(estado, firma)
    assert len(grupos) == 1
    m = folium.Map(location=(7.67, -76.70))
    grupos[0].add_to(m)
    html = m.get_root().render()
    assert "T1" in html and "T2" in html and "NASA CMR" in html
    assert "CMR" in html
    assert not any(isinstance(c, folium.raster_layers.ImageOverlay)
                   for c in grupos[0]._children.values())


def test_no_se_descarga_par_antiguo_o_diferente(monkeypatch):
    par = _par("T1", "T2", box(*AOI))
    resultado = _resultado([par])
    opciones = geo.opciones(resultado, [par])
    item = opciones[0]
    estado = {"firma": ui._firma(AOI, INI, FIN), "resultado": resultado,
              "opciones": opciones, "seleccionado": item["id"]}
    import components.nisar_auto_ui as auto_ui
    llamadas = []
    monkeypatch.setattr(auto_ui, "_ejecutar_en_cola",
                        lambda *_args: llamadas.append(_args) or {"job_id": "1234567890abcdef"})
    monkeypatch.setenv("EARTHDATA_TOKEN", "TOKEN_FICTICIO_SOLO_EN_TEST")
    monkeypatch.setattr(ui.cat, "evaluar_par", lambda *_args: par)
    assert ui._solicitar_elegido(AOI, INI, FIN, estado, item) == "1234567890abcdef"
    assert llamadas[0][1].granules == ("T1", "T2")
    assert llamadas[0][1].resumen()["id_par_seleccionado"] == item["id"]
    assert llamadas[0][1].resumen()["criterio_seleccion"] == "PAR_CONFIRMADO_USUARIO_POR_COBERTURA_CMR"
    with pytest.raises(ValueError, match="otro período o zona"):
        ui._solicitar_elegido((-76.7, 7.6, -76.6, 7.7), INI, FIN, estado, item)
    assert len(llamadas) == 1


def test_sin_qa_dos_fechas_incompatibles_no_se_saltan_filtro(monkeypatch):
    par = _par("T1", "T2", box(*AOI))
    resultado = _resultado([par])
    item = geo.opciones(resultado, [par])[0]
    estado = {"firma": ui._firma(AOI, INI, FIN), "resultado": resultado,
              "opciones": [item], "seleccionado": item["id"]}
    monkeypatch.setenv("EARTHDATA_TOKEN", "TOKEN_FICTICIO_SOLO_EN_TEST")
    monkeypatch.setattr(ui.cat, "evaluar_par",
                        lambda *_args: ["polarizaciones incompatibles"])
    with pytest.raises(ValueError, match="compatibilidad"):
        ui._solicitar_elegido(AOI, INI, FIN, estado, item)


def test_cobertura_verde_se_oculta_solo_tras_publicacion_sar_apta(monkeypatch):
    """La huella de selección CMR no debe tapar la imagen SAR verificada."""
    par = _par("T1", "T2", box(*AOI))
    resultado = _resultado([par])
    opciones = geo.opciones(resultado, [par])
    firma = ui._firma(AOI, INI, FIN)
    estado = {
        "zona": {"limites": list(AOI)},
        "v9_inicio_periodo": INI, "v9_fin_periodo": FIN,
        "v9_coberturas": {"firma": firma, "opciones": opciones,
                         "seleccionado": opciones[0]["id"]},
        "v9_firma": firma,
        "v9_mapa_job": "mapa_qa_001",
        "resultado_activo": None,
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    assert len(ui.grupos_mapa()) == 1
    assert ui.modo_seleccion_mapa() is True

    # Preparación/proceso en curso: todavía hay huellas para comparar.
    estado["resultado_activo"] = {"id": "delta_nisar", "origen": "analisis"}
    assert len(ui.grupos_mapa()) == 1, "sin verificación no ocultar las coberturas"

    # Publicación validada: se retiran T1, T2, verde y zona gris del mapa.
    estado["v9_publicado"] = "mapa_qa_001"
    assert ui._resultado_sar_verificado(estado["v9_coberturas"]) is True
    assert ui.grupos_mapa() == []
    assert ui.modo_seleccion_mapa() is False
    assert len(estado["v9_coberturas"]["opciones"]) == 1, "conservar metadatos, no borrar datos"

    # Si se retira el resultado o se inicia otro trabajo, se puede comparar de nuevo.
    estado["resultado_activo"] = None
    assert len(ui.grupos_mapa()) == 1
    estado["resultado_activo"] = {"id": "delta_nisar", "origen": "analisis"}
    estado["v9_mapa_job"] = "nuevo_mapa_en_curso"
    assert len(ui.grupos_mapa()) == 1

    # Los resultados ajenos o de otra AOI tampoco autorizan ocultar huellas.
    estado["v9_mapa_job"] = "mapa_qa_001"
    estado["resultado_activo"]["origen"] = "historico"
    assert len(ui.grupos_mapa()) == 1
    estado["resultado_activo"]["origen"] = "analisis"
    estado["v9_firma"] = (AOI, "2026-10-01", "2026-11-01")
    assert len(ui.grupos_mapa()) == 1


def test_accion_sar_fija_no_analiza_sin_par_o_sin_cobertura_aceptada(monkeypatch):
    """La acción es única y siempre visible, pero deshabilitada hasta autorizarla."""
    from contextlib import nullcontext

    estado = {"zona": {"limites": list(AOI)},
              "v9_inicio_periodo": INI, "v9_fin_periodo": FIN}
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.st, "container", lambda **kwargs: nullcontext())
    monkeypatch.setattr(ui.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui, "_preparacion_existente", lambda *args: None)
    llamadas = []

    def boton(label, **kwargs):
        llamadas.append({"label": label, **kwargs})
        return False

    monkeypatch.setattr(ui.st, "button", boton)
    ui.accion_principal()
    assert len(llamadas) == 1
    assert llamadas[-1]["key"] == "v9_analizar"
    assert llamadas[-1]["disabled"] is True

    parcial = _par("P1", "P2", box(-76.80, 7.55, -76.65, 7.8))
    resultado = _resultado([parcial])
    opciones = geo.opciones(resultado, [parcial])
    assert opciones[0]["plan"] is not None and opciones[0]["cobertura"] < 0.90
    firma = ui._firma(AOI, INI, FIN)
    estado["v9_coberturas"] = {"firma": firma, "opciones": opciones,
                              "seleccionado": opciones[0]["id"]}
    ui.accion_principal()
    assert llamadas[-1]["disabled"] is True, "falta aceptar cobertura parcial"
    estado[ui._clave_aceptacion(firma, opciones[0]["id"])] = True
    monkeypatch.setenv("EARTHDATA_TOKEN", "TOKEN_FICTICIO_SOLO_EN_PRUEBAS")
    ui.accion_principal()
    assert llamadas[-1]["disabled"] is False
    assert llamadas[-1]["type"] == "primary"
    estado["v9_preparacion"] = "trabajo_en_curso"
    ui.accion_principal()
    assert llamadas[-1]["disabled"] is True
    assert len(llamadas) == 4, "el botón se emite una sola vez por render"


def test_accion_sar_fija_aprueba_reutilizacion_cog_sin_token(monkeypatch):
    """Reutilizar solo el par preparado autorizado; no obliga a descargar otro."""
    from contextlib import nullcontext

    par = _par("T1", "T2", box(*AOI))
    resultado = _resultado([par])
    opciones = geo.opciones(resultado, [par])
    firma = ui._firma(AOI, INI, FIN)
    estado = {"zona": {"limites": list(AOI)},
              "v9_inicio_periodo": INI, "v9_fin_periodo": FIN,
              "v9_coberturas": {"firma": firma, "opciones": opciones,
                               "seleccionado": opciones[0]["id"]}}
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.st, "container", lambda **kwargs: nullcontext())
    monkeypatch.setattr(ui.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    botones = []
    monkeypatch.setattr(ui.st, "button", lambda *args, **kwargs: botones.append(kwargs) or False)
    monkeypatch.setattr(ui, "_preparacion_existente", lambda *args: None)
    ui.accion_principal()
    assert botones[-1]["disabled"] is True
    monkeypatch.setattr(ui, "_preparacion_existente", lambda *args: {"job_id": "job_qa"})
    ui.accion_principal()
    assert botones[-1]["disabled"] is False


def test_estilo_y_ubicacion_del_boton_sar_sin_duplicacion():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    css = (raiz / "assets/mission_control.css").read_text(encoding="utf-8")
    interfaz = (raiz / "components/interfaz.py").read_text(encoding="utf-8")
    codigo = (raiz / "components/v9_experiencia.py").read_text(encoding="utf-8")
    assert ".st-key-panel_sar .st-key-sar_accion_fija" in css
    assert "position: sticky !important" not in css
    assert "bottom: -16px" not in css
    assert "#ffbb49" in css
    assert 'v9_experiencia.accion_principal()' in interfaz
    assert interfaz.index("v9_experiencia.accion_principal()") < interfaz.index("v9_experiencia.render()")
    assert 'herramientas.paso_area(centrar_en)' in interfaz
    assert "nisar_auto_ui.render" not in interfaz
    assert codigo.count('key="v9_analizar"') == 1


def test_error_nisar_y_catalogo_aparecen_antes_de_analizar(monkeypatch):
    """Las alertas principales deben ser visibles sin desplazar el panel SAR."""
    from contextlib import nullcontext

    eventos = []
    estado = {
        "zona": {"limites": list(AOI)},
        "v9_inicio_periodo": INI, "v9_fin_periodo": FIN,
        "v9_error": "Error al autorizar el par",
        "v9_coberturas_error": "NASA CMR no disponible",
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.st, "container", lambda **kw: nullcontext())
    monkeypatch.setattr(ui.st, "error", lambda texto: eventos.append(("error", texto)))
    monkeypatch.setattr(ui.st, "caption", lambda texto: eventos.append(("caption", texto)))
    monkeypatch.setattr(ui.st, "button",
                        lambda texto, **kw: eventos.append(("button", kw["key"])) or False)
    ui.accion_principal()
    assert [tipo for tipo, _ in eventos] == ["error", "error", "caption", "button"]
    assert "autorizar" in eventos[0][1]
    assert "NASA CMR" in eventos[1][1]
    assert eventos[-1] == ("button", "v9_analizar")
    assert ui._error_cog_grande(
        "ErrorAutoNISAR: El COG supera el límite de bytes antes de transferir."
    )
    assert ui._error_cog_grande(
        "Capa HHHH: COG_DEMASIADO_GRANDE: NASA Harmony devolvió 300 MiB"
    )
    assert not ui._error_cog_grande("No hay cobertura de catálogo")


def test_reduccion_manual_cog_preserva_geometria_y_resolucion():
    """La sugerencia disminuye el área, nunca la aumenta ni cambia de ciudad."""
    from utils import sesion

    actual = sesion.validar_zona(AOI)
    sugerida = ui._reducir_zona_cog(actual, (-76.68, 7.68))
    assert sesion.validar_zona(sugerida) == sugerida
    assert actual[0] <= sugerida[0] < sugerida[2] <= actual[2]
    assert actual[1] <= sugerida[1] < sugerida[3] <= actual[3]
    assert sesion.pixeles_estimados(sugerida) < sesion.pixeles_estimados(actual) * 0.35
    ancho_km, alto_km = sesion.dimensiones_km(sugerida)
    assert 0.98 < ancho_km / alto_km < 1.02
    assert ui._reducir_zona_cog(actual, (-76.68, 7.68)) == sugerida



def test_sugiere_solo_fechas_de_pares_viables_cmr_sin_descargar(monkeypatch):
    """Sin pares en período, la fecha sugerida existe y supera el límite CMR."""
    import components.nisar_auto_ui as auto_ui

    malo = _par("B1", "B2", box(-76.80, 7.55, -76.75, 7.8))
    malo.antes.nombre.inicio = datetime(2026, 10, 28, tzinfo=timezone.utc)
    malo.despues.nombre.inicio = datetime(2026, 11, 9, tzinfo=timezone.utc)
    bueno = _par("G1", "G2", box(*AOI))
    bueno.antes.nombre.inicio = datetime(2026, 11, 11, tzinfo=timezone.utc)
    bueno.despues.nombre.inicio = datetime(2026, 11, 14, tzinfo=timezone.utc)
    r = _resultado([malo, bueno])
    elegido_inicio, elegido_fin = date(2026, 10, 20), date(2026, 10, 25)
    estado = {"v9_inicio_periodo": elegido_inicio, "v9_fin_periodo": elegido_fin}
    monkeypatch.setattr(ui.st, "session_state", estado)
    llamadas = []
    monkeypatch.setattr(ui.cat, "buscar",
                        lambda *a, **kwargs: llamadas.append(kwargs) or r)
    monkeypatch.setattr(auto_ui, "_ejecutar_en_cola",
                        lambda *_a: pytest.fail("CMR nunca debe descargar"))
    ui._consultar_coberturas(AOI, elegido_inicio, elegido_fin)
    sugerencias = estado["v9_sugerencias"]
    assert sugerencias["firma"] == ui._firma(AOI, elegido_inicio, elegido_fin)
    assert len(sugerencias["opciones"]) == 1
    assert sugerencias["opciones"][0]["par"] is bueno
    assert sugerencias["opciones"][0]["plan"] is not None
    assert sugerencias["opciones"][0]["cobertura"] > .95
    assert all(x["madurez"] == "VALIDATED" for x in llamadas)
    assert "v9_preparacion" not in estado and "nisar_auto_job" not in estado


def test_recomienda_fechas_incluso_si_existen_pares_invalidos_en_el_periodo(monkeypatch):
    """El par con cobertura insuficiente no impide proponer otro período."""
    actual = _par("C1", "C2", box(-76.80, 7.55, -76.76, 7.8))
    actual.antes.nombre.inicio = datetime(2026, 10, 28, tzinfo=timezone.utc)
    actual.despues.nombre.inicio = datetime(2026, 11, 3, tzinfo=timezone.utc)
    alterno = _par("A1", "A2", box(*AOI))
    alterno.antes.nombre.inicio = datetime(2026, 11, 11, tzinfo=timezone.utc)
    alterno.despues.nombre.inicio = datetime(2026, 11, 14, tzinfo=timezone.utc)
    r = _resultado([actual, alterno])
    estado = {}
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.cat, "buscar", lambda *a, **kw: r)
    ui._consultar_coberturas(AOI, date(2026, 10, 26), date(2026, 11, 5))
    assert len(estado["v9_coberturas"]["opciones"]) == 1
    assert estado["v9_coberturas"]["opciones"][0]["plan"] is None
    recomendaciones = estado["v9_sugerencias"]["opciones"]
    assert len(recomendaciones) == 1
    assert recomendaciones[0]["par"] is alterno
    assert recomendaciones[0]["plan"] is not None


def test_no_inventa_fechas_si_ningun_par_alcanza_cobertura_minima(monkeypatch):
    actual = _par("M1", "M2", box(-76.80, 7.55, -76.78, 7.8))
    r = _resultado([actual])
    estado = {}
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.cat, "buscar", lambda *a, **kw: r)
    ui._consultar_coberturas(AOI, INI, FIN)
    assert estado["v9_sugerencias"]["opciones"] == []
    assert not any(x.get("plan") is not None for x in estado["v9_coberturas"]["opciones"])


def test_fechas_alternativas_visibles_encima_de_analizar_y_sin_descarga(monkeypatch):
    """La recomendación principal debe estar arriba, sin abrir Harmony."""
    from contextlib import nullcontext

    par = _par("S1", "S2", box(*AOI))
    par.antes.nombre.inicio = datetime(2026, 11, 11, tzinfo=timezone.utc)
    par.despues.nombre.inicio = datetime(2026, 11, 14, tzinfo=timezone.utc)
    r = _resultado([par])
    opciones = geo.opciones(r, [par])
    fecha_ini, fecha_fin = date(2026, 10, 20), date(2026, 10, 25)
    firma = ui._firma(AOI, fecha_ini, fecha_fin)
    estado = {
        "zona": {"limites": list(AOI)},
        "v9_inicio_periodo": fecha_ini, "v9_fin_periodo": fecha_fin,
        "v9_coberturas": {"firma": firma, "opciones": [],
                         "seleccionado": None},
        "v9_sugerencias": {"firma": firma, "madurez": "VALIDATED",
                           "opciones": opciones},
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.st, "container", lambda **kw: nullcontext())
    monkeypatch.setattr(ui.st, "caption", lambda *a, **kw: None)
    monkeypatch.setattr(ui.st, "warning", lambda msg: eventos.append(("warning", msg)))
    monkeypatch.setattr(ui.st, "expander", lambda *a, **kw: nullcontext())
    eventos = []

    def boton(label, **kwargs):
        eventos.append(("button", kwargs["key"]))
        return False

    monkeypatch.setattr(ui.st, "button", boton)
    ui.accion_principal()
    assert ("button", "v9_usar_sugerencia_0") in eventos
    assert eventos.index(("button", "v9_usar_sugerencia_0")) < (
        eventos.index(("button", "v9_analizar"))
    )
    assert any("NASA CMR" in msg for tipo, msg in eventos if tipo == "warning")
    assert "nisar_auto_job" not in estado
    callback = next(x for x in opciones if x["plan"] is not None)
    ui._usar_fechas_sugeridas(
        callback["par"].antes.nombre.inicio.date(),
        callback["par"].despues.nombre.inicio.date(),
    )
    assert estado["v9_inicio_periodo"] == date(2026, 11, 11)
    assert estado["v9_fin_periodo"] == date(2026, 11, 14)
    assert "v9_coberturas" not in estado and "v9_sugerencias" not in estado



def test_fallo_busqueda_ampliada_no_borra_catalogo_ni_inventa_fechas(monkeypatch):
    """Si CMR falla solo en búsqueda extendida, mantener resultado principal."""
    par = _par("S1", "S2", box(-76.80, 7.55, -76.79, 7.8))
    resultado = _resultado([par])
    periodo_inicio = date(2026, 8, 1)
    periodo_fin = date(2026, 8, 8)
    estado = {}
    llamadas = []
    monkeypatch.setattr(ui.st, "session_state", estado)

    def buscar(*args, **kwargs):
        llamadas.append(kwargs["madurez"])
        if len(llamadas) > 1:
            raise ui.cat.ErrorServicio("NASA CMR temporalmente fuera de servicio")
        return resultado

    monkeypatch.setattr(ui.cat, "buscar", buscar)
    ui._consultar_coberturas(AOI, periodo_inicio, periodo_fin)
    assert len(llamadas) == 2
    assert all(x == "PROVISIONAL" for x in llamadas)
    assert estado["v9_coberturas"]["resultado"] is resultado
    assert estado["v9_sugerencias"]["opciones"] == []
    assert estado["v9_sugerencias"]["consulta_incompleta"] is True
    avisos = []
    monkeypatch.setattr(ui.st, "warning", lambda txt: avisos.append(txt))
    ui._mostrar_sugerencias(ui._firma(AOI, periodo_inicio, periodo_fin))
    assert len(avisos) == 1
    assert "CMR" in avisos[0]



def test_reintento_cog_solo_tras_clic_para_mismo_par_y_aoi(monkeypatch):
    """El presupuesto ampliado crea un NUEVO job; no modifica el fallido."""
    par = _par("T1", "T2", box(*AOI))
    resultado = _resultado([par])
    opciones = geo.opciones(resultado, [par])
    item = opciones[0]
    firma = ui._firma(AOI, INI, FIN)
    estado = {
        "zona": {"limites": list(AOI)},
        "v9_inicio_periodo": INI, "v9_fin_periodo": FIN,
        "v9_coberturas": {
            "firma": firma, "opciones": opciones, "seleccionado": item["id"],
        },
        "v9_firma": firma, "v9_preparacion": "fallido_previo",
        ui._clave_aceptacion(firma, item["id"]): True,
    }
    fallo = {
        "estado": ui.trabajos.ERROR,
        "aoi": {"limites": list(AOI)},
        "escenas": {"antes": "T1", "despues": "T2"},
        "error": "COG_DEMASIADO_GRANDE: NASA Harmony devolvió 227.8 MiB",
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.trabajos, "leer", lambda ident: fallo)
    llamadas = []
    monkeypatch.setattr(
        ui, "_solicitar_elegido",
        lambda zona, inicio, fin, estado_actual, elegido: (
            llamadas.append((tuple(zona), inicio, fin, elegido["id"]))
            or "nuevo_job_1024"
        ),
    )
    assert ui._reintentar_mismo_par_cog() is True
    assert llamadas == [(AOI, INI, FIN, item["id"])]
    assert estado["v9_preparacion"] == "nuevo_job_1024"
    assert estado["v9_firma"] == firma
    assert estado["nisar_auto_job"] == "nuevo_job_1024"
    assert not estado.get("v9_error")


def test_reintento_cog_no_permita_otro_par_ni_job_activo(monkeypatch):
    """Un cambio de escena o un job en curso no se considera consentimiento."""
    par = _par("T1", "T2", box(*AOI))
    opciones = geo.opciones(_resultado([par]), [par])
    item = opciones[0]
    firma = ui._firma(AOI, INI, FIN)
    estado = {
        "zona": {"limites": list(AOI)},
        "v9_inicio_periodo": INI, "v9_fin_periodo": FIN,
        "v9_coberturas": {
            "firma": firma, "opciones": opciones, "seleccionado": item["id"],
        },
        "v9_firma": firma, "v9_preparacion": "fallido_previo",
        ui._clave_aceptacion(firma, item["id"]): True,
    }
    fallo = {
        "estado": ui.trabajos.ERROR,
        "aoi": {"limites": list(AOI)},
        "escenas": {"antes": "Otras1", "despues": "Otras2"},
        "error": "COG_DEMASIADO_GRANDE: excedido",
    }
    monkeypatch.setattr(ui.st, "session_state", estado)
    monkeypatch.setattr(ui.trabajos, "leer", lambda ident: fallo)
    monkeypatch.setattr(ui, "_solicitar_elegido",
                        lambda *a: pytest.fail("no debe iniciarse descarga"))
    assert ui._reintentar_mismo_par_cog() is False
    assert estado["v9_preparacion"] == "fallido_previo"
    assert "otro par o zona" in estado["v9_error"]
    fallo["escenas"] = {"antes": "T1", "despues": "T2"}
    fallo["estado"] = ui.trabajos.EN_CURSO
    assert ui._reintentar_mismo_par_cog() is False
    assert estado["v9_preparacion"] == "fallido_previo"
