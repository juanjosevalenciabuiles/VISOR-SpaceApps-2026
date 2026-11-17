"""V.I.S.O.R. — Visualización Inteligente de Superficies y Observación por Radar.

Punto de entrada · interfaz Mission Control Earth Explorer: un único mapa a
pantalla completa con superficies flotantes. Solo orquesta: cada pieza de
interfaz vive en components/ y la lógica de datos en utils/.
"""
import os

import streamlit as st

from components import bienvenida, capas_ambientales, estilos, flujo, interfaz, mapa, panel_capas, v9_experiencia
from components import herramientas_sar as herramientas
from components import resultados as ui_resultados
from utils import alcance_geografico, diagnostico
from utils.config import FENOMENOS
from utils.geotiff import ErrorCapa, cargar_capa
from utils.resultados import cargar_resultados

st.set_page_config(
    page_title="V.I.S.O.R. · Inundaciones",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Muestra independiente sin acceso a la red ni modificación de los archivos SAR.
# Es una vista seleccionada voluntariamente, nunca el arranque predeterminado.
if st.session_state.get("visor_modo_muestra_real"):
    from components import exhibicion_real
    exhibicion_real.render()
    st.stop()

interfaz.inicializar_estado()
# Inyectar el estilo ANTES de construir paneles. Si un widget falla,
# la vista no queda sin la estética Mission Control.
clave_tema = st.session_state.get("fenomeno", "inundacion")
estilos.inyectar_tema(FENOMENOS.get(clave_tema, FENOMENOS["inundacion"]))

# 1. En modo público cargar SOLO el GeoTIFF activo, no todos los históricos.
#    Una selección borrada/inválida se limpia por flujo.sincronizar, no reactiva el historial.
#    QA conserva el inventario completo para regresiones y pruebas de seguridad.
mostrar_historial_qa = os.environ.get("VISOR_MOSTRAR_HISTORIAL") == "1"
solo_id = None if mostrar_historial_qa else (
    (st.session_state.get("resultado_activo") or {}).get("id") or "")
resultados, fuera_de_alcance = alcance_geografico.filtrar_resultados(
    cargar_resultados(solo_id=solo_id))
st.session_state["resultados_fuera_de_alcance"] = fuera_de_alcance
# Desactivar históricos heredados de una sesión previa, sin borrar los archivos.
if flujo.es_historico() and os.environ.get("VISOR_MOSTRAR_HISTORIAL") != "1":
    flujo.limpiar_resultado()
activo = flujo.sincronizar(resultados)
# Comprobación ligera de servicios externos, una vez cada 15 min por proceso y sin bloquear la vista.
diagnostico.comprobar_en_segundo_plano()
# Dock permanente: se dibuja antes de Controles para que todos los interruptores
# afecten al mapa en esta misma ejecución, sin recálculo ni duplicados.
panel_capas.render(resultados, activo)
controles = interfaz.panel_explorador(resultados, activo)
fenomeno = FENOMENOS[controles.clave]
interfaz.aplicar_css_estado()

# La capa DEMO solo se carga si se pidió a propósito.
capa, error = None, None
if controles.mostrar_capa:
    try:
        capa = cargar_capa(fenomeno.ruta, categorico=fenomeno.categorico)
    except ErrorCapa as e:
        error = str(e)

# 2. El mapa único, detrás de todo.
with st.container(key="lienzo_mapa"):
    mapa.render(fenomeno, capa, controles, st.session_state["vista"], resultados,
                [*herramientas.grupos_mapa(), *capas_ambientales.grupos_mapa(),
                 *v9_experiencia.grupos_mapa()],
                seguir_vista=herramientas.necesita_vista(),
                seleccionar_par=v9_experiencia.modo_seleccion_mapa())

# Leyenda SAR siempre visible al lado del mapa (solo si hay GeoTIFF activo).
# Fuente única: el perfil científico del archivo, no el resultado del historial.
if activo is not None and controles.resultados.get(activo.id) is not None:
    with st.container(key="visor_leyenda_flotante"):
        st.markdown(ui_resultados.leyenda_rapida_html(activo),
                    unsafe_allow_html=True)

# 3. Superficies flotantes.
activos = [activo] if activo is not None else []
interfaz.barra_superior(fenomeno, capa, activos, controles.mostrar_capa)
# Acceso propio, fuera de la barra que recorta botones en pantallas pequeñas.
interfaz.buscador()
interfaz.panel_informacion(fenomeno, capa, error, controles, resultados)
interfaz.herramientas_sar()
# La línea temporal flotante se retiró: fechas disponibles en la ficha científica.
interfaz.guia_eco(activos)
# La guía es un panel persistente: se dibuja en cada rerun.
# Mover el mapa no modifica visor_guia_abierta; solo botones explícitos la cierran.
bienvenida.render()

