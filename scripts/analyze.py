"""Agrupa los tableros finales de las partidas descargadas en composiciones y calcula sus estadísticas.

Uso: python3 scripts/analyze.py [--min-games 40]
Lee data/raw/matches/*.json y data/set.json; escribe data/comps.json
(la versión manual anterior queda en data/comps_manual.json).
"""
import argparse
import glob
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

ITEM_KINDS_FOR_CARRY = {"completed", "radiant", "artifact", "emblem"}


def load_set():
    s = json.load(open(os.path.join(DATA, "set.json"), encoding="utf8"))
    champs = {c["id"]: c for c in s["champions"]}
    traits = {t["id"]: t for t in s["traits"]}
    items = {i["id"]: i for i in s["items"]}
    return champs, traits, items


def slug(api):
    return "".join(ch if ch.isalnum() else "_" for ch in api.lower()).strip("_")


def load_patch():
    path = os.path.join(DATA, "patch.json")
    return json.load(open(path, encoding="utf8")) if os.path.exists(path) else {}


def patch_start():
    start = load_patch().get("start")
    return datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp() if start else 0


def read_boards(champs, traits, items, days=0, prune=False):
    """Lee los tableros. Con days > 0 solo usa las partidas de los últimos días (y con prune borra las demás)."""
    boards, times = [], []
    unknown = Counter()
    matches = 0
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400 if days else 0
    cutoff = max(cutoff, patch_start())
    for path in glob.glob(os.path.join(DATA, "raw", "matches", "*.json")):
        info = json.load(open(path))["info"]
        ts = info.get("game_datetime", 0) / 1000
        if ts < cutoff:
            if prune:
                os.remove(path)
            continue
        if info.get("queue_id") != 1100:
            continue
        matches += 1
        times.append(ts)
        for p in info["participants"]:
            units = []
            for u in p["units"]:
                cid = slug(u["character_id"])
                if cid not in champs:
                    unknown[u["character_id"]] += 1
                    continue
                its = []
                for it in u.get("itemNames", []):
                    iid = slug(it)
                    if iid in items:
                        its.append(iid)
                    else:
                        unknown[it] += 1
                units.append({"id": cid, "stars": u.get("tier", 1), "items": its})
            active = {}
            for t in p["traits"]:
                tid = slug(t["name"])
                if tid in traits and t.get("tier_current", 0) > 0:
                    active[tid] = t["num_units"]
            boards.append({
                "units": units,
                "traits": active,
                "level": p.get("level", 0),
                "placement": p["placement"],
                "time": ts,
            })
    return boards, matches, times, unknown


def dmg_items(u, items):
    return sum(1 for i in u["items"] if items[i].get("role") == "dmg")


def main_carry(board, champs, items):
    """Unidad con más objetos ofensivos; desempata por coste y estrellas."""
    def weight(u):
        n = dmg_items(u, items)
        return (n, champs[u["id"]]["cost"] if n else 0, u["stars"])
    best = max(board["units"], key=weight, default=None)
    return best["id"] if best and weight(best)[0] >= 2 else None


def primary_trait(board, traits):
    """Rasgo no único con más unidades activas."""
    cands = [(n, tid) for tid, n in board["traits"].items() if traits[tid]["breakpoints"] != [1]]
    return max(cands)[1] if cands else None


