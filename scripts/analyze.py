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
    best_items = {}
    for u in final:
        top = [i for i, _ in item_use[u].most_common() if items[i]["kind"] != "component"][:3]
        if len(top) >= 2:
            best_items[u] = top
    avg_tank = {u: sum(c for i, c in item_use[u].items() if items[i].get("role") == "tank") / max(1, len(good)) for u in final}

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
        "avg_tank": avg_tank,
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


def pick_items(s, carry):
    carries = [carry] + [u for u in s["carries"] if u != carry]
    holders = [u for u in carries[:3] if u in s["items"]]
    tanks = sorted((u for u in s["items"] if u not in carries and s["avg_tank"].get(u, 0) >= 0.5),
                   key=lambda u: -s["avg_tank"][u])
    holders += tanks[:1]
    return {u: s["items"][u] for u in holders}


def comp_traits(units, champs, traits):
    count = Counter(t for u in set(units) for t in champs[u]["traits"])
    return {t for t, n in count.items() if traits[t]["breakpoints"] != [1] and n >= traits[t]["breakpoints"][0]}


def temp_carries(group, items, max_cost=3, n=2):
    """Unidades que más veces llevan 2+ objetos de daño en tableros intermedios."""
    holders = Counter(u["id"] for b in group for u in b["units"]
                      if sum(1 for i in u["items"] if items[i].get("role") == "dmg") >= 2)
    return [u for u, _ in holders.most_common() if u][:n], holders


def attach_stage_boards(comps, boards, champs, traits, items, min_boards=15):
    """Early y mid reales: tableros de nivel 5-7 (jugadores eliminados) asignados a la composición más parecida."""
    info = [(c, set(c["units"]), comp_traits(c["units"], champs, traits)) for c in comps]
    assigned = defaultdict(list)
    for b in boards:
        if b["level"] > 7:
            continue
        units = {u["id"] for u in b["units"]}
        active = {t for t in b["traits"] if traits[t]["breakpoints"] != [1]}
        # Parecido = unidades en común + rasgos activos en común (las Fast 8/9 se reconocen sobre todo por rasgos)
        scored = sorted(((len(units & cu) + len(active & ct), c["id"]) for c, cu, ct in info), reverse=True)
        if not scored or scored[0][0] < 3:
            continue
        best = [cid for sc, cid in scored if sc == scored[0][0]]
        for cid in best:  # empate: el tablero cuenta para todas las empatadas
            assigned[cid].append(b)
    low = [b for b in boards if b["level"] <= 7]
    for c in comps:
        group = assigned.get(c["id"], [])
        if len(group) < min_boards:
            stage_from_traits(c, low, champs, traits, items)
            continue
        freq = Counter(u["id"] for b in group for u in b["units"])
        n = len(group)
        mid = [u for u, k in freq.most_common() if k / n >= 0.2][:7]
        early = [u for u, k in freq.most_common() if champs[u]["cost"] <= 2 and k / n >= 0.12][:5]
        if len(early) < 4:
            early += [u for u, k in freq.most_common() if champs[u]["cost"] == 3 and u not in early][:5 - len(early)]
        stars = defaultdict(list)
        for b in group:
            for u in b["units"]:
                stars[u["id"]].append(u["stars"])
        c["mid"] = sorted(mid, key=lambda u: champs[u]["cost"])
        c["early"] = sorted(early, key=lambda u: champs[u]["cost"])
        c["midStars"] = {u: Counter(stars[u]).most_common(1)[0][0] for u in mid}
        c["stageGames"] = n
        c["stageSource"] = "boards"
        c["stageCarries"] = temp_carries(group, items)[0]
        c["_itemFreq"] = completed_freq(group, items)


def completed_freq(group, items):
    """Cuántas veces aparece cada objeto completo en tableros de nivel 5-7 (= se hace pronto)."""
    return Counter(i for b in group for u in b["units"] for i in u["items"]
                   if items[i]["kind"] in ("completed", "radiant", "artifact", "emblem"))


AP_STATS = {"AbilityPower", "Mana"}
AD_STATS = {"AttackDamage", "AttackSpeed", "CritChance"}


# Tipo de daño de cada componente: la Vara da poder de habilidad, Espadón y Arco dan ataque...
COMPONENT_TYPE = {
    "da_component_needlesslylargerod": ("ap", 2), "da_component_tearofthegoddess": ("ap", 1),
    "da_component_bfsword": ("ad", 2), "da_component_recurvebow": ("ad", 2), "da_component_sparringgloves": ("ad", 0.5),
}


