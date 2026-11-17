"""Las leyendas dependen del tipo de ráster, nunca del tamaño de inundación."""
from utils.leyenda_sar import aviso, entradas


def test_colores_continuos_no_afirmar_inundacion_pequena():
    es = dict(entradas("diferencia_db", "es"))
    en = dict(entradas("diferencia_db", "en"))
    assert "Menor señal" in es["#00BFEF"]
    assert "Mayor señal" in es["#FF9F0A"]
    assert "NO mide el tamaño" in es["#FF9F0A"]
    assert "flood size" in en["#FF9F0A"]
    assert "confirmed flooding" in aviso("en")


def test_naranja_vv_vh_es_disminucion_solo_vh():
    es = dict(entradas("coincidencia_vv_vh", "es"))
    en = dict(entradas("coincidencia_vv_vh", "en"))
    assert "solo en VV" in es["#00F0FF"]
    assert "solo en VH" in es["#FF9F0A"]
    assert "both VV and VH" in en["#7D7AFF"]


def test_mascara_y_perfiles_desconocidos():
    es = dict(entradas("mascara_cambios", "es"))
    assert "Aumento" in es["#FF9F0A"]
    assert entradas("desconocido", "en") == []


def test_leyenda_corta_se_inserta_delante_de_ficha():
    from pathlib import Path
    interfaz = (Path(__file__).resolve().parents[1] / "components" / "interfaz.py").read_text(
        encoding="utf-8"
    )
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'st.container(key="visor_leyenda_flotante")' in app
    assert "ui_resultados.leyenda_rapida_html(activo)" in app
    assert "ui_resultados.leyenda_rapida_html(res)" not in interfaz
    assert "ui_resultados.ficha_html(res)" in interfaz
