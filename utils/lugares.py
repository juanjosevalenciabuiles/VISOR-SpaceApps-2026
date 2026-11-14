"""Búsqueda de lugares por nombre para centrar el mapa. No define zonas ni analiza nada.

Dos fuentes, y la interfaz dice siempre cuál respondió:

1. **Geocodificador en línea**, solo al pulsar «Buscar» (nunca al teclear). Por defecto el
   servicio público Nominatim de OpenStreetMap, respetando su política de uso
   (operations.osmfoundation.org/policies/nominatim): sin autocompletado, como máximo una consulta
   por segundo en todo el proceso, identificación del programa (User-Agent), caché de respuestas y
   atribución visible. Para tráfico alto, quien despliega debe apuntar `VISOR_GEOCODIFICADOR_URL` a
   otro servicio compatible (con `VISOR_GEOCODIFICADOR_CLAVE` si lo exige) o desactivarlo con
   `VISOR_GEOCODIFICADOR_URL=desactivado`.
2. **Catálogo local** (sin red): capitales departamentales de Colombia, municipios de Urabá y
   ciudades principales del mundo, con nombres en español, inglés y local. Posición aproximada del
   centro (±0,05°), solo para ubicar el mapa. Si el servicio en línea falla, se usa este catálogo y
   se avisa. No contiene límites administrativos ni pretende ser exhaustivo.
"""
from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

AGENTE = "VISOR-SpaceApps-2026 (https://github.com/juanjosevalenciabuiles/VISOR-SpaceApps-2026)"
TIEMPO_LIMITE_S = 8
ESPERA_MINIMA_S = 1.1
MAX_RESULTADOS = 6
LOCAL, EN_LINEA = "catálogo local", "geocodificador en línea"
NOMINATIM = "https://nominatim.openstreetmap.org"
ATRIBUCION_NOMINATIM = "Búsqueda: Nominatim · datos © colaboradores de OpenStreetMap (ODbL)"


class ErrorLugares(RuntimeError):
    """El servicio en línea no respondió bien. El mensaje es apto para mostrarse."""


@dataclass(frozen=True)
class Lugar:
    nombre: str
    region: str            # departamento / estado
    pais: str
    latitud: float
    longitud: float
    zoom: int = 11
    fuente: str = LOCAL
    alias: tuple[str, ...] = ()     # otros nombres (inglés, local) de la ciudad y del país

    @property
    def etiqueta(self) -> str:
        return ", ".join(p for p in (self.nombre, self.region, self.pais) if p)


