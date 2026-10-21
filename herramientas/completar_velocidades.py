"""Completa la máxima de las cámaras sin dato con la velocidad de la vía en OSM (consulta Overpass).

Overpass a veces responde 502/504 cuando está cargado: se reintenta y se prueba otro servidor.
"""
import json, time, urllib.parse, urllib.request

BASE = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "datos")
RANK = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4}
SERVIDORES = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]


def overpass(q: str) -> list:
    ultimo = None
    for intento in range(3):
        for servidor in SERVIDORES:
            try:
                req = urllib.request.Request(servidor, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": "alerta-camaras/0.6 (uso personal)"})
                return json.load(urllib.request.urlopen(req, timeout=280))["elements"]
            except Exception as e:  # noqa: BLE001
                ultimo = e
        time.sleep(30 * (intento + 1))
    raise RuntimeError(f"Overpass no respondió después de varios intentos: {ultimo}")


camaras = json.load(open(f"{BASE}/camaras.json", encoding="utf-8"))
sin = [c for c in camaras if not c["maxspeed"]]
q = "[out:json][timeout:200];" + "".join(
    f'make m id={c["id"]};out;way(around:30,{c["lat"]},{c["lon"]})[highway][maxspeed];out tags;' for c in sin)
raw = overpass(q) if sin else []

vel, cur = {}, None
for e in raw:
    if e["type"] == "m":
        cur = int(e["tags"]["id"])
        vel[cur] = None
        continue
    t = e.get("tags", {})
    try:
        v = int(t["maxspeed"].split()[0])
    except (KeyError, ValueError):
        continue
    r = RANK.get(t.get("highway"), 9)
    if vel[cur] is None or r < vel[cur][1]:
        vel[cur] = (v, r, t.get("ref") or t.get("name"))

n = 0
for c in camaras:
    if not c["maxspeed"] and vel.get(c["id"]):
        c["maxspeed"], c["maxspeed_origen"] = vel[c["id"]][0], "velocidad de la vía en OSM"
        c["road"] = c["road"] or vel[c["id"]][2]
        n += 1
json.dump(camaras, open(f"{BASE}/camaras.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print("completadas", n, "| siguen sin velocidad", sum(1 for c in camaras if not c["maxspeed"]))
