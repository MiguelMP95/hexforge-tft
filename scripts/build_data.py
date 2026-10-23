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
            "img": f"img/items/{sid}.png",
        }
        items.append(item)
        downloads.append((asset_url(i["icon"]), os.path.join(ROOT, item["img"])))

    # Aumentos propios del set, enlazados a rasgos y campeones
    augments = []
    trait_keys = {t["id"]: re.sub(r"(da_|18|_|uniquetrait)", "", t["id"]) for t in traits}
    for i in d["items"]:
        api = i["apiName"]
        if "Augment" not in api or "Emblem" in api or not i.get("name") or not i.get("icon"):
            continue
        if not (api.startswith(f"DA_{SET}_") or api.startswith("DA_")):
            continue
        low = api.lower()
        desc = clean_desc(i.get("desc"))
        linked_traits = [tid for tid, key in trait_keys.items() if key and len(key) >= 3 and key in low]
        linked_champs = [c["id"] for c in champs
                         if "(" not in c["name"] and re.search(rf"\b{re.escape(c['name'])}\b", desc)]
        if "lux" in low:
            linked_champs.append("da_lux18_base")
        sid = slug(api)
        augments.append({
            "id": sid,
            "name": i["name"],
            "desc": re.sub(r"@[^@]+@", "X", desc).replace("  ", " "),
            "traits": linked_traits,
            "champs": sorted(set(linked_champs)),
            "plus": api.endswith("Plus") or "Plus_" in api or i["name"].endswith("+"),
            "img": f"img/augments/{sid}.png",
        })
        downloads.append((asset_url(i["icon"]), os.path.join(ROOT, "img", "augments", f"{sid}.png")))
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
