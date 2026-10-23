"""Descarga partidas clasificatorias de TFT de jugadores Master+ usando la API de Riot.

Uso:
  python3 scripts/riot_fetch.py [--platform euw1] [--region europe] [--max-matches 2000]

La clave se lee de .riot_key (en la raíz del proyecto) o de la variable RIOT_API_KEY.
Las partidas se guardan en data/raw/matches/ y no se vuelven a descargar si ya existen,
así que se puede interrumpir y reanudar.
"""
import argparse
import glob
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
MATCHES = os.path.join(RAW, "matches")
RANKED_QUEUE = 1100
PATCH_FILE = os.path.join(ROOT, "data", "patch.json")


def window_start(days):
    """Inicio de la ventana: hace N días, pero nunca antes del inicio del parche actual."""
    start = time.time() - days * 86400 if days else 0
    if os.path.exists(PATCH_FILE):
        patch = json.load(open(PATCH_FILE))
        start = max(start, datetime.fromisoformat(patch["start"].replace("Z", "+00:00")).timestamp())
    return int(start)


def load_key():
    key = os.environ.get("RIOT_API_KEY")
    if not key:
        path = os.path.join(ROOT, ".riot_key")
        if os.path.exists(path):
            key = open(path).read().strip()
    if not key:
        sys.exit("Falta la clave: crea .riot_key o define RIOT_API_KEY")
    return key


class RateLimiter:
    """Respeta los límites de la clave de desarrollo: 20 por segundo y 100 cada 2 minutos."""

    def __init__(self, limits=((20, 1), (100, 120))):
        self.limits = limits
        self.calls = deque()

    def wait(self):
        while True:
            now = time.time()
            longest = max(w for _, w in self.limits)
            while self.calls and now - self.calls[0] > longest:
                self.calls.popleft()
            delay = 0
            for n, window in self.limits:
                recent = [t for t in self.calls if now - t < window]
                if len(recent) >= n:
                    delay = max(delay, window - (now - recent[0]) + 0.05)
            if delay <= 0:
                self.calls.append(now)
                return
            time.sleep(delay)


