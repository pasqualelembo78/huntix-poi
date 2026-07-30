#!/usr/bin/env python3
from __future__ import annotations
import os
import shutil
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
    mode = "fresh"
    if os.path.exists(output_dir):
        try:
            answer = input(f"\n'{output_dir}/' già esiste. [S]ovrascrivere, [A]ggiungere nuovi POI, [N]on fare nulla? [s/A/n]: ").strip().lower() or "a"
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer == "n":
            print("Annullato.")
            return
        if answer == "s":
            shutil.rmtree(output_dir)
            mode = "fresh"
        else:
            mode = "update"

    from poi_fusion import run_fusion
    merged, integrity = run_fusion(
        categories=DEFAULT_CATEGORIES,
        output_dir=output_dir,
        region=region,
        mode=mode,
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
