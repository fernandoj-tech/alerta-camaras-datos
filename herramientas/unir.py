"""Une OSM + PBA + CABA (cinemómetros) en una sola base y muestra cobertura por corredor."""
import json, math, re, collections
from pathlib import Path

BASE = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "datos")
AMBA = (-35.2, -59.3, -34.2, -57.7)


def dist(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def cargar(n):
    return json.load(open(f"{BASE}/fuentes/{n}.json", encoding="utf-8"))


pba = cargar("pba_infraccionesba")
osm = cargar("osm")
caba = [c for c in cargar("caba_camaras_fijas") if "Cinem" in (c.get("notes") or "")]
ansv = cargar("ansv_radares_fijos") if (Path(BASE) / "fuentes" / "ansv_radares_fijos.json").exists() else []

base = []
PRIOR = {"pba": 0, "osm": 1, "ansv": 2, "caba": 3}


def manos_oficiales(c, fuente) -> set:
    """{'asc'} / {'desc'} según el listado oficial (Provincia, ANSV): si en un lugar están las dos, controla las dos."""
    if fuente not in ("pba", "ansv"):
        return set()
    m = re.search(r"sentido:?\s*(\w+)", c.get("notes") or "", re.I)
    if not m:
        return set()
    return {"asc"} if m.group(1).lower().startswith("asc") else {"desc"}


def sumar(c, fuente):
    for b in base:
        if dist(b, c) <= 60:
            b["fuentes"].add(fuente)
            if c.get("maxspeed") and (b["maxspeed"] is None or PRIOR[fuente] < b["_pv"]):
                if b["maxspeed"] and b["maxspeed"] != c["maxspeed"]:
                    b["conflicto"] = f"{b['maxspeed']} vs {c['maxspeed']}"
                b["maxspeed"], b["_pv"] = c["maxspeed"], PRIOR[fuente]
            if fuente == "pba" and c.get("road"):
                b["road"] = c["road"]
            if c.get("rumbo") is not None:
                b["rumbos"].append(c["rumbo"])
            b["manos"] |= manos_oficiales(c, fuente)
            if fuente == "pba" and c.get("notes") and "sentido" in c["notes"] and c["notes"] not in b["sentidos"]:
                b["sentidos"].append(c["notes"].split(";")[0])
            return
    base.append({"lat": c["lat"], "lon": c["lon"], "maxspeed": c.get("maxspeed"),
                 "_pv": PRIOR[fuente] if c.get("maxspeed") else 9,
                 "direction": c.get("direction"), "road": c.get("road"),
                 "sentidos": [c["notes"].split(";")[0]] if fuente == "pba" and c.get("notes") and "sentido" in c["notes"] else [],
                 "rumbos": [c["rumbo"]] if c.get("rumbo") is not None else [],
                 "manos": manos_oficiales(c, fuente),
                 "fuentes": {fuente}, "conflicto": None})


for c in pba:
    sumar(c, "pba")
for c in osm:
    sumar(c, "osm")
for c in caba:
    sumar(c, "caba")
# ANSV: radares fijos autorizados en rutas nacionales (sin máxima: la completa completar_velocidades.py)
for c in ansv:
    sumar(c, "ansv")

for i, b in enumerate(base):
    b["id"] = i + 1
    b["fuentes"] = sorted(b["fuentes"])
    b["dos_manos"] = b.pop("manos") == {"asc", "desc"}
    b.pop("_pv")

json.dump(base, open(f"{BASE}/camaras.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)

amba = [b for b in base if AMBA[0] <= b["lat"] <= AMBA[2] and AMBA[1] <= b["lon"] <= AMBA[3]]
print("BASE UNIFICADA:", len(base), "| AMBA:", len(amba), "| sin velocidad:", sum(1 for b in base if not b["maxspeed"]))
print("Por fuentes:", collections.Counter("+".join(b["fuentes"]) for b in base).most_common())
print("Conflictos de velocidad PBA vs OSM:", sum(1 for b in base if b["conflicto"]))

CORREDORES = {
    "Panamericana / RN9 / Acceso Norte": r"PANAMERICANA|ACCESO NORTE|\bRN ?9\b|NACIONAL 9\b|RUTA 9\b",
    "Ramal Pilar / RN8": r"RAMAL PILAR|\bRN ?8\b|NACIONAL 8\b|RUTA 8\b",
    "Acceso Oeste / RN7": r"ACCESO OESTE|\bRN ?7\b|NACIONAL 7\b|RUTA 7\b",
    "Riccheri / RP4? / Ezeiza-Cañuelas RN205": r"RICCHERI|EZEIZA|CAÑUELAS|\bRN ?205\b|NACIONAL 205",
    "Au. Bs As - La Plata / RN1": r"LA PLATA|\bRN ?1\b|NACIONAL 1\b",
    "RN3": r"\bRN ?3\b|NACIONAL 3\b|RUTA 3\b",
    "RN5": r"\bRN ?5\b|NACIONAL 5\b|RUTA 5\b",
    "RP2 / Autovía 2": r"\bRP ?2\b|PROVINCIAL 2\b|AUTOV[IÍ]A 2|RUTA 2\b",
    "RP6": r"\bRP ?6\b|PROVINCIAL 6\b",
    "RP11": r"\bRP ?11\b|PROVINCIAL 11\b",
    "Camino del Buen Ayre": r"BUEN AYRE",
    "General Paz": r"GENERAL PAZ|GRAL\.? PAZ",
    "Au. 25 de Mayo / Perito Moreno / Dellepiane": r"25 DE MAYO|PERITO MORENO|DELLEPIANE|AU ?1\b|AU ?6\b",
    "Lugones / Cantilo / Illia / Paseo del Bajo": r"LUGONES|CANTILO|ILLIA|PASEO DEL BAJO",
}
print("\nCobertura por corredor (cámaras en la base / de qué fuente):")
for nom, rx in CORREDORES.items():
    sel = [b for b in base if b["road"] and re.search(rx, b["road"].upper())]
    print(f"  {nom:45s} {len(sel):3d}  {dict(collections.Counter('+'.join(b['fuentes']) for b in sel))}")