class Riot:
    def __init__(self, key):
        self.key = key
        self.limiter = RateLimiter()
        self.count = 0

    def get(self, url, retries=5):
        for attempt in range(retries):
            self.limiter.wait()
            self.count += 1
            req = urllib.request.Request(url, headers={"X-Riot-Token": self.key, "User-Agent": "hexforge-tft/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = int(e.headers.get("Retry-After", "10"))
                    print(f"  límite alcanzado, esperando {wait}s…", flush=True)
                    time.sleep(wait)
                    continue
                if e.code in (500, 502, 503, 504):
                    time.sleep(2 * (attempt + 1))
                    continue
                if e.code in (401, 403):
                    sys.exit(f"La API rechaza la clave ({e.code}). ¿Ha caducado? Genera una nueva en developer.riotgames.com")
                if e.code == 404:
                    return None
                raise
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 * (attempt + 1))
        return None


def compact(match):
    """Solo lo que usa el análisis: unas 10 veces menos espacio que la partida completa."""
    info = match["info"]
    return {"info": {
        "game_datetime": info.get("game_datetime"),
        "queue_id": info.get("queue_id"),
        "participants": [{
            "placement": p["placement"],
            "level": p.get("level"),
            "units": [{"character_id": u["character_id"], "tier": u.get("tier", 1), "itemNames": u.get("itemNames", [])}
                      for u in p.get("units", [])],
            "traits": [{"name": t["name"], "num_units": t["num_units"], "tier_current": t.get("tier_current", 0)}
                       for t in p.get("traits", []) if t.get("tier_current", 0) > 0],
        } for p in info["participants"]],
    }}


def load_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="euw1")
    ap.add_argument("--region", default="europe")
    ap.add_argument("--tiers", default="challenger,grandmaster,master")
    ap.add_argument("--days", type=int, default=7, help="pedir solo partidas de los últimos N días (0 = sin límite)")
    ap.add_argument("--max-minutes", type=float, default=60, help="tiempo máximo de descarga; lo que falte se recoge la próxima vez")
    ap.add_argument("--first-run-count", type=int, default=10, help="partidas por jugador cuando aún no hay registro previo")
    ap.add_argument("--max-matches", type=int, default=0, help="(compatibilidad) sin uso")
    ap.add_argument("--per-player", type=int, default=0, help="(compatibilidad) sin uso")
    args = ap.parse_args()

    deadline = time.time() + args.max_minutes * 60
    os.makedirs(MATCHES, exist_ok=True)
    api = Riot(load_key())
    plat = f"https://{args.platform}.api.riotgames.com"
    reg = f"https://{args.region}.api.riotgames.com"

    # 1. Jugadores de Master+ con su número de partidas (victorias + derrotas)
    games, lp = {}, {}
    for tier in args.tiers.split(","):
        data = api.get(f"{plat}/tft/league/v1/{tier}") or {}
        for e in data.get("entries", []):
            if e.get("puuid"):
                games[e["puuid"]] = e.get("wins", 0) + e.get("losses", 0)
                lp[e["puuid"]] = e.get("leaguePoints", 0)
        print(f"{tier}: {len(data.get('entries', []))} jugadores", flush=True)
    if not games:
        sys.exit("No se encontraron jugadores.")

    # 2. Solo se pregunta a quien ha jugado desde la última vez (según el registro de partidas jugadas)
    ladder_path = os.path.join(RAW, "ladder.json")
    seen_games = load_json(ladder_path, {})
    skipped_path = os.path.join(RAW, "skipped.json")
    skipped = set(load_json(skipped_path, []))  # partidas no clasificatorias ya revisadas
    queue = []
    for puuid, n in games.items():
        if puuid not in seen_games:
            queue.append((0, -lp[puuid], puuid, args.first_run_count))  # sin registro: primero los de más puntos
        elif n > seen_games[puuid]:
            new = n - seen_games[puuid]
            queue.append((1, -new, puuid, min(new + 2, 40)))
    # Primero quien ha jugado (más partidas nuevas antes); luego los que aún no tienen registro
    queue.sort(key=lambda q: (-q[0], q[1]))
    active = sum(1 for q in queue if q[0] == 1)
    print(f"Jugadores que han jugado desde la última vez: {active} · sin registro previo: {len(queue) - active}", flush=True)

    start = window_start(args.days)
    since = f"&startTime={start}" if start else ""
    new_matches = queried = 0
    t0 = time.time()
    for k, (_, _, puuid, count) in enumerate(queue, 1):
        if time.time() > deadline:
            print("Tiempo máximo alcanzado: lo que falta se recogerá en la próxima ejecución.", flush=True)
            break
        ids = api.get(f"{reg}/tft/match/v1/matches/by-puuid/{puuid}/ids?count={count}{since}")
        if ids is None:
            continue
        for mid in ids:
            path = os.path.join(MATCHES, f"{mid}.json.gz")
            if mid in skipped or os.path.exists(path) or os.path.exists(path[:-3]):
                continue
            if time.time() > deadline:
                break
            m = api.get(f"{reg}/tft/match/v1/matches/{mid}")
            if not m:
                continue
            if m.get("info", {}).get("queue_id") == RANKED_QUEUE:
                with gzip.open(path, "wt") as f:
                    json.dump(compact(m), f, separators=(",", ":"))
                new_matches += 1
            else:
                skipped.add(mid)
        else:
            seen_games[puuid] = games[puuid]  # jugador al día solo si se revisaron todas sus partidas
        queried += 1
        if k % 100 == 0:
            mins = (time.time() - t0) / 60
            print(f"  {k}/{len(queue)} jugadores · {new_matches} partidas nuevas · {mins:.0f} min", flush=True)
            json.dump(seen_games, open(ladder_path, "w"))
            json.dump(sorted(skipped), open(skipped_path, "w"))

    json.dump(seen_games, open(ladder_path, "w"))
    json.dump(sorted(skipped), open(skipped_path, "w"))

    # Las partidas guardadas sin comprimir se reducen y se comprimen
    shrunk = 0
    for path in glob.glob(os.path.join(MATCHES, "*.json")):
        try:
            m = json.load(open(path))
            with gzip.open(path + ".gz", "wt") as f:
                json.dump(compact(m), f, separators=(",", ":"))
            os.remove(path)
            shrunk += 1
        except (ValueError, KeyError):
            pass
    total = len(glob.glob(os.path.join(MATCHES, "*.json.gz")))
    print(f"Listo: {new_matches} partidas nuevas · {queried} jugadores revisados · {total} partidas guardadas "
          f"({api.count} peticiones{f', {shrunk} partidas comprimidas' if shrunk else ''}).", flush=True)


if __name__ == "__main__":
    main()
