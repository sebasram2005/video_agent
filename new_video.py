#!/usr/bin/env python3
"""
new_video.py — Un solo comando para crear y subir un nuevo video.

Flujo:
  1. Cura la mejor historia disponible (auto)
  2. Hace push del JSON al repo
  3. GitHub Actions detecta el push y genera + sube el video automáticamente

Usage:
  python new_video.py
  python new_video.py --account A    # solo subreddits legales (CPC alto)
  python new_video.py --account B    # solo subreddits de relaciones
"""

import argparse
import subprocess
import sys
from pathlib import Path

from curator import curate


def git(args: list[str]) -> bool:
    result = subprocess.run(["git"] + args, cwd=Path(__file__).parent,
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [git error] {result.stderr.strip()}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Curar historia y disparar pipeline en GitHub Actions")
    parser.add_argument("--account", choices=["A", "B"], help="Filtrar por cuenta (A=legal, B=relaciones)")
    args = parser.parse_args()

    print("\n════════════════════════════════════════")
    print("  Paso 1/2 — Curando historia...")
    print("════════════════════════════════════════\n")

    story = curate(account=args.account, auto=True)
    if not story:
        print("\n  No se encontró historia válida. Intenta más tarde.")
        sys.exit(1)

    print(f"\n  Historia seleccionada: {story['title'][:70]}")
    print(f"  r/{story['subreddit']} • ⬆️ {story['score']:,}\n")

    print("════════════════════════════════════════")
    print("  Paso 2/2 — Enviando a GitHub Actions...")
    print("════════════════════════════════════════\n")

    git(["add", "data/stories_log.json", "output/curated/"])
    git(["commit", "-m", f"story: {story['subreddit']} — {story['title'][:60]}"])
    ok = git(["push"])

    if ok:
        print("  ✅ Push exitoso — GitHub Actions generará y subirá el video.")
        print("     Revisa el progreso en: https://github.com/sebasram2005/video_agent/actions\n")
    else:
        print("  ❌ Push falló. Verifica tu conexión o credenciales de git.")
        sys.exit(1)


if __name__ == "__main__":
    main()
