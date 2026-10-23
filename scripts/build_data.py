"""Descarga los datos del set actual desde Community Dragon y genera data/set.json + imágenes.

Uso: python3 scripts/build_data.py [ruta_es_es.json]
Si no se pasa ruta, descarga es_es.json (~25 MB).
"""
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

SET = "18"
CDRAGON = "https://raw.communitydragon.org/latest"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "img")


def asset_url(path):
    path = path.lower()
    path = re.sub(r"\.(tex|dds)$", ".png", path)
    return f"{CDRAGON}/game/{path}"


def slug(api_name):
    return re.sub(r"[^a-z0-9]+", "_", api_name.lower()).strip("_")


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hexforge-tft/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            f.write(r.read())
        return True
    except Exception as e:
        print("  fallo:", url, e)
        return False


def clean_desc(text):
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"%i:[a-zA-Z]+%", "", text)
    return text.replace("\r", "").replace("\\n", "\n").strip()


# Etiquetas de nivel de los aumentos: 1 = plata, 2 = oro, 3 = prismático
AUGMENT_TIERS = {"{d11fd6d5}": 1, "{ce1fd21c}": 2, "{cf1fd3af}": 3}
# Palabras clave (en la descripción en español) para clasificar los aumentos
AUGMENT_CATEGORIES = {
    "econ": [r"\boro\b", r"experiencia", r"inter[eé]s"],
    "reroll": [r"actualizaci", r"3 estrellas", r"tres estrellas", r"de coste [123]\b"],
    "items": [r"componente", r"\bobjeto", r"yunque", r"esp[aá]tula"],
    "ap": [r"poder de habilidad", r"\bman[aá]\b"],
    "ad": [r"da[ñn]o de ataque", r"velocidad de ataque", r"cr[ií]tic"],
    "tank": [r"armadura", r"resistencia m[aá]gica", r"vida m[aá]xima", r"\bescudo", r"durabilidad"],
}
OFFENSE = {"AbilityPower", "AttackDamage", "AttackSpeed", "CritChance", "Mana"}
TANK_TAG = "{15b72700}"


