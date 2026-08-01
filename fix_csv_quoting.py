#!/usr/bin/env python3
"""
fix_csv_quoting.py — Quota i nomi con virgole nei CSV dati.

Righe malformate (es. `...,Gelateria, Pasticcieria, Caffetteria Infraportas,bar_cafe,...`)
hanno il nome non quotato: la virgola sposta le colonne e l'app legge l'URL sbagliato.
Qui si ricostruisce la riga come: lat,lng,id,"nome",building_type,type,url,page_type.

Solo righe con >8 campi (csv parser) e prime 3 colonne valide (lat,lng,id).
Le 4 colonne finali (building_type,type,url,page_type) sono considerate fisse.
Uso: python3 fix_csv_quoting.py
"""
import csv, os

REPO = os.path.dirname(os.path.abspath(__file__))
ITALIA = os.path.join(REPO, "italia")


def normalize_line(line):
    if line.startswith("#") or not line.strip():
        return line, False
    try:
        parts = next(csv.reader([line]))
    except Exception:
        return line, False
    if len(parts) == 8:
        return line, False
    if len(parts) < 8:
        return line, False
    lat, lng, pid = parts[0], parts[1], parts[2]
    try:
        float(lat)
        float(lng)
    except ValueError:
        return line, False
    tail = parts[-4:]
    name = ",".join(parts[3:len(parts) - 4])
    rebuilt = f"{lat},{lng},{pid},\"{name}\",{','.join(tail)}"
    return rebuilt + "\n", True


def main():
    changed = total = 0
    for root, dirs, files in os.walk(ITALIA):
        for f in files:
            if not f.endswith(".csv") or f in ("_citta.csv", "_regioni.csv"):
                continue
            p = os.path.join(root, f)
            out = []
            for line in open(p, encoding="utf-8", errors="replace"):
                nl, is_changed = normalize_line(line)
                out.append(nl)
                if is_changed:
                    changed += 1
                total += 1
            with open(p, "w", encoding="utf-8") as fh:
                fh.writelines(out)
    print(f"righe analizzate: {total}, righe normalizzate: {changed}")


if __name__ == "__main__":
    main()