# Centro aproximado de la cabecera (±0,02°). Solo para ubicar el mapa.
_CO = "Colombia"
CATALOGO: tuple[Lugar, ...] = tuple(Lugar(n, r, _CO, la, lo, z) for n, r, la, lo, z in (
    ("Chigorodó", "Antioquia", 7.67, -76.68, 11), ("Carepa", "Antioquia", 7.76, -76.66, 12),
    ("Apartadó", "Antioquia", 7.88, -76.63, 12), ("Turbo", "Antioquia", 8.09, -76.73, 11),
    ("Necoclí", "Antioquia", 8.43, -76.78, 11), ("Mutatá", "Antioquia", 7.24, -76.44, 11),
    ("Medellín", "Antioquia", 6.25, -75.57, 11), ("Rionegro", "Antioquia", 6.15, -75.37, 12),
    ("El Carmen de Viboral", "Antioquia", 6.08, -75.34, 12), ("Caucasia", "Antioquia", 7.99, -75.19, 11),
    ("Rionegro", "Santander", 7.26, -73.15, 12),
    ("Bogotá", "Distrito Capital", 4.71, -74.07, 10), ("Cali", "Valle del Cauca", 3.45, -76.53, 11),
    ("Barranquilla", "Atlántico", 10.97, -74.80, 11), ("Cartagena de Indias", "Bolívar", 10.39, -75.48, 11),
    ("Cúcuta", "Norte de Santander", 7.89, -72.50, 11), ("Bucaramanga", "Santander", 7.12, -73.12, 11),
    ("Pereira", "Risaralda", 4.81, -75.69, 11), ("Santa Marta", "Magdalena", 11.24, -74.20, 11),
    ("Ibagué", "Tolima", 4.44, -75.23, 11), ("Pasto", "Nariño", 1.21, -77.28, 11),
    ("Manizales", "Caldas", 5.07, -75.52, 11), ("Neiva", "Huila", 2.93, -75.28, 11),
    ("Villavicencio", "Meta", 4.14, -73.63, 11), ("Armenia", "Quindío", 4.53, -75.68, 11),
    ("Valledupar", "Cesar", 10.46, -73.25, 11), ("Montería", "Córdoba", 8.75, -75.88, 11),
    ("Sincelejo", "Sucre", 9.30, -75.40, 11), ("Popayán", "Cauca", 2.44, -76.61, 11),
    ("Tunja", "Boyacá", 5.54, -73.36, 11), ("Riohacha", "La Guajira", 11.54, -72.91, 11),
    ("Quibdó", "Chocó", 5.69, -76.66, 11), ("Florencia", "Caquetá", 1.61, -75.61, 11),
    ("Yopal", "Casanare", 5.34, -72.40, 11), ("Arauca", "Arauca", 7.08, -70.76, 11),
    ("Mocoa", "Putumayo", 1.15, -76.65, 11), ("Leticia", "Amazonas", -4.21, -69.94, 11),
    ("San José del Guaviare", "Guaviare", 2.57, -72.64, 11), ("Mitú", "Vaupés", 1.25, -70.23, 11),
    ("Puerto Carreño", "Vichada", 6.19, -67.49, 11), ("Inírida", "Guainía", 3.87, -67.92, 11),
    ("San Andrés", "San Andrés y Providencia", 12.58, -81.70, 12),
)) + tuple(Lugar(n, r, p, la, lo, z, LOCAL, tuple(a.split("|"))) for n, r, p, la, lo, z, a in (
    # Ciudades principales del mundo: (nombre, región, país, lat, lon, zoom, alias separados por «|»)
    ("Ciudad de Panamá", "Panamá", "Panamá", 8.98, -79.52, 11, "Panama City|Panama"),
    ("Quito", "Pichincha", "Ecuador", -0.18, -78.47, 11, "Ecuador"),
    ("Lima", "Lima", "Perú", -12.05, -77.04, 11, "Peru"),
    ("Caracas", "Distrito Capital", "Venezuela", 10.49, -66.88, 11, "Venezuela"),
    ("La Paz", "La Paz", "Bolivia", -16.50, -68.15, 11, "Bolivia"),
    ("Santiago", "Región Metropolitana", "Chile", -33.45, -70.67, 11, "Santiago de Chile|Chile"),
    ("Buenos Aires", "Buenos Aires", "Argentina", -34.60, -58.38, 11, "Argentina"),
    ("Montevideo", "Montevideo", "Uruguay", -34.90, -56.16, 11, "Uruguay"),
    ("Asunción", "Asunción", "Paraguay", -25.26, -57.58, 11, "Asuncion|Paraguay"),
    ("Brasilia", "Distrito Federal", "Brasil", -15.79, -47.88, 11, "Brasília|Brazil"),
    ("São Paulo", "São Paulo", "Brasil", -23.55, -46.63, 10, "Sao Paulo|Brazil"),
    ("Río de Janeiro", "Río de Janeiro", "Brasil", -22.91, -43.17, 11, "Rio de Janeiro|Brazil"),
    ("Manaos", "Amazonas", "Brasil", -3.12, -60.02, 11, "Manaus|Brazil"),
    ("Ciudad de México", "Ciudad de México", "México", 19.43, -99.13, 10, "Mexico City|CDMX|Mexico"),
    ("Ciudad de Guatemala", "Guatemala", "Guatemala", 14.63, -90.51, 11, "Guatemala City"),
    ("San José", "San José", "Costa Rica", 9.93, -84.08, 11, "Costa Rica"),
    ("La Habana", "La Habana", "Cuba", 23.11, -82.37, 11, "Havana|Habana|Cuba"),
    ("Santo Domingo", "Distrito Nacional", "República Dominicana", 18.47, -69.89, 11, "Dominican Republic"),
    ("Nueva York", "Nueva York", "Estados Unidos", 40.71, -74.01, 11, "New York|NYC|United States|USA"),
    ("Los Ángeles", "California", "Estados Unidos", 34.05, -118.24, 10, "Los Angeles|United States|USA"),
    ("Houston", "Texas", "Estados Unidos", 29.76, -95.37, 10, "United States|USA"),
    ("Miami", "Florida", "Estados Unidos", 25.76, -80.19, 11, "United States|USA"),
    ("Washington D. C.", "Distrito de Columbia", "Estados Unidos", 38.90, -77.04, 11, "Washington DC|United States|USA"),
    ("Anchorage", "Alaska", "Estados Unidos", 61.22, -149.90, 10, "United States|USA"),
    ("Honolulu", "Hawái", "Estados Unidos", 21.31, -157.86, 11, "Hawaii|United States|USA"),
    ("Toronto", "Ontario", "Canadá", 43.65, -79.38, 10, "Canada"),
    ("Vancouver", "Columbia Británica", "Canadá", 49.28, -123.12, 11, "British Columbia|Canada"),
    ("Madrid", "Comunidad de Madrid", "España", 40.42, -3.70, 11, "Spain"),
    ("Barcelona", "Cataluña", "España", 41.39, 2.17, 11, "Catalonia|Spain"),
    ("Lisboa", "Lisboa", "Portugal", 38.72, -9.14, 11, "Lisbon"),
    ("París", "Isla de Francia", "Francia", 48.86, 2.35, 11, "Paris|Île-de-France|France"),
    ("Londres", "Inglaterra", "Reino Unido", 51.51, -0.13, 10, "London|England|United Kingdom|UK"),
    ("Dublín", "Leinster", "Irlanda", 53.35, -6.26, 11, "Dublin|Ireland"),
    ("Berlín", "Berlín", "Alemania", 52.52, 13.40, 10, "Berlin|Germany|Deutschland"),
    ("Ámsterdam", "Holanda Septentrional", "Países Bajos", 52.37, 4.90, 11, "Amsterdam|Netherlands"),
    ("Bruselas", "Bruselas", "Bélgica", 50.85, 4.35, 11, "Brussels|Bruxelles|Belgium"),
    ("Roma", "Lacio", "Italia", 41.90, 12.50, 11, "Rome|Italy"),
    ("Viena", "Viena", "Austria", 48.21, 16.37, 11, "Vienna|Wien"),
    ("Varsovia", "Mazovia", "Polonia", 52.23, 21.01, 11, "Warsaw|Warszawa|Poland"),
    ("Atenas", "Ática", "Grecia", 37.98, 23.73, 11, "Athens|Greece"),
    ("Estocolmo", "Estocolmo", "Suecia", 59.33, 18.07, 11, "Stockholm|Sweden"),
    ("Reikiavik", "Capital", "Islandia", 64.15, -21.94, 11, "Reykjavik|Iceland"),
    ("Moscú", "Moscú", "Rusia", 55.76, 37.62, 10, "Moscow|Moskva|Russia"),
    ("Estambul", "Estambul", "Turquía", 41.01, 28.98, 10, "Istanbul|Turkey|Türkiye"),
    ("El Cairo", "El Cairo", "Egipto", 30.04, 31.24, 10, "Cairo|Egypt"),
    ("Lagos", "Lagos", "Nigeria", 6.52, 3.38, 10, "Nigeria"),
    ("Acra", "Gran Acra", "Ghana", 5.60, -0.19, 11, "Accra|Ghana"),
    ("Dakar", "Dakar", "Senegal", 14.72, -17.47, 11, "Senegal"),
    ("Kinsasa", "Kinsasa", "República Democrática del Congo", -4.32, 15.31, 10, "Kinshasa|DR Congo|Congo"),
    ("Nairobi", "Nairobi", "Kenia", -1.29, 36.82, 11, "Kenya"),
    ("Adís Abeba", "Adís Abeba", "Etiopía", 9.03, 38.74, 11, "Addis Ababa|Ethiopia"),
    ("Johannesburgo", "Gauteng", "Sudáfrica", -26.20, 28.05, 10, "Johannesburg|South Africa"),
    ("Ciudad del Cabo", "Cabo Occidental", "Sudáfrica", -33.92, 18.42, 11, "Cape Town|South Africa"),
    ("Antananarivo", "Analamanga", "Madagascar", -18.88, 47.51, 11, "Madagascar"),
    ("Riad", "Riad", "Arabia Saudita", 24.71, 46.68, 10, "Riyadh|Saudi Arabia"),
    ("Dubái", "Dubái", "Emiratos Árabes Unidos", 25.20, 55.27, 10, "Dubai|United Arab Emirates|UAE"),
    ("Teherán", "Teherán", "Irán", 35.69, 51.39, 10, "Tehran|Iran"),
    ("Karachi", "Sindh", "Pakistán", 24.86, 67.01, 10, "Pakistan"),
    ("Nueva Delhi", "Delhi", "India", 28.61, 77.21, 10, "New Delhi|Delhi|India"),
    ("Bombay", "Maharashtra", "India", 19.08, 72.88, 10, "Mumbai|India"),
    ("Daca", "Daca", "Bangladés", 23.81, 90.41, 11, "Dhaka|Bangladesh"),
    ("Katmandú", "Bagmati", "Nepal", 27.72, 85.32, 11, "Kathmandu|Nepal"),
    ("Pekín", "Pekín", "China", 39.90, 116.40, 10, "Beijing|北京|China"),
    ("Shanghái", "Shanghái", "China", 31.23, 121.47, 10, "Shanghai|上海|China"),
    ("Hong Kong", "Hong Kong", "China", 22.32, 114.17, 11, "香港|China"),
    ("Seúl", "Seúl", "Corea del Sur", 37.57, 126.98, 10, "Seoul|서울|South Korea|Korea"),
    ("Tokio", "Tokio", "Japón", 35.68, 139.69, 10, "Tokyo|東京|Japan"),
    ("Osaka", "Osaka", "Japón", 34.69, 135.50, 11, "大阪|Japan"),
    ("Manila", "Gran Manila", "Filipinas", 14.60, 120.98, 11, "Philippines"),
    ("Bangkok", "Bangkok", "Tailandia", 13.76, 100.50, 10, "Krung Thep|Thailand"),
    ("Hanói", "Hanói", "Vietnam", 21.03, 105.85, 11, "Hanoi|Viet Nam|Vietnam"),
    ("Kuala Lumpur", "Kuala Lumpur", "Malasia", 3.14, 101.69, 11, "Malaysia"),
    ("Singapur", "Singapur", "Singapur", 1.35, 103.82, 11, "Singapore"),
    ("Yakarta", "Yakarta", "Indonesia", -6.21, 106.85, 10, "Jakarta|Indonesia"),
    ("Sídney", "Nueva Gales del Sur", "Australia", -33.87, 151.21, 10, "Sydney|New South Wales"),
    ("Melbourne", "Victoria", "Australia", -37.81, 144.96, 10, "Australia"),
    ("Perth", "Australia Occidental", "Australia", -31.95, 115.86, 10, "Western Australia"),
    ("Auckland", "Auckland", "Nueva Zelanda", -36.85, 174.76, 10, "New Zealand|Aotearoa"),
    ("Wellington", "Wellington", "Nueva Zelanda", -41.29, 174.78, 11, "New Zealand|Aotearoa"),
    ("Suva", "Central", "Fiyi", -18.14, 178.44, 11, "Fiji"),
    ("Nukualofa", "Tongatapu", "Tonga", -21.14, -175.20, 12, "Nuku'alofa|Tonga"),
))


def normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn")
    return " ".join(sin_tildes.lower().replace(",", " ").split())


def buscar_local(texto: str) -> list[Lugar]:
    """Coincidencias del catálogo. «Rionegro» devuelve los dos; «Rionegro, Antioquia», uno."""
    consulta = normalizar(texto)
    if len(consulta) < 2:
        return []
    palabras = consulta.split()
    puntuados = []
    for lugar in CATALOGO:
        nombre = normalizar(lugar.nombre)
        completo = normalizar(" ".join((lugar.etiqueta, *lugar.alias)))
        if not all(p in completo for p in palabras):
            continue
        # Primero el nombre exacto, luego el que empieza igual, luego el resto.
        nombres = [nombre, *(normalizar(a) for a in lugar.alias)]
        orden = 0 if any(consulta == n or consulta.startswith(n + " ") for n in nombres) else \
            1 if any(n.startswith(palabras[0]) for n in nombres) else 2
        puntuados.append((orden, lugar.etiqueta, lugar))
    return [l for _, _, l in sorted(puntuados)[:MAX_RESULTADOS]]


def proveedor() -> str | None:
    """URL del geocodificador en línea, o None si está desactivado. Sin variable: Nominatim público."""
    url = os.environ.get("VISOR_GEOCODIFICADOR_URL", "").strip().rstrip("/")
    if not url:
        return NOMINATIM
    if url.lower() in ("desactivado", "off", "no", "0"):
        return None
    return url if url.startswith("https://") or url.startswith("http://localhost") else None


