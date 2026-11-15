# V10 · Corrección de visibilidad PC

Se separa **selector de fechas** de **línea temporal de resultados**. Sin un resultado activo con fechas reales, el usuario ve un selector compacto y no una línea de tiempo vacía que tape el mapa. Cuando existe un GeoTIFF real visible, se conservan las fechas T₁/T₂ del historial. Si hay productos verificables en la AOI y el usuario lo solicita, puede abrir la cronología de adquisiciones.

El botón histórico «Analizar» del panel científico se mantiene en su sección, con estilo sticky para intentar que permanezca dentro de la ventana de desplazamiento PC. **Es preciso confirmar con Playwright Chromium y Firefox el bounding box del botón antes de integrar.** En caso de fallo, no debe maquillarse la prueba: se corrige el layout real.

No hay cambios al motor SAR, datos, parámetros, móvil ni resultados científicos.