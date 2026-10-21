"""Normaliza OSM y cruza contra las fuentes oficiales (PBA, CABA)."""
import json, math, collections, sys

BASE = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "datos")
RANK = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4,
        "motorway_link": 5, "trunk_link": 5, "primary_link": 5, "unclassified": 6, "residential": 7}
AMBA = (-35.2, -59.3, -34.2, -57.7)  # sur, oeste, norte, este


def en_amba(c):
    return AMBA[0] <= c["lat"] <= AMBA[2] and AMBA[1] <= c["lon"] <= AMBA[3]


def dist(a, b):
    R = 6371000
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def num(v):
    try:
        return int(str(v).split(";")[0].split()[0])
    except Exception:
        return None


# --- OSM: nodo cámara seguido de las vías a <30 m ---
raw = json.load(open(f"{BASE}/osm_camaras_raw.json", encoding="utf-8"))["elements"]
osm, cur = [], None
for e in raw:
    if e["type"] == "node":
        t = e.get("tags", {})
        cur = {"lat": e["lat"], "lon": e["lon"], "maxspeed": num(t.get("maxspeed")),
               "direction": t.get("direction"), "road": None, "_rank": 99,
               "source": "osm", "osm_id": e["id"], "notes": None}
        osm.append(cur)
    elif e["type"] == "way" and cur:
        t = e.get("tags", {})
        r = RANK.get(t.get("highway"), 50)
        nombre = " / ".join(x for x in (t.get("ref"), t.get("name")) if x)
        if nombre and r < cur["_rank"]:
            cur["road"], cur["_rank"] = nombre, r
            if cur["maxspeed"] is None and num(t.get("maxspeed")):
                cur["notes"] = f"vel. de la vía: {t.get('maxspeed')}"
for c in osm:
    c.pop("_rank")
json.dump(osm, open(f"{BASE}/fuentes/osm.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)

pba = json.load(open(f"{BASE}/fuentes/pba_infraccionesba.json", encoding="utf-8"))
caba = json.load(open(f"{BASE}/fuentes/caba_camaras_fijas.json", encoding="utf-8"))
caba_cine = [c for c in caba if "Cinem" in (c.get("notes") or "")]

# dedupe PBA por coordenada (los dos sentidos suelen repetir punto)
seen, pba_u = {}, []
for c in pba:
    k = (round(c["lat"], 4), round(c["lon"], 4))
    if k not in seen:
        seen[k] = c
        pba_u.append(c)


def cruzar(fuente, contra, umbral=150):
    faltan, ok = [], 0
    for c in fuente:
        d = min((dist(c, o) for o in contra), default=1e9)
        if d <= umbral:
            ok += 1
        else:
            faltan.append({**c, "dist_osm_m": round(d)})
    return ok, faltan


osm_amba = [c for c in osm if en_amba(c)]
print("OSM total zona:", len(osm), "| AMBA:", len(osm_amba),
      "| con velocidad:", sum(1 for c in osm if c["maxspeed"]))
print("PBA registros:", len(pba), "| puntos únicos:", len(pba_u), "| en AMBA:", sum(1 for c in pba_u if en_amba(c)))
print("CABA total:", len(caba), "| cinemómetros:", len(caba_cine))

ok_p, falt_p = cruzar(pba_u, osm)
ok_c, falt_c = cruzar(caba_cine, osm)
print(f"PBA: {ok_p} ya en OSM, {len(falt_p)} faltan ({sum(1 for c in falt_p if en_amba(c))} en AMBA)")
print(f"CABA cinemómetros: {ok_c} ya en OSM, {len(falt_c)} faltan")

# OSM que no figura en ninguna oficial (sólo informativo, AMBA)
ofi = pba_u + caba
solo_osm = [c for c in osm_amba if min(dist(c, o) for o in ofi) > 150]
print("OSM AMBA sin respaldo oficial:", len(solo_osm))

# faltantes agrupados por vía
def grupo(lst):
    cnt = collections.Counter((c.get("road") or "?").strip().upper() for c in lst)
    return cnt.most_common(40)

print("\nFaltan de PBA por vía:")
for k, v in grupo(falt_p):
    print(f"  {v:3d}  {k}")
print("\nFaltan de CABA (cinemómetros):")
for c in falt_c:
    print("  ", c["road"])

json.dump({"pba_faltan": falt_p, "caba_faltan": falt_c, "osm_sin_respaldo_amba": solo_osm},
          open(f"{BASE}/cruce_faltantes.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