_cache: dict[str, list[Lugar]] = {}
_ultima = [0.0]
_cerrojo = threading.Lock()     # una consulta a la vez en todo el proceso (todas las sesiones)


def _zoom(limites: list[float] | None) -> int:
    if not limites:
        return 11
    import math
    lado = max(abs(limites[1] - limites[0]), abs(limites[3] - limites[2]), 1e-4)
    return max(4, min(14, int(math.log2(360.0 / lado)) + 1))


def interpretar(respuesta: list) -> list[Lugar]:
    """Convierte una respuesta jsonv2 de tipo Nominatim. Descarta lo que no tenga coordenadas válidas."""
    lugares = []
    for item in respuesta if isinstance(respuesta, list) else []:
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        partes = [p.strip() for p in str(item.get("display_name", "")).split(",") if p.strip()]
        direccion = item.get("address") if isinstance(item.get("address"), dict) else {}
        nombre = str(item.get("name") or (partes[0] if partes else "")).strip()
        if not nombre:
            continue
        region = str(direccion.get("state") or direccion.get("region") or (partes[-2] if len(partes) > 2 else ""))
        pais = str(direccion.get("country") or (partes[-1] if len(partes) > 1 else ""))
        try:
            caja = [float(v) for v in item.get("boundingbox") or []]
        except (TypeError, ValueError):
            caja = []
        lugares.append(Lugar(nombre, region, pais, lat, lon, _zoom(caja if len(caja) == 4 else None), EN_LINEA))
    return lugares[:MAX_RESULTADOS]


