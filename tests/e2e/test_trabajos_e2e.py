"""Trabajos en segundo plano en el navegador: dos pestañas a la vez, recarga y pantalla completa.

Servidor real (el análisis corre en un hilo aparte, sin modo síncrono). RTC sintéticos y catálogo
ASF guardado: se prueba el flujo, no la ciencia.
"""
import json

import pytest

from conftest import Servidor, preparar_datos


@pytest.fixture(scope="module")
def servidor_trabajos(tmp_path_factory):
    s = Servidor(preparar_datos(tmp_path_factory.mktemp("trabajos") / "data"))
    yield s
    s.cerrar()


def _preparar(p):
    p.confirmar_zona()
    p.pestana_sar(1)
    p.clic("sar_buscar")
    p.pestana_sar(2)
    assert not p.page.locator(".st-key-sar_analizar button").first.is_disabled()
    assert p.page.locator(".mc-fase-datos").first.get_attribute("data-estado") == "PENDIENTE"


def _trabajos(datos):
    carpeta = datos / "trabajos"
    return [json.loads(f.read_text("utf-8")) for f in carpeta.glob("*.json")] if carpeta.exists() else []


def test_dos_pestanas_un_solo_trabajo_y_recuperacion_tras_recargar(abrir, servidor_trabajos):
    datos = servidor_trabajos.datos
    registros_antes = set((datos / "analisis").glob("*_registro.json"))
    uno, dos = abrir(url=servidor_trabajos.url), abrir(url=servidor_trabajos.url)
    _preparar(uno)
    _preparar(dos)
    # Las dos pulsan «Analizar» casi a la vez con la misma configuración.
    uno.page.locator(".st-key-sar_analizar button:visible").first.click()
    try:
        dos.page.locator(".st-key-sar_analizar button:visible").first.click(timeout=3000)
    except Exception:  # noqa: BLE001 — si el primero ya terminó, el botón está bloqueado: tampoco duplica
        pass
    uno.page.wait_for_function(
        "()=>{const e=document.querySelector('#trabajo-estado');return e && e.dataset.estado==='APTO'}",
        timeout=180_000)
    uno.esperar(1500)
    # La segunda pestaña o sigue el MISMO trabajo, o (si llegó tarde) ve que ya se analizó: nunca recalcula.
    dos.page.wait_for_function(
        "()=>{const e=document.querySelector('#trabajo-estado');"
        "return (e && e.dataset.estado==='APTO') || document.body.innerText.includes('ya se analizó')}",
        timeout=180_000)
    dos.esperar(1500)
    trabajos = _trabajos(datos)
    assert len(trabajos) == 1, "la misma configuración no crea dos trabajos"
    t = trabajos[0]
    assert t["estado"] == "APTO" and {f["estado"] for f in t["fases"]} == {"APTO"}
    assert len(set((datos / "analisis").glob("*_registro.json")) - registros_antes) == 1, "un solo cálculo"
    assert len(uno.capas_resultado()) == 1 and "ANÁLISIS DE ESTA SESIÓN" in uno.texto("barra_superior")
    fases = uno.page.locator(".mc-fases li").all_inner_texts()
    assert [f.split("\n")[0] for f in fases] == ["APTO"] * 7 and "Listo" in fases[-1]

    # Recargar (F5): la sesión empieza vacía, pero el trabajo sigue registrado y se abre a propósito.
    uno.page.reload()
    uno.esperar_mapa()
    uno.page.locator(".st-key-barra_superior").wait_for(timeout=60_000)
    uno.esperar(1500)
    assert uno.capas_resultado() == [] and "SIN RESULTADO" in uno.texto("barra_superior")
    uno.clic("btn_sar")
    uno.pestana_sar(3)
    uno.expandir("sar_trabajos")
    lista = uno.texto("sar_trabajos")
    assert t["job_id"] in lista and "APTO" in lista
    uno.clic(f"sar_abrir_trabajo_{t['job_id']}")
    assert len(uno.capas_resultado()) == 1 and "HISTÓRICO" in uno.texto("barra_superior")
    assert len(_trabajos(datos)) == 1, "abrir no crea trabajos"
    assert not uno.errores and not dos.errores


def test_pantalla_completa_del_mapa(abrir, servidor_trabajos):
    p = abrir(url=servidor_trabajos.url)
    boton = p.mapa.locator(".leaflet-control-zoom-fullscreen")
    assert boton.count() == 1 and boton.get_attribute("title") == "Pantalla completa"
    boton.click()
    p.page.wait_for_timeout(800)
    assert p.mapa.evaluate("()=>!!document.fullscreenElement"), "el mapa entra en pantalla completa"
    assert p.mapa.evaluate("()=>map.getSize().x") > 0
    p.mapa.locator(".leaflet-control-zoom-fullscreen").click()
    p.page.wait_for_timeout(800)
    assert not p.mapa.evaluate("()=>!!document.fullscreenElement")
