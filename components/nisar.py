"""Panel NISAR (banda L) de Herramientas SAR. Separado del flujo Sentinel-1.

A · Catálogo   búsqueda de solo metadatos (CMR de NASA). Los pares son
               «CANDIDATO NO VALIDADO»; si no hay ninguno, se dice por qué.
B · Recortes   HDF5 GCOV ya presentes en data/nisar/crudos/ → ventana del
               área en gamma0 de potencia. La app no descarga nada.
C · Análisis   cambio temporal solo entre recortes compatibles, con umbrales
               experimentales que se escriben a mano; si no hay par, escena
               única en dB.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import streamlit as st

from utils import nisar_catalogo as cat
from utils import nisar_flujo, nisar_gcov
from utils.analisis_sar import ErrorSAR, ParametrosCambio
from utils.buscador_sar import ErrorBusqueda

PASOS = ("A · Catálogo", "B · Recortes", "C · Análisis")
CARPETA_CRUDOS = nisar_gcov.CARPETA_NISAR / "crudos"


def _nota(texto: str, clase: str = "visor-leyenda-nota") -> None:
    st.markdown(f'<div class="{clase}">{escape(texto)}</div>', unsafe_allow_html=True)


class _Guardada:
    def __init__(self, cuerpo: bytes):
        self.cuerpo = cuerpo

    def read(self) -> bytes:
        return self.cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def catalogo_simulado() -> Path | None:
    """Solo pruebas automáticas (VISOR_NISAR_SIMULADO): se anuncia en pantalla."""
    ruta = os.environ.get("VISOR_NISAR_SIMULADO")
    return Path(ruta) if ruta else None


def _buscar(region) -> None:
    simulado = catalogo_simulado()
    abrir = (lambda *_a, **_k: _Guardada(simulado.read_bytes())) if simulado else None
    try:
        r = cat.buscar(*region.limites, st.session_state["nisar_inicio"], st.session_state["nisar_fin"],
                       madurez="VALIDATED", abrir=abrir)
    except ErrorBusqueda as e:
        st.session_state.update(nisar_busqueda=None, nisar_error=str(e))
        return
    st.session_state.update(nisar_busqueda=r, nisar_error=None)


def paso_catalogo(region, error_region: str | None) -> None:
    _nota("NISAR L2 GCOV · banda L · madurez VALIDATED (adquisiciones desde el 21-oct-2026). Solo metadatos: "
          "no se descarga nada y no requiere credenciales.", "mc-aviso")
    c1, c2 = st.columns(2)
    c1.date_input("Desde", value=cat.INICIO_VALIDATED, key="nisar_inicio", format="YYYY-MM-DD")
    c2.date_input("Hasta", value=datetime.now(timezone.utc).date(), key="nisar_fin", format="YYYY-MM-DD")
    if error_region:
        _nota(f"Área no válida (paso 01 de Sentinel-1): {error_region}", "mc-aviso")
        return
    _nota(f"Área: {region.oeste:.4f}, {region.sur:.4f}, {region.este:.4f}, {region.norte:.4f} "
          "(la del paso 01 · Área).")
    if catalogo_simulado():
        _nota("CATÁLOGO SIMULADO (pruebas automáticas): no es una consulta real.", "mc-aviso")
    if st.button("Buscar en el catálogo NISAR", key="nisar_buscar", icon=":material/search:"):
        with st.spinner("Consultando el catálogo de NASA (solo metadatos)…"):
            _buscar(region)
    if st.session_state.get("nisar_error"):
        _nota(st.session_state["nisar_error"], "mc-aviso")
    r = st.session_state.get("nisar_busqueda")
    if r is None:
        return
    st.markdown(f'<div class="visor-seccion">{len(r.candidatos)} escena(s) candidata(s) · '
                f"{r.total_catalogo} en el catálogo</div>", unsafe_allow_html=True)
    if r.candidatos:
        filas = "".join(
            f"<tr><td>{c.nombre.inicio:%Y-%m-%d %H:%M}</td><td>T{c.nombre.track:03d} · F{c.nombre.frame:03d} · "
            f"{'asc' if c.nombre.direccion == 'ASCENDING' else 'desc'}</td>"
            f"<td>A: {escape('/'.join(c.nombre.pol_a) or '—')} {c.nombre.modo_a} MHz<br>"
            f"B: {escape('/'.join(c.nombre.pol_b) or '—')} {c.nombre.modo_b} MHz</td>"
            f"<td>{escape(c.nombre.crid)} · {escape(c.madurez)}</td><td>{c.cobertura:.0%}</td>"
            f"<td>{f'{c.tamano_bytes / 1e9:.1f} GB' if c.tamano_bytes else '—'}</td></tr>"
            f'<tr><td colspan="6"><code>{escape(c.granule)}</code></td></tr>' for c in r.candidatos)
        st.markdown('<table class="mc-tabla"><thead><tr><th>Inicio (UTC)</th><th>Track · frame</th>'
                    "<th>Polarizaciones</th><th>CRID · madurez</th><th>Cubre</th><th>HDF5</th></tr></thead>"
                    f"<tbody>{filas}</tbody></table>", unsafe_allow_html=True)
    for p in r.pares:
        _nota(f"{p.estado}: {p.antes.nombre.inicio:%Y-%m-%d} → {p.despues.nombre.inicio:%Y-%m-%d} "
              f"({p.dias:.0f} días, cubre {p.cobertura_comun:.0%}). {p.avisos[0]}", "mc-aviso")
    if r.candidatos and not r.pares:
        st.markdown('<div class="visor-seccion">Sin par temporal compatible</div><ul class="visor-lista">'
                    + "".join(f"<li>{escape(b)}</li>" for b in r.bloqueos[:8]) + "</ul>", unsafe_allow_html=True)
    for a in [*r.avisos, *r.descartes[:4]]:
        _nota(a)


def paso_recortes(region, error_region: str | None) -> None:
    _nota("La app no descarga productos NISAR. Copia el HDF5 GCOV en data/nisar/crudos/ "
          "(scripts/nisar.py explica cómo, con Earthdata Login por variable de entorno).")
    crudos = sorted(CARPETA_CRUDOS.glob("*.h5")) if CARPETA_CRUDOS.is_dir() else []
    if not crudos:
        _nota("No hay ningún HDF5 en data/nisar/crudos/.", "mc-aviso")
    else:
        elegido = st.selectbox("Producto GCOV local", [p.name for p in crudos], key="nisar_h5")
        try:
            producto = nisar_gcov.inspeccionar(CARPETA_CRUDOS / elegido)
        except nisar_gcov.ErrorGCOV as e:
            _nota(str(e), "mc-aviso")
            producto = None
        if producto is not None:
            st.markdown(
                f'<div class="visor-leyenda-nota">Misión {escape(producto.mision or "no declarada")} · track '
                f"{producto.track} · frame {producto.frame} · {escape(producto.direccion or '?')} · "
                f"{escape((producto.inicio or '?')[:19])} · CRID {escape(producto.crid or 'no declarado')}</div>",
                unsafe_allow_html=True)
            for a in producto.avisos[:4]:
                _nota(a, "mc-aviso")
            capas = [f"{c.frecuencia}:{c.termino}" for c in producto.capas]
            capa = st.selectbox("Capa (frecuencia : término diagonal)", capas, key="nisar_capa",
                                help="Solo términos diagonales reales. HHHH es HH; nunca se rotula como VV/VH.")
            st.checkbox("La madurez VALIDATED de este granule se comprobó en el catálogo", value=False,
                        key="nisar_madurez_ok")
            if st.button("Recortar el área de interés", key="nisar_recortar", icon=":material/crop:",
                         disabled=error_region is not None):
                frecuencia, termino = capa.split(":")
                try:
                    with st.spinner("Leyendo solo la ventana del área…"):
                        salida = nisar_gcov.exportar_recorte(
                            CARPETA_CRUDOS / elegido, region.limites, frecuencia, termino,
                            madurez="VALIDATED" if st.session_state["nisar_madurez_ok"] else None)
                    st.session_state["nisar_mensaje"] = f"Recorte creado: {salida.name} (el HDF5 no se modificó)."
                except nisar_gcov.ErrorGCOV as e:
                    st.session_state["nisar_mensaje"] = str(e)
    if st.session_state.get("nisar_mensaje"):
        _nota(st.session_state["nisar_mensaje"], "mc-aviso")
    recortes, avisos = nisar_flujo.recortes_locales()
    st.markdown(f'<div class="visor-seccion">Recortes en data/nisar/ ({len(recortes)})</div>',
                unsafe_allow_html=True)
    for r in recortes:
        g = r.geometria
        _nota(f"{r.ruta.name} · {g['frecuencia']}:{g['termino']} · T{g['track']} F{g['frame']} · CRID {g['crid'] or '—'} "
              f"· madurez {g['madurez'] or '—'}" + (" · DEMO" if r.es_demo else ""))
    for a in avisos[:4]:
        _nota(a, "mc-aviso")


def paso_analisis(region, abrir_explorador) -> None:
    inv = nisar_flujo.inventario()
    if not inv.recortes:
        _nota("Aún no hay recortes NISAR en data/nisar/ (paso B).")
        return
    aoi = region.limites if region is not None else None
    if inv.pares:
        opciones = {f"{p.antes.fecha:%Y-%m-%d} → {p.despues.fecha:%Y-%m-%d} · {p.antes.geometria['frecuencia']}:"
                    f"{p.antes.geometria['termino']} · T{p.antes.geometria['track']} F{p.antes.geometria['frame']}": p
                    for p in inv.pares}
        par = opciones[st.selectbox("Par de recortes compatible", list(opciones), key="nisar_par")]
        _nota("Umbrales EXPERIMENTALES para banda L: no hay valores por defecto ni se usan los de Sentinel-1. "
              "Escríbelos para poder analizar.", "mc-aviso")
        c1, c2, c3 = st.columns(3)
        dis = c1.number_input("Disminución (dB)", min_value=0.5, max_value=20.0, value=None, step=0.5,
                              key="nisar_umbral_dis")
        aum = c2.number_input("Aumento (dB)", min_value=0.5, max_value=20.0, value=None, step=0.5,
                              key="nisar_umbral_aum")
        ventana = c3.selectbox("Speckle (px)", [1, 3, 5, 7, 9], index=2, key="nisar_ventana",
                               help="Media móvil en potencia; 1 = sin filtro.")
        if st.button("Analizar par NISAR", key="nisar_analizar", type="primary", icon=":material/play_arrow:",
                     disabled=dis is None or aum is None):
            try:
                with st.spinner("Analizando con el motor SAR…"):
                    r = nisar_flujo.analizar(par, aoi, ParametrosCambio(float(dis), float(aum), int(ventana)))
                st.session_state["nisar_resultado"] = (f"Generados en data/analisis/: {r.diferencia.name}, "
                                                       f"{r.mascara.name}. Nada se sobrescribió.")
                st.rerun()
            except ErrorSAR as e:
                st.session_state["nisar_resultado"] = str(e)
    else:
        st.markdown('<div class="visor-seccion">Sin par temporal compatible</div><ul class="visor-lista">'
                    + "".join(f"<li>{escape(b)}</li>" for b in inv.bloqueos[:8]) + "</ul>", unsafe_allow_html=True)
    st.markdown('<div class="visor-seccion">Escena única (sin cálculo de cambio)</div>', unsafe_allow_html=True)
    nombres = {r.ruta.name: r for r in inv.recortes}
    unico = nombres[st.selectbox("Recorte", list(nombres), key="nisar_unica")]
    if st.button("Ver gamma0 en dB", key="nisar_ver_unica", icon=":material/image:"):
        try:
            salida = nisar_flujo.escena_unica(unico)
            st.session_state["nisar_resultado"] = f"Generado en data/analisis/: {salida.name} (una fecha, sin umbral)."
            st.rerun()
        except ErrorSAR as e:
            st.session_state["nisar_resultado"] = str(e)
    if st.session_state.get("nisar_resultado"):
        _nota(st.session_state["nisar_resultado"], "mc-aviso")
    for a in inv.avisos[:4]:
        _nota(a)
    _nota("Cambio de señal de radar en banda L: no confirma inundaciones. Que el GCOV sea VALIDATED no valida "
          "el mapa derivado.")
    st.button("Abrir el explorador", key="nisar_ir_explorador", icon=":material/layers:", type="tertiary",
              on_click=abrir_explorador)


def render(region, error_region: str | None, abrir_explorador) -> None:
    catalogo, recortes, analisis = st.tabs(list(PASOS), key="nisar_paso")
    with catalogo:
        paso_catalogo(region, error_region)
    with recortes:
        paso_recortes(region, error_region)
    with analisis:
        paso_analisis(region, abrir_explorador)

