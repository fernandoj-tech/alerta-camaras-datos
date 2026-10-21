"""Actualiza las bases de cámaras desde las fuentes públicas, de punta a punta.

    python -I herramientas/actualizar_base.py

1. Baja cada fuente (si una falla, se queda con la última versión buena de esa fuente):
   - OpenStreetMap (Overpass): cámaras de velocidad con la vía donde están, y cámaras de semáforo.
   - Provincia de Buenos Aires: InfraccionesBA, equipos fijos de constatación (con velocidad).
   - Ciudad de Buenos Aires: BA Data, cámaras fijas de control vehicular.
   - ANSV: planilla pública de radares fijos autorizados en rutas nacionales (la que alimenta su mapa).
2. Arma `datos/camaras.json` y `datos/semaforos.json` (cruce.py → unir.py → completar_velocidades.py →
   semaforos.py) y los exporta a la app (exportar_app.py).
3. Deja en `publicar/` lo que baja la app cuando se actualiza sola: camaras.json, semaforos.json y version.json.
   Si la base nueva tiene mucho menos que la publicada (menos del 85 %), no se publica.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"
FUENTES = DATOS / "fuentes"
ORIGINALES = FUENTES / "originales"
PUBLICAR = RAIZ / "publicar"

UA = {"User-Agent": "alerta-camaras/0.6 (uso personal; datos publicos)"}
ZONA = (-41.1, -63.5, -32.8, -56.6)     # provincia de Buenos Aires + Rosario (sur, oeste, norte, este)
AMBA = (-35.2, -59.3, -34.2, -57.7)
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
URL_PBA = "https://infraccionesba.gba.gob.ar/equiposDeConstatacion"
URL_CABA = ("https://cdn.buenosaires.gob.ar/datosabiertos/datasets/transporte-y-obras-publicas/"
            "camaras-fijas-control-vehicular/camaras-fijas-de-control-vehicular.csv")
URL_ANSV = ("https://docs.google.com/spreadsheets/d/1qKy9Ok4BSOkuFpmeTvLMsre6ZkHGZRY7aYwmnUbpTwE/"
            "gviz/tq?tqx=out:csv&sheet=fijo")


def bajar(url: str, datos: bytes | None = None, timeout: int = 300) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, data=datos, headers=UA), timeout=timeout) as r:
        return r.read()


def overpass(q: str) -> bytes:
    ultimo: Exception | None = None
    for servidor in OVERPASS:
        try:
            crudo = bajar(servidor, urllib.parse.urlencode({"data": q}).encode())
            json.loads(crudo)  # que sea JSON y no una página de error
            return crudo
        except Exception as e:  # noqa: BLE001
            ultimo = e
    raise RuntimeError(f"Overpass no respondió: {ultimo}")


def en_zona(lat: float, lon: float) -> bool:
    s, o, n, e = ZONA
    return s <= lat <= n and o <= lon <= e


def guardar(nombre: str, filas: list, minimo: int):
    if len(filas) < minimo:
        raise RuntimeError(f"vinieron {len(filas)} registros (se esperaban al menos {minimo}); no se pisa la base")
    (FUENTES / nombre).write_text(json.dumps(filas, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(filas)


# ─── fuentes ─────────────────────────────────────────────────────

def fuente_osm() -> str:
    s, o, n, e = ZONA
    vias = "motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|unclassified|residential"
    q = (f'[out:json][timeout:280];node["highway"="speed_camera"]({s},{o},{n},{e})->.c;'
         f'foreach.c->.n{{.n out body;way(around.n:30)[highway~"^({vias})$"];out tags;}}')
    crudo = overpass(q)
    camaras = sum(1 for x in json.loads(crudo)["elements"] if x["type"] == "node")
    if camaras < 500:
        raise RuntimeError(f"OSM trajo {camaras} cámaras; no se pisa la base")
    (DATOS / "osm_camaras_raw.json").write_bytes(crudo)
    s, o, n, e = AMBA
    q = (f'[out:json][timeout:180];(relation["type"="enforcement"]["enforcement"~"traffic_signals|red_light"]'
         f'({s},{o},{n},{e});node["enforcement"~"traffic_signals|red_light"]({s},{o},{n},{e}););out body;>;out skel qt;')
    (DATOS / "osm_semaforos_raw.json").write_bytes(overpass(q))
    return f"{camaras} cámaras de velocidad"


def fuente_pba() -> str:
    html = bajar(URL_PBA).decode("utf-8", "ignore")
    (ORIGINALES / "pba_equipos.html").write_text(html, encoding="utf-8")
    filas = []
    for m in re.finditer(r"receivedArr\.push\(\{(.*?)\}\)", html, flags=re.S):
        d = dict(re.findall(r'(\w+):\s*"([^"]*)"', re.sub(r"//[^\n]*", "", m.group(1))))
        try:
            lat, lon = float(d["latitud"]), float(d["longitud"])
        except (KeyError, ValueError):
            continue
        try:
            vmax = int(float(d.get("velocidadPermitida", "")))
        except ValueError:
            vmax = None
        filas.append({"lat": lat, "lon": lon, "maxspeed": vmax, "direction": None, "road": d.get("calleRuta") or None,
                      "source": "pba_infraccionesba",
                      "notes": f"sentido: {d.get('sentido')}; serie: {d.get('nroSerie')}"})
    return f"{guardar('pba_infraccionesba.json', filas, 300)} equipos"


def fuente_caba() -> str:
    crudo = bajar(URL_CABA)
    (ORIGINALES / "caba_camaras_fijas.csv").write_bytes(crudo)
    texto = crudo.decode("utf-8") if crudo.startswith(b"\xef\xbb\xbf") else crudo.decode("cp1252", "replace")
    filas = []
    for r in list(csv.reader(io.StringIO(texto.lstrip("﻿")), delimiter=";"))[1:]:
        if len(r) < 4:
            continue
        try:
            lat, lon = float(r[2].replace(",", ".")), float(r[3].replace(",", "."))
        except ValueError:
            continue
        filas.append({"lat": lat, "lon": lon, "maxspeed": None, "direction": None, "road": r[1],
                      "source": "caba_camaras_fijas",
                      "notes": "tipo: " + r[0].replace("\xa0", " ") + "; dataset BA Data"})
    return f"{guardar('caba_camaras_fijas.json', filas, 150)} cámaras"


def fuente_ansv() -> str:
    texto = bajar(URL_ANSV).decode("utf-8")
    (ORIGINALES / "ansv_radares_fijos.csv").write_text(texto, encoding="utf-8")
    filas_csv = list(csv.reader(io.StringIO(texto)))
    encabezado = [h.split()[0].lower() if h.strip() else "" for h in filas_csv[0]]
    filas = []
    for fila in filas_csv[1:]:
        d = dict(zip(encabezado, fila))
        try:
            lat, lon = float(d["latitud"]), float(d["longitud"])
        except (KeyError, ValueError):
            continue
        if not en_zona(lat, lon):
            continue
        ruta = d.get("ruta", "") + (f" km {d['km']}" if d.get("km") else "")
        filas.append({"lat": lat, "lon": lon, "maxspeed": None, "direction": None, "road": ruta or None,
                      "source": "ansv_radares_fijos",
                      "notes": f"{d.get('municipio', '')}; sentido {d.get('sentido', '').lower()}; serie {d.get('serie', '')}"})
    return f"{guardar('ansv_radares_fijos.json', filas, 50)} radares en la zona"


# ─── armado ──────────────────────────────────────────────────────

def correr(script: str):
    r = subprocess.run([sys.executable, "-I", "-X", "utf8", str(RAIZ / "herramientas" / script)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"{script} falló:\n{r.stderr[-1500:]}")
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # la consola de Windows no imprime todo
    ORIGINALES.mkdir(parents=True, exist_ok=True)
    resumen = {}
    for nombre, paso in (("OpenStreetMap", fuente_osm), ("Provincia", fuente_pba), ("Ciudad", fuente_caba),
                         ("ANSV", fuente_ansv)):
        try:
            resumen[nombre] = paso()
        except Exception as e:  # noqa: BLE001
            resumen[nombre] = f"FALLÓ, se usa la versión anterior ({e})"
        print(f"  {nombre}: {resumen[nombre]}", flush=True)

    # Lo que estaba publicado: si la base nueva cae mucho, algo salió mal y no se publica
    anterior = {}
    if (PUBLICAR / "version.json").exists():
        anterior = json.loads((PUBLICAR / "version.json").read_text(encoding="utf-8"))
    respaldo = {f: (PUBLICAR / f).read_bytes() for f in ("camaras.json", "semaforos.json") if (PUBLICAR / f).exists()}

    for script in ("cruce.py", "unir.py", "completar_velocidades.py", "semaforos.py", "exportar_app.py"):
        print(f"  {script}: {correr(script)}", flush=True)

    velocidad = len(json.loads((PUBLICAR / "camaras.json").read_text(encoding="utf-8")))
    semaforos = len(json.loads((PUBLICAR / "semaforos.json").read_text(encoding="utf-8")))
    if anterior and (velocidad < 0.85 * anterior.get("velocidad", 0) or semaforos < 0.85 * anterior.get("semaforos", 0)):
        for f, contenido in respaldo.items():
            (PUBLICAR / f).write_bytes(contenido)
        raise SystemExit(f"La base nueva cae mucho ({velocidad} velocidad, {semaforos} semáforos contra "
                         f"{anterior.get('velocidad')} y {anterior.get('semaforos')}): se deja la anterior")
    # "fecha" cambia sólo si cambiaron las cámaras (la app baja la base cuando cambia la fecha);
    # "revisado" cambia siempre: deja constancia de cada revisión (y mantiene activo el repo de datos)
    hoy = datetime.date.today().isoformat()
    sin_cambios = bool(anterior) and all(respaldo.get(f) == (PUBLICAR / f).read_bytes()
                                         for f in ("camaras.json", "semaforos.json"))
    version = {"fecha": anterior["fecha"] if sin_cambios else hoy, "revisado": hoy, "velocidad": velocidad,
               "semaforos": semaforos, "fuentes": resumen}
    (PUBLICAR / "version.json").write_text(json.dumps(version, ensure_ascii=False, indent=1), encoding="utf-8")
    estado = "sin cambios" if sin_cambios else "base nueva"
    print(f"Listo ({estado}): {velocidad} cámaras de velocidad y {semaforos} de semáforo ({version['fecha']})")


if __name__ == "__main__":
    main()
