"""Descarga partidas clasificatorias de TFT de jugadores Master+ usando la API de Riot.

Uso:
  python3 scripts/riot_fetch.py [--platform euw1] [--region europe] [--max-matches 2000]

La clave se lee de .riot_key (en la raíz del proyecto) o de la variable RIOT_API_KEY.
Las partidas se guardan en data/raw/matches/ y no se vuelven a descargar si ya existen,
así que se puede interrumpir y reanudar.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
MATCHES = os.path.join(RAW, "matches")
RANKED_QUEUE = 1100


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="euw1")
    ap.add_argument("--region", default="europe")
    ap.add_argument("--max-matches", type=int, default=2000)
    ap.add_argument("--per-player", type=int, default=15)
    ap.add_argument("--tiers", default="challenger,grandmaster,master")
    args = ap.parse_args()

    os.makedirs(MATCHES, exist_ok=True)
    api = Riot(load_key())
    plat = f"https://{args.platform}.api.riotgames.com"
    reg = f"https://{args.region}.api.riotgames.com"

    # 1. Jugadores de alto nivel
    players = []
    for tier in args.tiers.split(","):
        data = api.get(f"{plat}/tft/league/v1/{tier}") or {}
        entries = sorted(data.get("entries", []), key=lambda e: -e.get("leaguePoints", 0))
        for e in entries:
            if e.get("puuid"):
                players.append(e["puuid"])
        print(f"{tier}: {len(entries)} jugadores", flush=True)
    players = list(dict.fromkeys(players))
    if not players:
        sys.exit("No se encontraron jugadores.")
    json.dump(players, open(os.path.join(RAW, "players.json"), "w"))

    # 2. IDs de partidas
    needed_players = min(len(players), max(1, args.max_matches * 8 // args.per_player // 6))
    match_ids = []
    seen = set()
    for i, puuid in enumerate(players[:needed_players], 1):
        ids = api.get(f"{reg}/tft/match/v1/matches/by-puuid/{puuid}/ids?count={args.per_player}") or []
        for mid in ids:
            if mid not in seen:
                seen.add(mid)
                match_ids.append(mid)
        if i % 25 == 0:
            print(f"  {i}/{needed_players} jugadores · {len(match_ids)} partidas encontradas", flush=True)
        if len(match_ids) >= args.max_matches * 1.3:
            break
    print(f"Partidas encontradas: {len(match_ids)}", flush=True)

    # 3. Detalle de partidas (se salta las ya descargadas)
    saved = 0
    start = time.time()
    for i, mid in enumerate(match_ids, 1):
        path = os.path.join(MATCHES, f"{mid}.json")
        if os.path.exists(path):
            saved += 1
        else:
            m = api.get(f"{reg}/tft/match/v1/matches/{mid}")
            if m and m.get("info", {}).get("queue_id") == RANKED_QUEUE:
                with open(path, "w") as f:
                    json.dump(m, f)
                saved += 1
        if i % 50 == 0:
            rate = i / max(1, time.time() - start)
            left = (min(len(match_ids), args.max_matches * 1.3) - i) / max(rate, 0.01)
            print(f"  {i}/{len(match_ids)} revisadas · {saved} clasificatorias guardadas · ~{left / 60:.0f} min restantes", flush=True)
        if saved >= args.max_matches:
            break

    print(f"Listo: {saved} partidas guardadas en data/raw/matches ({api.count} peticiones).", flush=True)


if __name__ == "__main__":
    main()
