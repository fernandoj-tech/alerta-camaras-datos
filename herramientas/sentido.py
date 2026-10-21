"""Calcula hacia dónde va el tránsito que controla cada cámara (rumbo en grados) y lo agrega a las fuentes
(campo "rumbo": grados, o null si no se sabe o controla los dos sentidos).

- Provincia (InfraccionesBA) y ANSV: "ascendente"/"descendente", tomando ascendente = hacia donde crece el km.
  Queda en "rumbo_oficial" y NO se usa para filtrar: la validación del 21/10/2026 dio 50 coinciden / 51 al revés
  contra las calzadas de una mano (los puntos oficiales no están sobre la calzada que controlan, o la convención
  cambia). Se puede activar el día que se valide.
  El km se ubica con los postes kilométricos de Vialidad Nacional (rutas nacionales) y los mojones de
  OpenStreetMap (nacionales y provinciales): se toman los dos más cercanos de la misma ruta.
- OpenStreetMap: sólo lo confiable. Relaciones type=enforcement (from → to) y cámaras sobre vías de una mano.
  El `direction` en grados NO se usa: según la wiki es hacia dónde mira la cámara, y los editores lo cargan de
  las dos formas (en calles de una mano coincide con el tránsito 101 veces y con la cámara 41; 21/10/2026).
- Validación: en calzadas de una mano (autopistas y rutas con calzadas separadas) compara el rumbo calculado con
  la mano de la calzada más cercana a la cámara, e informa cuántas coinciden.

Necesita datos/fuentes/originales/postes_km_rn.geojson (lo baja actualizar_base.py) y consulta Overpass.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATOS = Path(__file__).resolve().parent.parent / "datos"
FUENTES = DATOS / "fuentes"
ARGENTINA = (-55.2, -73.7, -21.7, -53.5)
SERVIDORES = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]


# ─── geometría ───────────────────────────────────────────────────

def distancia(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def rumbo(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def dif(a, b):
    return abs((a - b + 180) % 360 - 180)


def distancia_a_tramo(p, a, b):
    """Metros aproximados del punto p al segmento a-b."""
    k = math.cos(math.radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], p[1] * k, p[0]
    dx, dy = bx - ax, by - ay
    t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) * 111_320


# ─── Overpass ────────────────────────────────────────────────────

def overpass(q: str) -> list:
    ultimo = None
    for intento in range(3):
        for servidor in SERVIDORES:
            try:
                req = urllib.request.Request(servidor, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": "alerta-camaras/0.9 (uso personal)"})
                return json.load(urllib.request.urlopen(req, timeout=300))["elements"]
            except Exception as e:  # noqa: BLE001
                ultimo = e
        time.sleep(30 * (intento + 1))
    raise RuntimeError(f"Overpass no respondió: {ultimo}")


def cache(nombre: str, consulta: str) -> list:
    """Consulta Overpass y guarda la respuesta; si Overpass falla, usa la última guardada."""
    archivo = DATOS / nombre
    try:
        elementos = overpass(consulta)
        archivo.write_text(json.dumps({"elements": elementos}), encoding="utf-8")
        return elementos
    except Exception as e:  # noqa: BLE001
        if archivo.exists():
            print(f"  aviso: {nombre} sin actualizar ({e})")
            return json.loads(archivo.read_text(encoding="utf-8"))["elements"]
        raise


# ─── rutas y kilómetros ──────────────────────────────────────────

def ruta_de(texto: str | None) -> str | None:
    """'RUTA NACIONAL 7', 'RN 3 km 54', 'Ruta Provincial 6', 'RP 41' → 'RN7', 'RN3', 'RP6', 'RP41'."""
    if not texto:
        return None
    t = texto.upper()
    m = re.search(r"\b(?:RN|R\.N\.|RUTA NACIONAL|NACIONAL)\s*(?:N[°º.]?\s*)?(\d+)", t)
    if m:
        return f"RN{int(m.group(1))}"
    m = re.search(r"\b(?:RP|R\.P\.|RUTA PROVINCIAL|PROVINCIAL)\s*(?:N[°º.]?\s*)?(\d+)", t)
    if m:
        return f"RP{int(m.group(1))}"
    return None


def refs_de(ref: str | None) -> set[str]:
    """El ref de una vía de OSM ('RN 9', 'RP 2;RN 3') → {'RN9'} / {'RP2', 'RN3'}."""
    salida = set()
    for parte in (ref or "").split(";"):
        m = re.fullmatch(r"(RN|RP)\s*(\d+)", parte.strip().upper())
        r = f"{m.group(1)}{int(m.group(2))}" if m else ruta_de(parte)
        if r:
            salida.add(r)
    return salida


def puntos_km() -> dict[str, list]:
    """{ruta: [(lat, lon, km), ...]} con postes de Vialidad Nacional y mojones de OSM."""
    puntos: dict[str, list] = {}
    postes = FUENTES / "originales" / "postes_km_rn.geojson"
    if postes.exists():
        for f in json.loads(postes.read_text(encoding="utf-8"))["features"]:
            p = f["properties"]
            if not str(p.get("cod_ruta", "")).isdigit():
                continue
            try:
                puntos.setdefault(f"RN{int(p['cod_ruta'])}", []).append(
                    (float(p["latitud"]), float(p["longitud"]), float(p["progresiva"])))
            except (TypeError, ValueError, KeyError):
                continue
    s, o, n, e = ARGENTINA
    elementos = cache("osm_mojones_raw.json",
                      f'[out:json][timeout:280];node["highway"="milestone"]["distance"]({s},{o},{n},{e})->.m;'
                      f'foreach.m->.x{{.x out tags center;way(around.x:25)[highway][ref];out tags;}}')
    actual = None
    for el in elementos:
        if el["type"] == "node":
            try:
                km = float(el["tags"]["distance"].replace(",", ".").split()[0])
            except (KeyError, ValueError):
                actual = None
                continue
            actual = {"p": (el["lat"], el["lon"]), "km": km, "rutas": refs_de(el["tags"].get("ref"))}
            continue
        if el["type"] == "way" and actual:
            if not actual["rutas"]:
                actual["rutas"] |= refs_de(el.get("tags", {}).get("ref"))
            for r in actual["rutas"]:
                puntos.setdefault(r, []).append((*actual["p"], actual["km"]))
            actual["rutas"] = set()  # ya se cargó: no repetir con las vías siguientes
    return puntos


def rumbo_ascendente(ruta: str, p, puntos: dict) -> float | None:
    """Rumbo hacia donde crece el km de la ruta, cerca de p (los dos postes/mojones más cercanos, coherentes)."""
    cercanos = sorted((distancia(p, (la, lo)), la, lo, km) for la, lo, km in puntos.get(ruta, ())
                      if abs(la - p[0]) < 0.06 and abs(lo - p[1]) < 0.07)
    cercanos = [c for c in cercanos if c[0] < 6000]
    for i, a in enumerate(cercanos[:6]):
        for b in cercanos[i + 1:8]:
            dkm = abs(a[3] - b[3])
            if dkm < 0.3 or dkm > 6:
                continue
            geo = distancia((a[1], a[2]), (b[1], b[2])) / 1000
            if abs(geo - dkm) > 0.5 * dkm + 0.3:
                continue  # poste mal ubicado o de otra ruta
            bajo, alto = (a, b) if a[3] < b[3] else (b, a)
            return rumbo((bajo[1], bajo[2]), (alto[1], alto[2]))
    return None


# ─── calzadas de una mano (validación) ───────────────────────────

def manos_cercanas(registros: list) -> dict[int, float]:
    """{índice: rumbo de la calzada de una mano más cercana (≤ 25 m)} para cada registro."""
    consulta = "[out:json][timeout:280];" + "".join(
        f'make m i={i};out;way(around:25,{r["lat"]},{r["lon"]})[highway~"^(motorway|trunk|primary|secondary)$"]'
        f'[oneway~"^(yes|1|-1)$"];out tags geom;' for i, r in enumerate(registros))
    elementos = cache("osm_calzadas_raw.json", consulta)
    mejor: dict[int, tuple] = {}
    actual = None
    for el in elementos:
        if el["type"] == "m":
            actual = int(el["tags"]["i"])
            continue
        g = [(x["lat"], x["lon"]) for x in el.get("geometry", [])]
        if actual is None or len(g) < 2:
            continue
        p = (registros[actual]["lat"], registros[actual]["lon"])
        d, a, b = min((distancia_a_tramo(p, a, b), a, b) for a, b in zip(g, g[1:]))
        r = rumbo(a, b) if el["tags"].get("oneway") != "-1" else rumbo(b, a)
        if actual not in mejor or d < mejor[actual][0]:
            mejor[actual] = (d, r)
    return {i: r for i, (d, r) in mejor.items()}


# ─── OSM confiable ───────────────────────────────────────────────

def sentidos_osm() -> dict[int, float]:
    """{id de nodo OSM: rumbo} de relaciones enforcement (from → to) y de cámaras sobre vías de una mano."""
    s, o, n, e = ARGENTINA
    salida: dict[int, float] = {}
    rel = cache("osm_enforcement_raw.json",
                f'[out:json][timeout:200];relation["type"="enforcement"]["enforcement"~"maxspeed|average_speed"]'
                f'({s},{o},{n},{e});out body;>;out skel qt;')
    nodos = {x["id"]: (x["lat"], x["lon"]) for x in rel if x["type"] == "node"}
    for r in (x for x in rel if x["type"] == "relation"):
        roles = {m["role"]: m["ref"] for m in r["members"] if m["type"] == "node"}
        if "device" in roles and "from" in roles and roles["from"] in nodos:
            destino = nodos.get(roles.get("to", roles["device"]))
            if destino and destino != nodos[roles["from"]]:
                salida[roles["device"]] = rumbo(nodos[roles["from"]], destino)
    manos = cache("osm_camaras_mano_raw.json",
                  f'[out:json][timeout:250];node["highway"="speed_camera"]({s},{o},{n},{e})->.c;'
                  f'foreach.c->.x{{.x out ids center;way(bn.x)[highway][oneway~"^(yes|1|-1)$"];out tags geom;}}')
    actual = None
    for el in manos:
        if el["type"] == "node":
            actual = el
            continue
        g = [(x["lat"], x["lon"]) for x in el.get("geometry", [])]
        if actual is None or len(g) < 2 or actual["id"] in salida:
            continue
        p = (actual["lat"], actual["lon"])
        d, a, b = min((distancia_a_tramo(p, a, b), a, b) for a, b in zip(g, g[1:]))
        salida[actual["id"]] = rumbo(a, b) if el["tags"].get("oneway") != "-1" else rumbo(b, a)
    return salida


# ─── principal ───────────────────────────────────────────────────

def main():
    puntos = puntos_km()
    oficiales = []
    for nombre in ("pba_infraccionesba.json", "ansv_radares_fijos.json"):
        archivo = FUENTES / nombre
        if archivo.exists():
            oficiales += [(archivo, r) for r in json.loads(archivo.read_text(encoding="utf-8"))]
    registros = [r for _, r in oficiales]
    manos = manos_cercanas(registros)

    resueltos = coinciden = opuestos = 0
    for i, r in enumerate(registros):
        r["rumbo"] = None
        r["rumbo_oficial"] = None
        sentido = re.search(r"sentido:?\s*(\w+)", r.get("notes") or "", re.I)
        ruta = ruta_de(r.get("road"))
        if not sentido or not ruta:
            continue
        asc = rumbo_ascendente(ruta, (r["lat"], r["lon"]), puntos)
        if asc is None:
            continue
        r["rumbo_oficial"] = round(asc if sentido.group(1).lower().startswith("asc") else (asc + 180) % 360)
        resueltos += 1
        if i in manos:
            if dif(r["rumbo_oficial"], manos[i]) < 60:
                coinciden += 1
            elif dif(r["rumbo_oficial"], manos[i]) > 120:
                opuestos += 1
    for archivo in {a for a, _ in oficiales}:
        filas = [r for a, r in oficiales if a == archivo]
        archivo.write_text(json.dumps(filas, ensure_ascii=False, indent=0), encoding="utf-8")

    osm = sentidos_osm()
    archivo_osm = FUENTES / "osm.json"
    if archivo_osm.exists():
        filas = json.loads(archivo_osm.read_text(encoding="utf-8"))
        for f in filas:
            f["rumbo"] = round(osm[f["osm_id"]]) if f.get("osm_id") in osm else None
        archivo_osm.write_text(json.dumps(filas, ensure_ascii=False, indent=0), encoding="utf-8")

    print(f"sentido: {resueltos} de {len(registros)} oficiales (en calzadas de una mano: {coinciden} coinciden, "
          f"{opuestos} al revés) · OSM confiable: {len(osm)}")


if __name__ == "__main__":
    main()
