#!/usr/bin/env python3
from __future__ import annotations
import os
import subprocess
import sys

sys.path.insert(0, ".")

from poi_fusion import DEFAULT_CATEGORIES
from poi_fusion.regions import prompt_region


def _git_push(output_dir: str):
    print("\n=== AUTO PUSH ===")
    try:
        subprocess.run(["git", "add", output_dir], check=True)
        subprocess.run(["git", "commit", "-m", f"feat: POI fusion output {output_dir}"], check=False)
        subprocess.run(["git", "push", "origin", "test"], check=True)
        print("  -> Push completato su test")
    except Exception as e:
        print(f"  [WARN] Push fallito: {e}")


def main():
    region = prompt_region()

    output_dir = "output"
    if os.path.exists(output_dir):
        try:
            answer = input(f"\n'{output_dir}/' già esiste. Sovrascrivere? [s/N]: ").strip().lower() or "n"
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer != "s":
            print("Annullato.")
            return
        import shutil
        shutil.rmtree(output_dir)

    from poi_fusion import run_fusion
    merged, integrity = run_fusion(
        categories=DEFAULT_CATEGORIES,
        output_dir=output_dir,
        region=region,
    )

    print(f"\nDone. {len(merged)} POIs exported.")

    if len(merged) == 0:
        print("Nessun POI estratto. Push annullato.")
    elif integrity.ok:
        print("Integrità OK -> push automatico")
        _git_push(output_dir)
    else:
        print("Problemi di integrità rilevati. Correggi prima di pushare.")


if __name__ == "__main__":
    main()
