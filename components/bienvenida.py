"""Guía inicial de V.I.S.O.R. para visitantes nuevos.

El modal se abre una sola vez por sesión de Streamlit; no altera el visor,
el estado SAR, el historial, los GeoTIFF ni la configuración del usuario.
La ayuda extendida sigue disponible en la barra superior.
"""
from __future__ import annotations

import streamlit as st

CLAVE_MOSTRADA = "visor_guia_inicial_mostrada_v1"


def corresponde_mostrar() -> bool:
    """Marca antes de abrir: cerrar el modal no lo reabre en cada rerun."""
    if st.session_state.get(CLAVE_MOSTRADA, False):
        return False
    st.session_state[CLAVE_MOSTRADA] = True
    return True


@st.dialog("Bienvenido a V.I.S.O.R. 🛰️", width="large")
def mostrar() -> None:
    st.markdown(
        "**Explora Colombia y descubre qué información aportan las observaciones de radar SAR.** "
        "Este recorrido te ayuda a empezar sin conocimientos de teledetección."
    )
    st.markdown(
        """
**1. Busca un lugar.** Usa el buscador de la parte superior izquierda
para escribir el nombre de un municipio o sus coordenadas. Puedes acercar,
alejar y mover el mapa.

**2. Selecciona tu zona.** Abre **Herramientas SAR**, pulsa
**«▭ Seleccionar zona»**, dibuja el rectángulo entre dos esquinas y suelta.
Si tu versión lo solicita, confirma con **«Usar esta zona»**.

**3. Elige fechas y consulta las escenas.** En Herramientas SAR indica
el período y pulsa **«Buscar imágenes SAR»**. La cobertura NISAR o
Sentinel-1 depende de las adquisiciones reales; algunas fechas pueden
no tener escenas compatibles.

**4. Analiza o revisa resultados.** Si hay imágenes preparadas compatibles,
puedes iniciar un análisis. Para ver un GeoTIFF ya procesado sin descargar
datos, usa el **historial** del Explorador.

**5. Interpreta el mapa.** Abre **Información** para consultar la leyenda,
las fechas, el sensor y la procedencia. Puedes cambiar capas y transparencia.
El **Laboratorio IA** presenta experimentos históricos cuando esté disponible.
"""
    )
    st.info(
        "Importante: una variación de retrodispersión SAR es un indicio "
        "de cambio, no una inundación confirmada ni una alerta oficial.",
        icon="ℹ️",
    )
    st.caption(
        "Puedes volver a consultar instrucciones detalladas desde «Ayuda» "
        "en la barra superior. Esta ventana aparece una sola vez por sesión."
    )
    if st.button(
        "Comenzar a explorar", key="visor_bienvenida_comenzar",
        type="primary", use_container_width=True,
    ):
        st.rerun()