def item_type(i, items):
    """'ap' o 'ad' según sus componentes (las etiquetas de los datos del juego no son fiables);
    radiantes y artefactos sin receta usan sus etiquetas."""
    comps = items[i].get("components") or []
    if comps:
        score = Counter()
        for c in comps:
            t, w = COMPONENT_TYPE.get(c, (None, 0))
            if t:
                score[t] += w
        if score["ap"] != score["ad"]:
            return "ap" if score["ap"] > score["ad"] else "ad"
        return None
    st = set(items[i].get("stats") or [])
    ap, ad = len(st & AP_STATS), len(st & AD_STATS)
    return "ap" if ap > ad else "ad" if ad > ap else None


def champ_damage_types(boards, items):
    """Si cada campeón suele llevar objetos de poder de habilidad (ap) o de ataque (ad), según las partidas."""
    count = defaultdict(Counter)
    for b in boards:
        for u in b["units"]:
            for i in u["items"]:
                if items[i].get("role") == "dmg":
                    t = item_type(i, items)
                    if t:
                        count[u["id"]][t] += 1
    return {u: c.most_common(1)[0][0] for u, c in count.items() if sum(c.values()) >= 5}


def attach_stage_items(comps, champs, items, dmg_type):
    """Orden de prioridad de los objetos (según lo pronto que aparecen) y quién los lleva en early y mid."""
    for c in comps:
        freq = c.pop("_itemFreq", Counter())
        holders = list(c["items"])
        if not holders:
            continue
        carry = holders[0]
        tank = next((u for u in holders if u not in c["carries"]), None)
        order = lambda its: sorted(its, key=lambda i: -freq.get(i, 0))
        carry_items = order(c["items"][carry])
        tank_items = order(c["items"][tank]) if tank else []
        c["itemOrder"] = {u: order(its) for u, its in c["items"].items()}

        want = Counter(item_type(i, items) for i in carry_items).most_common(1)[0][0] if carry_items else None

        def holder_carry(units):
            """El carry final si ya está; si no, quien mejor le sustituye y usa el mismo tipo de objetos."""
            if carry in units:
                return carry
            tmp = c.get("stageCarries", [])

            def rank(u):
                return (dmg_type.get(u) == want,          # mismo tipo de daño (ataque / poder de habilidad)
                        u in tmp,                          # carry provisional según las partidas
                        champs[u]["range"] >= 3,           # mejor a distancia
                        champs[u]["cost"])
            cands = [u for u in units if dmg_type.get(u) in (want, None)] or list(units)
            return max(cands, key=rank) if cands else None

        def holder_tank(units, taken):
            if tank in units and tank != taken:
                return tank
            melee = sorted((u for u in units if champs[u]["range"] <= 1 and u != taken),
                           key=lambda u: (-champs[u]["cost"], u))
            return melee[0] if melee else None

        stage_items = {}
        for stage, n_carry, n_tank in (("early", 1, 1), ("mid", 2, 2)):
            units = c.get(stage) or []
            hc = holder_carry(units)
            ht = holder_tank(units, hc)
            plan = {}
            if hc and carry_items:
                plan[hc] = carry_items[:n_carry]
            if ht and tank_items:
                plan[ht] = tank_items[:n_tank]
            stage_items[stage] = plan
        c["stageItems"] = stage_items


def stage_from_traits(c, low, champs, traits, items):
    """Para composiciones sin tableros intermedios propios (sobre todo Fast 8/9): campeones baratos
    de sus dos rasgos principales más jugados en tableros de nivel 5-7 con esos rasgos activos."""
    count = Counter(t for u in set(c["units"]) for t in champs[u]["traits"] if traits[t]["breakpoints"] != [1])
    core = [t for t, _ in count.most_common(2)]
    if not core:
        return
    pool = [b for b in low if any(t in b["traits"] for t in core)]
    freq = Counter(u["id"] for b in pool for u in b["units"])
    related = lambda u: u in c["units"] or any(t in champs[u]["traits"] for t in core)
    _, holders = temp_carries(pool, items)
    # Carry provisional: el que más lleva objetos de daño en esos tableros (mejor si es de sus rasgos)
    carry_rank = sorted(holders, key=lambda u: -(holders[u] * (2 if related(u) else 1)))

    def board(size, max_cost, extra=()):
        tmp = [u for u in carry_rank if champs[u]["cost"] <= max_cost][:2 if size > 5 else 1]
        picked = tmp + [u for u in sorted(c["units"], key=lambda u: -freq[u]) if champs[u]["cost"] <= max_cost and u not in tmp]
        for u, _ in freq.most_common():
            if len(picked) >= size:
                break
            if u not in picked and champs[u]["cost"] <= max_cost and related(u):
                picked.append(u)
        for u in extra:  # p. ej. el carry de 4 de coste que ya se juega a nivel 7
            if u not in picked:
                picked = picked[:size - 1] + [u]
        return sorted(picked[:size], key=lambda u: champs[u]["cost"])

    carry4 = [u for u in c["carries"] if champs[u]["cost"] == 4][:1]
    c["mid"] = board(7, 3, carry4)
    c["early"] = board(5, 2)
    c["midStars"] = {}
    c["stageGames"] = len(pool)
    c["stageSource"] = "traits"
    c["stageCarries"] = [u for u in carry_rank if champs[u]["cost"] <= 3][:2]
    c["_itemFreq"] = completed_freq(pool, items)


