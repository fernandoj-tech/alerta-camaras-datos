"""Exporta las bases al formato compacto que lee la app, en publicar/ (lo que baja la app cada semana) y,
si está el proyecto de la app al lado, también en sus assets.

- camaras.json:   [[id, lat, lon, vmax, rumbo], ...]  cámaras de velocidad con máxima; rumbo = sentido que controla
  en grados, -1 si no se sabe o si controla las dos manos (las fuentes dan sentidos opuestos).
  Se excluyen los "radares" que en OSM dicen ser de luz roja (sólo si ninguna fuente oficial los da de velocidad).
- assets/semaforos.json: [[id, lat, lon, rumbo], ...]  rumbo = sentido controlado en grados, -1 si no se sabe.
"""
import json, math, re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"
ASSETS = RAIZ / "app-android" / "app" / "src" / "main" / "assets"
PUBLICAR = RAIZ / "publicar"
DESTINOS = [PUBLICAR] + ([ASSETS] if ASSETS.exists() else [])
ROJO = re.compile(r"luz roja|sem[aá]foro|en rojo", re.I)
VELOCIDAD = re.compile(r"velocidad|cinem", re.I)


def rumbo_final(rumbos: list) -> int:
    """Un sentido si todos coinciden (a menos de 60°); si hay opuestos o no hay dato, -1 (las dos manos)."""
    if not rumbos:
        return -1
    base = rumbos[0]
    if any(abs((r - base + 180) % 360 - 180) > 60 for r in rumbos):
        return -1
    x = sum(math.cos(math.radians(r)) for r in rumbos)
    y = sum(math.sin(math.radians(r)) for r in rumbos)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360)


def dist(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


luz_roja = []
for e in json.loads((DATOS / "osm_camaras_raw.json").read_text(encoding="utf-8"))["elements"]:
    if e["type"] != "node":
        continue
    t = e.get("tags", {})
    texto = " ".join(str(t.get(k, "")) for k in ("description", "name", "note"))
    if ROJO.search(texto) and not VELOCIDAD.search(texto):
        luz_roja.append((e["lat"], e["lon"]))

camaras = json.loads((DATOS / "camaras.json").read_text(encoding="utf-8"))
filas, excluidas = [], 0
for c in camaras:
    if not c.get("maxspeed"):
        continue
    if c["fuentes"] == ["osm"] and any(dist((c["lat"], c["lon"]), p) <= 3 for p in luz_roja):
        excluidas += 1
        continue
    filas.append([c["id"], round(c["lat"], 6), round(c["lon"], 6), int(c["maxspeed"]),
                  -1 if c.get("dos_manos") else rumbo_final(c.get("rumbos", []))])
PUBLICAR.mkdir(exist_ok=True)
for d in DESTINOS:
    (d / "camaras.json").write_text(json.dumps(filas, separators=(",", ":")), encoding="utf-8")

semaforos = json.loads((DATOS / "semaforos.json").read_text(encoding="utf-8"))
sem = [[s["id"], round(s["lat"], 6), round(s["lon"], 6), s["rumbo"] if s["rumbo"] is not None else -1] for s in semaforos]
for d in DESTINOS:
    (d / "semaforos.json").write_text(json.dumps(sem, separators=(",", ":")), encoding="utf-8")

con_sentido = sum(1 for f in filas if f[4] >= 0)
print(f"velocidad: {len(filas)} ({con_sentido} con sentido; excluidas por ser de luz roja: {excluidas}) · semáforos: {len(sem)}")