def buscar_en_linea(texto: str, abrir=None) -> list[Lugar]:
    """Una consulta al proveedor configurado. `abrir` permite sustituir la red en las pruebas."""
    base = proveedor()
    if base is None:
        raise ErrorLugares("No hay un geocodificador en línea configurado.")
    consulta = normalizar(texto)
    if consulta in _cache:
        return _cache[consulta]
    parametros = {"q": texto.strip(), "format": "jsonv2", "limit": str(MAX_RESULTADOS), "addressdetails": "1",
                  "accept-language": "es"}
    clave = os.environ.get("VISOR_GEOCODIFICADOR_CLAVE", "").strip()
    if clave:
        parametros["key"] = clave
    destino = base if base.endswith("/search") else base + "/search"
    peticion = urllib.request.Request(destino + "?" + urllib.parse.urlencode(parametros),
                                      headers={"User-Agent": AGENTE, "Accept": "application/json"})
    try:
        with _cerrojo:      # ≤ 1 consulta por segundo en todo el proceso, como exige la política de Nominatim
            espera = ESPERA_MINIMA_S - (time.monotonic() - _ultima[0])
            if espera > 0 and abrir is None:
                time.sleep(espera)
            _ultima[0] = time.monotonic()
            with (abrir or urllib.request.urlopen)(peticion, timeout=TIEMPO_LIMITE_S) as r:
                datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        motivo = ("el servicio rechazó la clave" if e.code in (401, 403) else
                  "demasiadas consultas; espera un momento" if e.code == 429 else f"respondió con el error {e.code}")
        raise ErrorLugares(f"El geocodificador en línea no está disponible ({motivo}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErrorLugares("No se pudo conectar con el geocodificador en línea (sin red o tardó demasiado).") from None
    except ValueError:
        raise ErrorLugares("El geocodificador en línea devolvió una respuesta que no se entiende.") from None
    _cache[consulta] = interpretar(datos)
    return _cache[consulta]


def buscar(texto: str, abrir=None) -> tuple[list[Lugar], str, str | None]:
    """(lugares, fuente que respondió, aviso). Nunca inventa un lugar: sin coincidencias, lista vacía."""
    if len(normalizar(texto)) < 2:
        return [], LOCAL, "Escribe al menos dos letras del nombre del lugar."
    if proveedor() is not None:
        try:
            return buscar_en_linea(texto, abrir), EN_LINEA, None
        except ErrorLugares as e:
            return buscar_local(texto), LOCAL, f"{e} Se usó el catálogo local."
    return buscar_local(texto), LOCAL, None
