"""Comprueba si Riot ha publicado un parche nuevo y, si es así, actualiza data/patch.json.

La versión sale de Data Dragon (se actualiza el mismo día que el parche de TFT).
Escribe "changed=true|false" en $GITHUB_OUTPUT si existe, para que el workflow
sepa si tiene que actualizar los datos del juego.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH_FILE = os.path.join(ROOT, "data", "patch.json")
VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"


def major_minor(version):
    return ".".join(version.split(".")[:2])


def next_tft_label(label):
    """18.5 -> 18.6 (estimado: Riot no publica el número de parche de TFT en la API)."""
    try:
        s, p = label.split(".")
        return f"{s}.{int(p) + 1}"
    except ValueError:
        return label


def main():
    with urllib.request.urlopen(VERSIONS, timeout=30) as r:
        latest = json.load(r)[0]
    patch = json.load(open(PATCH_FILE, encoding="utf8"))
    changed = major_minor(latest) != major_minor(patch["version"])
    if changed:
        patch = {
            "version": latest,
            "label": next_tft_label(patch["label"]),
            "start": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with open(PATCH_FILE, "w", encoding="utf8") as f:
            json.dump(patch, f, ensure_ascii=False, indent=2)
        print(f"Parche nuevo: {latest} (TFT {patch['label']}), desde {patch['start']}")
    else:
        print(f"Sin parche nuevo (versión {latest})")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
