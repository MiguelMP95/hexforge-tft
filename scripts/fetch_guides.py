"""Lee las guías de composiciones de TFT Flow (tftflow.com) y guarda en data/guides.json
solo datos estructurados: tablero final con posiciones y openers (tableros de early).

Uso: python3 scripts/fetch_guides.py
Se ejecuta al cambiar de parche; hace una petición por guía con pausa entre ellas.
"""
import html as htmllib
import json
import os
import re
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "guides.json")
TIER_LIST = "https://tftflow.com/tier-list"
SET = "18"
UA = {"User-Agent": "hexforge-tft/1.0 (fan site; github.com/MiguelMP95/hexforge-tft)"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf8", errors="ignore")


def slug(api):
    return "".join(ch if ch.isalnum() else "_" for ch in api.lower()).strip("_")


def parse_guide(html):
    html = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    title = re.search(r"<title>([^<|]+)", html)
    name = htmllib.unescape(re.sub(r"\s*Comp Guide.*$", "", title.group(1)).strip()) if title else ""

    # Tablero final: casillas 0-27 (fila 0 = delante, fila 3 = detrás)
    positions = {}
    # La guía dibuja el tablero rival (vacío, "hexagon-grid-enemy") y el del jugador ("hexagon-grid")
    board = html.find('id="hexagon-grid"')
    if board >= 0:
        seen = set()
        for part in re.split(r'(?=<g[^>]*class="hex-container")', html[board:board + 200000]):
            idx = re.match(r'<g[^>]*class="hex-container"[^>]*data-index="(\d+)"', part)
            if not idx:
                continue
            i = int(idx.group(1))
            if i in seen:  # empieza otro tablero (otra variante): solo se usa el principal
                break
            seen.add(i)
            api = re.search(r'data-champion-apiname="([^"]+)"', part)
            if api and i < 28:
                positions.setdefault(slug(api.group(1)), i)

    # Openers: la "fórmula" de cada opener (campeones del early)
    openers = []
    for block in re.findall(r'class="custom-opener-formula">(.*?)</div>\s*</div>\s*(?:<div[^>]*>\s*)?(?:Example|<)', html, flags=re.S):
        units = [slug(a) for a in re.findall(r'data-champion-apiname="([^"]+)"', block)]
        if units:
            openers.append(list(dict.fromkeys(units)))
    if not openers:
        for block in re.split(r'class="custom-opener-formula"', html)[1:]:
            end = block.find("Example")
            units = [slug(a) for a in re.findall(r'data-champion-apiname="([^"]+)"', block[:end if end > 0 else 3000])]
            if units:
                openers.append(list(dict.fromkeys(units)))
    openers = [list(o) for o in dict.fromkeys(tuple(o) for o in openers)]
    return {"name": name, "units": list(positions), "positions": positions, "openers": openers,
            "leveling": parse_leveling(html)}


def parse_leveling(html):
    """Plan de niveles de la guía: solo fase -> nivel y si toca tirar (no se guarda el texto)."""
    block = re.search(r'class="econ-ol">(.*?)</ol>', html, flags=re.S)
    if not block:
        return []
    steps = []
    for stage, text in re.findall(r'<li data-prefix="(\d-\d)"[^>]*>(.*?)</li>', block.group(1), flags=re.S):
        text = re.sub(r"<[^>]+>", " ", text)
        lvl = re.search(r"\b(?:[Ll]evel|[Ll]vl) (?:to |up to )?(\d+)", text) or re.search(r"\b[Ss]tay (?:at )?(?:level |lvl )?(\d+)", text)
        low = text.lower()
        action = "slowroll" if "slow roll" in low or "slowroll" in low else \
                 "roll" if re.search(r"\broll (?:down|for|until|to find|to 3|aggressively)|\ball[- ]in", low) and "don't need to roll" not in low else None
        if lvl or action:
            # "Level to 6 if ..." = solo si se cumple una condición (racha, oro...): opcional
            optional = bool(re.search(r"\blevel (?:to |up to )?\d+,? (?:only )?if\b", low))
            steps.append({"stage": stage, "level": int(lvl.group(1)) if lvl else None, "action": action, "optional": optional})
    return steps


def main():
    tier = get(TIER_LIST)
    urls = sorted(set(re.findall(rf'href="(https://tftflow\.com/composition/set{SET}/[a-z0-9-]+)"', tier)))
    print(f"{len(urls)} guías encontradas")
    guides = []
    for url in urls:
        try:
            g = parse_guide(get(url))
        except Exception as e:  # una guía rota no debe parar el resto
            print("  fallo:", url, e)
            continue
        if g["units"]:
            g["url"] = url
            guides.append(g)
            print(f"  {g['name']}: {len(g['units'])} en el tablero, {len(g['openers'])} openers")
        time.sleep(1.5)
    with open(OUT, "w", encoding="utf8") as f:
        json.dump({"source": "TFT Flow (tftflow.com)", "fetched": time.strftime("%Y-%m-%d"), "guides": guides},
                  f, ensure_ascii=False, indent=1)
    print(f"Guardadas {len(guides)} guías en data/guides.json")


if __name__ == "__main__":
    main()