def summarize(group, champs, traits, items, total_matches, split_time):
    n = len(group)
    places = [b["placement"] for b in group]
    level = statistics.median(b["level"] for b in group)

    unit_count = Counter(u["id"] for b in group for u in b["units"])
    size = int(round(statistics.median(len(b["units"]) for b in group)))
    final = [u for u, c in unit_count.most_common() if c / n >= 0.15][:max(size, 7)]

    # Objetos por unidad: los más frecuentes entre las partidas que quedaron top 4
    good = [b for b in group if b["placement"] <= 4] or group
    item_use = defaultdict(Counter)
    holders = Counter()
    stars = defaultdict(list)
    for b in good:
        for u in b["units"]:
            if u["id"] in final:
                stars[u["id"]].append(u["stars"])
                if u["items"]:
                    holders[u["id"]] += 1
                    for i in u["items"]:
                        item_use[u["id"]][i] += 1
    avg_items = {u: sum(item_use[u].values()) / max(1, unit_count[u]) for u in final}
    avg_dmg = {u: sum(c for i, c in item_use[u].items() if items[i].get("role") == "dmg") / max(1, len(good)) for u in final}

    carries = sorted((u for u in final if avg_dmg[u] >= 1.2), key=lambda u: -avg_dmg[u])
    carries = carries[:3]
    item_holders = sorted(final, key=lambda u: -avg_items[u])[:4]
    best_items = {}
    for u in item_holders:
        top = [i for i, _ in item_use[u].most_common() if items[i]["kind"] != "component"][:3]
        if len(top) >= 2:
            best_items[u] = top

    main = carries[0] if carries else None
    main_stars = statistics.mean(stars[main]) if main and stars[main] else 0
    if main and champs[main]["cost"] <= 3 and main_stars >= 2.5:
        style = "Reroll"
    elif level >= 9:
        style = "Fast 9"
    else:
        style = "Fast 8"

    avg = statistics.mean(places)
    tier = "S" if avg <= 4.05 else "A" if avg <= 4.35 else "B" if avg <= 4.65 else "C"

    old = [b for b in group if b["time"] < split_time]
    new = [b for b in group if b["time"] >= split_time]
    ratio = (len(new) + 1) / (len(old) + 1)
    trend = "up" if ratio > 1.35 else "down" if ratio < 0.75 else "stable"

    return {
        "units": final,
        "carries": carries,
        "items": best_items,
        "style": style,
        "tier": tier,
        "trend": trend,
        "level": level,
        "main_stars": main_stars,
        # Estrellas más habituales de cada unidad en los tableros top 4
        "stars": {u: Counter(stars[u]).most_common(1)[0][0] for u in final if stars[u]},
        "stats": {
            "avg": round(avg, 2),
            "top4": round(100 * sum(p <= 4 for p in places) / n, 1),
            "win": round(100 * sum(p == 1 for p in places) / n, 1),
            "pick": round(n / total_matches, 2),
            "games": n,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-games", type=int, default=40)
    ap.add_argument("--max-comps", type=int, default=24)
    ap.add_argument("--days", type=int, default=0, help="usar solo las partidas de los últimos N días (0 = todas)")
    ap.add_argument("--prune", action="store_true", help="borrar las partidas más antiguas que --days")
    ap.add_argument("--min-matches", type=int, default=100, help="mínimo de partidas para recalcular")
    args = ap.parse_args()

    champs, traits, items = load_set()
    boards, matches, times, unknown = read_boards(champs, traits, items, args.days, args.prune)
    if matches < args.min_matches:
        # Parche recién salido: se mantienen las composiciones anteriores y la web lo indica
        path = os.path.join(DATA, "comps.json")
        prev = json.load(open(path, encoding="utf8"))
        prev.update({"patch": load_patch().get("label", prev.get("patch")), "newPatch": True, "stale": True})
        with open(path, "w", encoding="utf8") as f:
            json.dump(prev, f, ensure_ascii=False, indent=2)
        print(f"Solo {matches} partidas del parche actual: se mantienen las composiciones anteriores.")
        return
    if unknown:
        print("Identificadores sin datos:", unknown.most_common(10))
    split_time = statistics.median(times)

    groups = defaultdict(list)
    for b in boards:
        carry = main_carry(b, champs, items)
        trait = primary_trait(b, traits)
        if carry and trait:
            groups[(carry, trait)].append(b)

    # Segunda pasada: los tableros de grupos pequeños se agrupan solo por carry
    by_carry = defaultdict(list)
    for (carry, trait), group in list(groups.items()):
        if len(group) < args.min_games:
            by_carry[carry].extend(group)
            del groups[(carry, trait)]
    for carry, group in by_carry.items():
        if len(group) >= args.min_games:
            trait = Counter(primary_trait(b, traits) for b in group).most_common(1)[0][0]
            groups[(carry, trait)].extend(group)

    # Fusiona grupos con tableros finales muy parecidos (aunque cambie el carry): gana el más jugado
    cands = []
    for (carry, trait), group in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(group) < args.min_games:
            continue
        units = set(summarize(group, champs, traits, items, matches, split_time)["units"])
        target = next((c for c in cands if len(c["units"] & units) >= 0.7 * min(len(c["units"]), len(units))), None)
        if target:
            target["group"].extend(group)
        else:
            cands.append({"carry": carry, "trait": trait, "group": list(group), "units": units})

    comps = []
    for cand in cands:
        carry, trait, group = cand["carry"], cand["trait"], cand["group"]
        s = summarize(group, champs, traits, items, matches, split_time)
        if carry not in s["units"]:
            continue
        if carry in s["carries"]:
            s["carries"].remove(carry)
        s["carries"].insert(0, carry)
        # Estilo según el carry final: reroll si es de coste ≤3 y suele estar a 3 estrellas
        carry_stars = [u["stars"] for b in group for u in b["units"] if u["id"] == carry]
        s["main_stars"] = statistics.mean(carry_stars) if carry_stars else 0
        three_share = sum(x == 3 for x in carry_stars) / max(1, len(carry_stars))
        if champs[carry]["cost"] <= 3 and three_share >= 0.4:
            s["style"] = "Reroll"
        else:
            s["style"] = "Fast 9" if s["level"] >= 9 else "Fast 8"
        # El rasgo del nombre: el principal más frecuente del grupo ya fusionado
        trait = Counter(primary_trait(b, traits) for b in group).most_common(1)[0][0] or trait
        name = f"{champs[carry]['name']} {traits[trait]['name']}"
        stars = f"{s['main_stars']:.1f}".replace(".", ",")
        tips = (
            f"Datos de {s['stats']['games']} tableros de Master+ en EUW. "
            f"Carry principal: {champs[carry]['name']} (media de {stars} estrellas). "
            f"Nivel final habitual: {s['level']:g}. "
            f"Rasgo principal: {traits[trait]['name']}."
        )
        comps.append({
            "id": f"{carry}-{trait}",
            "name": name,
            "tier": s["tier"],
            "style": s["style"],
            "trend": s["trend"],
            "stats": s["stats"],
            "units": s["units"],
            "items": s["items"],
            "carries": s["carries"] or [carry],
            "stars": s["stars"],
            "tips": tips,
        })

    # Las más jugadas; el tier es relativo entre ellas (por puesto medio)
    unique = sorted(comps, key=lambda c: -c["stats"]["games"])[:args.max_comps]
    unique.sort(key=lambda c: c["stats"]["avg"])
    n = len(unique)
    for i, c in enumerate(unique):
        q = i / max(1, n)
        c["tier"] = "S" if q < 0.2 else "A" if q < 0.5 else "B" if q < 0.8 else "C"

    first = datetime.fromtimestamp(min(times), timezone.utc).strftime("%d/%m")
    last = datetime.fromtimestamp(max(times), timezone.utc).strftime("%d/%m/%Y")
    patch = load_patch()
    patch_age_days = (datetime.now(timezone.utc).timestamp() - patch_start()) / 86400
    out = {
        "patch": patch.get("label", "?"),
        "patchStart": patch.get("start"),
        # Aviso en la web mientras el parche es reciente y hay pocos datos
        "newPatch": patch_age_days < 3 and matches < 800,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": (f"Datos propios de la API de Riot: {matches} partidas clasificatorias "
                   f"({len(boards)} tableros) de jugadores Master+ de EUW, del {first} al {last}. "
                   f"Composiciones con al menos {args.min_games} tableros."),
        "comps": unique,
    }
    with open(os.path.join(DATA, "comps.json"), "w", encoding="utf8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    covered = sum(c["stats"]["games"] for c in unique)
    print(f"{matches} partidas · {len(boards)} tableros · {len(unique)} composiciones "
          f"({100 * covered / len(boards):.0f}% de los tableros)")
    for c in unique:
        st = c["stats"]
        print(f"  {c['tier']} {c['name']:<40} {c['style']:<7} media {st['avg']:.2f} · top4 {st['top4']:>5}% · "
              f"win {st['win']:>4}% · {st['games']} tableros · {c['trend']}")


if __name__ == "__main__":
    main()
