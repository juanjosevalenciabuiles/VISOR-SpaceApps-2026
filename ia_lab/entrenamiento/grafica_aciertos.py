# ========================================
# grafica_aciertos.py
# ========================================

import json
from pathlib import Path

import matplotlib.pyplot as plt

# ========================================
# 1. Read the JSON
# ========================================
CARPETA = Path(__file__).resolve().parent / "salidas"
with open(CARPETA / "PRUEBA_si_no.json", encoding="utf-8") as archivo:
    prueba = json.load(archivo)

# ========================================
# 2. Extract the 4 rows to compare
# ========================================
A_modelo = [f for f in prueba["A_diario"] if f["H"] == 3 and f["modelo"].startswith("Random Forest")][0]
A_regla  = [f for f in prueba["A_diario"] if f["H"] == 3 and f["modelo"].startswith("Regla")][0]

B_modelo = [f for f in prueba["B_zonas"] if f["par"] == "TOTAL E6" and f["modelo"].startswith("XGBoost")][0]
B_regla  = [f for f in prueba["B_zonas"] if f["par"] == "TOTAL E6" and f["modelo"].startswith("Regla")][0]

# ========================================
# 3. Print and verify the numbers from the confusion matrix
# ========================================
print("=" * 40)
print("PRUEBA SÍ/NO (datos que el modelo no vio)")
print("=" * 40)
for nombre, fila in [("A · Random Forest", A_modelo), ("A · Regla nivel hoy", A_regla),
                     ("B · XGBoost", B_modelo), ("B · Regla terreno", B_regla)]:
    detecta = 100 * fila["VP"] / (fila["VP"] + fila["FN"])
    acierta = 100 * fila["VN"] / (fila["VN"] + fila["FP"])
    print(f"{nombre:<20} detecta SÍ: {detecta:5.1f} % ({fila['VP']}/{fila['VP'] + fila['FN']})"
          f"   acierta NO: {acierta:5.1f} % ({fila['VN']}/{fila['VN'] + fila['FP']})")
print("=" * 40)

# ========================================
# 4. Plot: one panel per model
# ========================================
AZUL, NARANJA = "#2a78d6", "#eb6834"
FONDO, TINTA, GRIS, REJILLA = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
METRICAS = ["detecta_SI_%", "acierta_NO_%"]
ANCHO = 0.34


def panel(ax, modelo, regla, titulo, etiquetas_x, nombre_modelo, nombre_regla):
    for desplazamiento, fila, color, nombre in [(-0.18, modelo, AZUL, nombre_modelo),
                                                (+0.18, regla, NARANJA, nombre_regla)]:
        valores = [fila[m] for m in METRICAS]
        posiciones = [i + desplazamiento for i in range(len(METRICAS))]
        barras = ax.bar(posiciones, valores, width=ANCHO, color=color, label=nombre)
        ax.bar_label(barras, fmt="%.0f %%", padding=3, color=TINTA, fontsize=11)

    ax.set_title(titulo, loc="left", color=TINTA, fontsize=12, pad=12)
    ax.set_xticks(range(len(METRICAS)), etiquetas_x, color=GRIS, fontsize=10)
    ax.set_ylim(0, 108)
    ax.set_yticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100 %"], color=GRIS, fontsize=9)
    ax.grid(axis="y", color=REJILLA, linewidth=0.8)
    ax.set_axisbelow(True)
    for lado in ["top", "right", "left"]:
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(length=0)
    ax.set_facecolor(FONDO)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False, fontsize=10, labelcolor=GRIS)


fig, (ax_A, ax_B) = plt.subplots(1, 2, figsize=(11, 5.2), facecolor=FONDO)

panel(ax_A, A_modelo, A_regla,
      "Modelo A · nivel alto del Atrato en Quibdó, 3 días antes",
      ["Detecta días\nde nivel alto", "Acierta días\nnormales"],
      "Random Forest", "Regla: nivel de hoy")

panel(ax_B, B_modelo, B_regla,
      "Modelo B · zonas de 2 km inundadas en E6",
      ["Detecta zonas\ninundadas", "Acierta zonas\nsecas"],
      "XGBoost", "Regla de terreno")

fig.suptitle("¿Le ganan los modelos a una regla simple?", x=0.06, ha="left",
             fontsize=15, fontweight="bold", color=TINTA)
fig.text(0.06, 0.015, "Prueba con datos que el modelo no vio: días 2022–2026 (A) y evento E6 (B). "
         "Real sin validar: sin verificación en campo.", color=GRIS, fontsize=9)
fig.tight_layout(rect=(0.03, 0.04, 1, 0.95))

salida = CARPETA / "grafica_aciertos.png"
fig.savefig(salida, dpi=200, facecolor=FONDO)
print(f"Gráfica guardada en: {salida}")
plt.show()