def attach_guides(comps, champs, traits, min_overlap=0.65):
    """Combina cada composición con la guía experta (TFT Flow) de tablero final más parecido:
    early = opener de la guía; mid = lo que ya se tiene a nivel 7 del final + opener + datos reales;
    posiciones del tablero final = las de la guía."""
    path = os.path.join(DATA, "guides.json")
    if not os.path.exists(path):
        return
    guides = [g for g in json.load(open(path, encoding="utf8"))["guides"] if all(u in champs for u in g["units"])]
    for c in comps:
        units = set(c["units"])
        best, score = None, 0
        for g in guides:
            gu = set(g["units"])
            sc = len(units & gu) / max(1, min(len(units), len(gu)))
            if sc > score:
                best, score = g, sc
        if not best or score < min_overlap:
            continue
        final_traits = {t for u in c["units"] for t in champs[u]["traits"]}
        opener = [u for u in (best["openers"][0] if best["openers"] else []) if u in champs]
        data_mid = c.get("mid", [])
        mid = [u for u in sorted(c["units"], key=lambda u: champs[u]["cost"]) if champs[u]["cost"] <= 3]
        carry4 = [u for u in c["carries"] if champs[u]["cost"] == 4][:1]
        for u in opener + data_mid:
            if len(mid) >= 7 - len(carry4):
                break
            if u not in mid and (u in data_mid or set(champs[u]["traits"]) & final_traits):
                mid.append(u)
        mid = (mid[:7 - len(carry4)] + [u for u in carry4 if u not in mid])[:7]
        if len(opener) >= 4:  # openers con huecos libres ("flex") se quedan con el early de los datos
            c["early"] = opener
        if len(mid) >= 5:
            c["mid"] = sorted(mid, key=lambda u: champs[u]["cost"])
        c["positions"] = {u: i for u, i in best["positions"].items() if u in units}
        c["guide"] = {"name": best["name"], "url": best["url"], "match": round(score, 2)}
        c["stageSource"] = "guide"


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
        # Reroll: el carry barato suele ir a 3 estrellas, o hay 3+ unidades baratas a 3 estrellas
        reroll_units = [u for u, st in s["stars"].items() if st == 3 and champs[u]["cost"] <= 3]
        if (champs[carry]["cost"] <= 3 and three_share >= 0.4) or len(reroll_units) >= 3:
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
        if s["style"] == "Reroll" and reroll_units:
            names = ", ".join(champs[u]["name"] for u in sorted(reroll_units, key=lambda u: champs[u]["cost"]))
            tips += f" Sube a 3 estrellas: {names}."
        comps.append({
            "id": f"{carry}-{trait}",
            "name": name,
            "tier": s["tier"],
            "style": s["style"],
            "trend": s["trend"],
            "stats": s["stats"],
            "units": s["units"],
            # Objetos solo de los carries (hasta 3) y del tanque principal, en ese orden
            "items": pick_items(s, carry),
            "carries": s["carries"] or [carry],
            "stars": s["stars"],
            "tips": tips,
        })

    # Las más jugadas; el tier es relativo entre ellas (por puesto medio)
    unique = sorted(comps, key=lambda c: -c["stats"]["games"])[:args.max_comps]
    attach_stage_boards(unique, boards, champs, traits, items)
    attach_guides(unique, champs, traits)
    attach_stage_items(unique, champs, items, champ_damage_types(boards, items))
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
