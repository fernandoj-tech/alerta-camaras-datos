"""Arma datos/semaforos.json: cámaras de semáforo (luz roja) de la Ciudad y de OpenStreetMap.

Fuentes:
- CABA BA Data: tipo "Analítica de video" (cámaras en cruces: semáforo y otras infracciones).
- OSM: relaciones type=enforcement + enforcement=traffic_signals (con sentido controlado: from → to),
  nodos con enforcement=traffic_signals y nodos highway=speed_camera cuya descripción dice luz roja / semáforo
  (están mal cargados como radar de velocidad: la app no los usa como velocidad).
Requiere datos/osm_semaforos_raw.json (Overpass, ver CLAUDE.md) y datos/osm_camaras_raw.json.
"""
import json, math, re
from pathlib import Path

DATOS = Path(__file__).resolve().parent.parent / "datos"
ROJO = re.compile(r"luz roja|sem[aá]foro|en rojo", re.I)
VELOCIDAD = re.compile(r"velocidad|cinem", re.I)


def dist(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def rumbo(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lon"] - a["lon"])
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360)


lista = []

# 1) OSM: relaciones con sentido
raw = json.loads((DATOS / "osm_semaforos_raw.json").read_text(encoding="utf-8"))["elements"]
nodos = {e["id"]: e for e in raw if e["type"] == "node"}
usados = set()
for r in (e for e in raw if e["type"] == "relation"):
    rol = {m["role"]: nodos.get(m["ref"]) for m in r["members"] if m["type"] == "node"}
    dev = rol.get("device")
    if not dev:
        continue
    usados.add(dev["id"])
    sentido = None
    if rol.get("from") and rol.get("to"):
        sentido = rumbo(rol["from"], rol["to"])
    lista.append({"lat": dev["lat"], "lon": dev["lon"], "rumbo": sentido,
                  "nombre": r.get("tags", {}).get("name"), "fuente": "osm_relacion"})

# 2) OSM: nodos sueltos con enforcement=traffic_signals
for n in nodos.values():
    t = n.get("tags", {})
    if n["id"] in usados or t.get("enforcement") not in ("traffic_signals", "red_light"):
        continue
    lista.append({"lat": n["lat"], "lon": n["lon"], "rumbo": None, "nombre": t.get("name") or t.get("description"),
                  "fuente": "osm_nodo"})

# 3) OSM: radares de velocidad que en realidad son de luz roja
reclasificadas = 0
for e in json.loads((DATOS / "osm_camaras_raw.json").read_text(encoding="utf-8"))["elements"]:
    if e["type"] != "node":
        continue
    t = e.get("tags", {})
    texto = " ".join(str(t.get(k, "")) for k in ("description", "name", "note"))
    if ROJO.search(texto) and not VELOCIDAD.search(texto):
        reclasificadas += 1
        lista.append({"lat": e["lat"], "lon": e["lon"], "rumbo": None, "nombre": texto.strip(),
                      "fuente": "osm_radar_de_luz_roja", "osm_id": e["id"]})

# 4) CABA: analítica de video
for c in json.loads((DATOS / "fuentes" / "caba_camaras_fijas.json").read_text(encoding="utf-8")):
    if "Anal" in (c.get("notes") or ""):
        lista.append({"lat": c["lat"], "lon": c["lon"], "rumbo": None, "nombre": c.get("road"), "fuente": "caba"})

# Deduplicar a 40 m: gana la que trae sentido
lista.sort(key=lambda s: s["rumbo"] is None)
final = []
for s in lista:
    igual = next((f for f in final if dist(f, s) <= 40 and (f["rumbo"] is None or s["rumbo"] is None
                                                             or abs((f["rumbo"] - s["rumbo"] + 180) % 360 - 180) < 45)), None)
    if igual:
        igual["fuentes"] = sorted(set(igual["fuentes"]) | {s["fuente"]})
        if s.get("osm_id"):
            igual.setdefault("osm_ids", []).append(s["osm_id"])
        continue
    s["fuentes"] = [s.pop("fuente")]
    if s.get("osm_id"):
        s["osm_ids"] = [s.pop("osm_id")]
    final.append(s)

for i, s in enumerate(final):
    s["id"] = 100_000 + i + 1
(DATOS / "semaforos.json").write_text(json.dumps(final, ensure_ascii=False, indent=0), encoding="utf-8")
con_sentido = sum(1 for s in final if s["rumbo"] is not None)
print(f"semáforos: {len(final)} (con sentido: {con_sentido}) · radares OSM reclasificados como luz roja: {reclasificadas}")
from collections import Counter
print(Counter("+".join(s["fuentes"]) for s in final).most_common())