def item_role(tags, kind):
    """'dmg' para objetos de carry, 'tank' para defensivos, 'other' para el resto."""
    if kind in ("component", "emblem"):
        return "other"
    if TANK_TAG in tags or not (set(tags) & OFFENSE):
        return "tank"
    return "dmg"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "es_es.json")
    if not os.path.exists(src):
        print("Descargando es_es.json…")
        fetch(f"{CDRAGON}/cdragon/tft/es_es.json", src)
    d = json.load(open(src, encoding="utf8"))
    s = d["sets"][SET]

    downloads = []

    traits = []
    trait_by_name = {}
    for t in s["traits"]:
        breakpoints = sorted({e["minUnits"] for e in t["effects"] if e.get("minUnits")})
        if not breakpoints:
            continue
        sid = slug(t["apiName"])
        trait = {
            "id": sid,
            "name": t["name"],
            "desc": clean_desc(t.get("desc")),
            "breakpoints": breakpoints,
            "img": f"img/traits/{sid}.png",
        }
        traits.append(trait)
        trait_by_name[t["name"]] = sid
        downloads.append((asset_url(t["icon"]), os.path.join(ROOT, trait["img"])))

    champs = []
    for c in s["champions"]:
        if not c.get("traits") or c.get("cost") not in (1, 2, 3, 4, 5):
            continue
        sid = slug(c["apiName"])
        icon = c.get("tileIcon") or c.get("squareIcon")
        champ = {
            "id": sid,
            "name": c["name"],
            "cost": c["cost"],
            "traits": [trait_by_name[t] for t in c["traits"] if t in trait_by_name],
            "ability": c.get("ability", {}).get("name", ""),
            "range": int(round((c.get("stats") or {}).get("range") or 1)),
            "img": f"img/champs/{sid}.png",
        }
        champs.append(champ)
        downloads.append((asset_url(icon), os.path.join(ROOT, champ["img"])))

    items = []
    by_api = {i["apiName"]: i for i in d["items"]}
    for i in d["items"]:
        api = i["apiName"]
        name = i.get("name") or ""
        if not api.startswith("DA_") or not i.get("icon") or not name or name.startswith(("tft_item_name", "@", "game_")):
            continue
        comp = i.get("composition") or []
        if api.startswith("DA_Component_"):
            kind = "component"
        elif api.startswith(f"DA_{SET}_Emblem"):
            if "Augment" in api:
                continue
            kind = "emblem"
        elif api.startswith("DA_Artifact_"):
            kind = "artifact"
        elif "radiant" in api.lower():
            kind = "radiant"
        elif len(comp) == 2 and all(c.startswith("DA_Component_") and c in by_api for c in comp):
            kind = "completed"
        else:
            continue
        sid = slug(api)
        item = {
            "id": sid,
            "api": api,
            "name": name,
            "kind": kind,
            "desc": clean_desc(i.get("desc")),
            "components": [slug(c) for c in comp] if kind in ("completed", "emblem") else [],
            "role": item_role(i.get("tags") or [], kind),
            "stats": sorted(set(i.get("tags") or []) & OFFENSE),
            "img": f"img/items/{sid}.png",
        }
        items.append(item)
        downloads.append((asset_url(i["icon"]), os.path.join(ROOT, item["img"])))

    # Aumentos del set (lista oficial), con nivel, rasgos asociados y categorías
    set_data = next((x for x in d["setData"] if x.get("mutator") == f"TFTSet{SET}"), {})
    pool = set_data.get("augments", [])
    trait_by_api = {t["apiName"]: slug(t["apiName"]) for t in s["traits"]}
    augments = []
    for api in pool:
        i = by_api.get(api)
        if not i or not i.get("name"):
            continue
        desc = clean_desc(i.get("desc"))
        text = re.sub(r"@[^@]+@", "X", desc).replace("  ", " ")
        tags = set(i.get("tags") or [])
        tier = next((n for tag, n in AUGMENT_TIERS.items() if tag in tags), 0)
        icon = i.get("icon") or ""
        linked_traits = [trait_by_api[t] for t in i.get("associatedTraits") or [] if t in trait_by_api]
        linked_champs = [c["id"] for c in champs
                         if "(" not in c["name"] and re.search(rf"\b{re.escape(c['name'])}\b", desc)]
        if "lux" in api.lower():
            linked_champs.append("da_lux18_base")
        low = text.lower()
        cats = {cat: sum(1 for p in pats if re.search(p, low)) for cat, pats in AUGMENT_CATEGORIES.items()}
        sid = slug(api)
        aug = {
            "id": sid,
            "name": i["name"],
            "desc": text,
            "tier": tier,
            "traits": linked_traits,
            "champs": sorted(set(linked_champs)),
            "cats": {c: n for c, n in cats.items() if n},
            "plus": i["name"].endswith("+"),
            "img": None if "missing" in icon else f"img/augments/{sid}.png",
        }
        augments.append(aug)
        if aug["img"]:
            downloads.append((asset_url(icon), os.path.join(ROOT, aug["img"])))
    os.makedirs(os.path.join(IMG, "augments"), exist_ok=True)
    # Aumentos con el mismo nombre (p. ej. "Bestia interior" de Sivir y de Nidalee): se añade el campeón
    names = Counter(a["name"] for a in augments)
    for a in augments:
        if names[a["name"]] > 1:
            suffix = a["id"].rsplit("_", 1)[-1]
            champ = next((c for c in champs if c["id"] in a["champs"] and suffix in c["id"]), None)
            if champ:
                a["name"] = f"{a['name']} ({champ['name']})"

    print(f"Set {SET}: {len(champs)} campeones, {len(traits)} rasgos, {len(items)} objetos, {len(augments)} aumentos")
    print(f"Descargando {len(downloads)} imágenes…")
    with ThreadPoolExecutor(8) as ex:
        ok = sum(ex.map(lambda a: fetch(*a), downloads))
    print(f"  {ok}/{len(downloads)} imágenes OK")

    out = {"set": SET, "champions": champs, "traits": traits, "items": items, "augments": augments}
    with open(os.path.join(ROOT, "data", "set.json"), "w", encoding="utf8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Guardado data/set.json")


if __name__ == "__main__":
    main()
