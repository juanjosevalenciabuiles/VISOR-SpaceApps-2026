"""El flujo de GitHub Actions debe ser YAML válido: si no lo es, GitHub no crea
ningún trabajo y la rama se queda sin pruebas sin que nada falle a la vista
(ocurrió el 13-nov-2026 con una clave `env` duplicada)."""
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
yaml = pytest.importorskip("yaml", reason="pyyaml está en requirements-dev.txt (no hace falta en Replit)")


class _SinDuplicados(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        claves = [self.construct_object(k, deep=deep) for k, _ in node.value]
        repetidas = {c for c in claves if claves.count(c) > 1}
        if repetidas:
            raise yaml.constructor.ConstructorError(None, None, f"claves repetidas: {sorted(map(str, repetidas))}",
                                                    node.start_mark)
        return super().construct_mapping(node, deep)


@pytest.mark.parametrize("ruta", sorted((RAIZ / ".github" / "workflows").glob("*.yml")), ids=lambda p: p.name)
def test_flujo_es_yaml_valido_y_sin_claves_repetidas(ruta):
    flujo = yaml.load(ruta.read_text(encoding="utf-8"), Loader=_SinDuplicados)   # noqa: S506 - cargador seguro
    assert isinstance(flujo.get("jobs"), dict) and flujo["jobs"]
    for nombre, trabajo in flujo["jobs"].items():
        assert trabajo.get("runs-on"), nombre
        for paso in trabajo["steps"]:
            assert ("run" in paso) != ("uses" in paso), (nombre, paso)


def test_trabajos_esperados():
    flujo = yaml.safe_load((RAIZ / ".github" / "workflows" / "pruebas.yml").read_text(encoding="utf-8"))
    assert {"calidad", "navegador", "catalogo-nisar", "red"} <= set(flujo["jobs"])
    # El catálogo real nunca bloquea; las pruebas sí.
    assert flujo["jobs"]["catalogo-nisar"].get("continue-on-error") is True
    assert not flujo["jobs"]["calidad"].get("continue-on-error")
