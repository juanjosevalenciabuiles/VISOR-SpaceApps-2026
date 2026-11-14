"""Disposición: sin superposiciones ni desbordes en escritorio, tablet y móvil."""
import pytest

TAMANOS = [(1920, 1080), (1440, 900), (1366, 768), (1280, 720), (1200, 800), (1000, 700), (900, 1000)]


@pytest.mark.parametrize("ancho,alto", TAMANOS, ids=[f"{a}x{b}" for a, b in TAMANOS])
def test_sin_superposiciones(abrir, ancho, alto):
    p = abrir(ancho, alto)
    assert p.superposiciones() == []
    # Con un resultado activo la barra superior tiene dos grupos: no debe desbordarse.
    p.page.locator(".st-key-panel_explorador").evaluate("e=>e.scrollTop=e.scrollHeight")
    p.alternar("res_coincidencia_vv_vh_20260924_20261006")
    barra = p.page.evaluate("""()=>{const b=document.querySelector('.st-key-barra_superior');
        const der=Math.max(...[...b.querySelectorAll('button')].filter(x=>x.offsetWidth).map(x=>x.getBoundingClientRect().right));
        return {desborde:b.scrollWidth>b.clientWidth+1, botones:der<=b.getBoundingClientRect().right+1}}""")
    assert barra == {"desborde": False, "botones": True}
    assert p.superposiciones() == []
    assert not p.page.evaluate("()=>document.documentElement.scrollWidth>innerWidth")


def test_movil(abrir):
    p = abrir(390, 844, movil=True)
    assert not p.page.evaluate("()=>document.documentElement.scrollWidth>innerWidth")
    atribucion = p.mapa.evaluate("()=>document.querySelector('.leaflet-control-attribution').getBoundingClientRect().top")
    fondos = p.page.evaluate("""()=>['panel_explorador','panel_info'].map(k=>{const e=document.querySelector('.st-key-'+k);
        return e&&getComputedStyle(e).display!=='none'?e.getBoundingClientRect().bottom:0})""")
    assert max(fondos) <= atribucion, "las hojas inferiores dejan libre la atribución"
    botones = p.page.evaluate("""()=>[...document.querySelectorAll('.st-key-barra_superior button')].filter(b=>b.offsetWidth)
        .map(b=>b.getBoundingClientRect().right<=innerWidth)""")
    assert botones and all(botones)
    p.clic("cerrar_explorador")
    info = p.page.locator(".st-key-panel_info").bounding_box()
    assert info["y"] + info["height"] > 844 * 0.8, "sin explorador, la información baja al borde inferior"
