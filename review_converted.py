#!/usr/bin/env python3
"""Contrôle manuel de la conversion : montre le JSON converti à côté de l'image.

Usage :
  python review_converted.py --jsonl ground_truth_valid.jsonl --root wildreceipt --n 10
Pour chaque reçu tiré au hasard : affiche les valeurs converties, ouvre l'image
(Windows), puis attend la touche Entrée. Ajoutez --no-open pour seulement afficher.
"""
import argparse
import json
import os
import random
from pathlib import Path


def show(d):
    print("=" * 70)
    print(d["meta"]["file"])
    m = d["merchant"]
    print(f"magasin   : {m['name']} | adresse : {m['address']} | tél : {m['phone']}")
    print(f"date/heure: {d['date']} {d['time']}")
    a = d["amounts"]
    print(f"montants  : sous-total={a['subtotal']} taxe={a['tax']} pourboire={a['tip']} total={a['total']}")
    for i, it in enumerate(d["items"]):
        print(f"  article {i + 1}: {it['description']!r} | qté={it['quantity']} | prix={it['price']}")
    if not d["items"]:
        print("  (aucun article)")
    if d["alternatives"]:
        print("alternatives:", json.dumps(d["alternatives"], ensure_ascii=False))
    if d["meta"]["conversion_notes"]:
        print("notes     :", d["meta"]["conversion_notes"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.jsonl, encoding="utf-8") if l.strip()]
    sample = random.Random(args.seed).sample(rows, min(args.n, len(rows)))
    for k, d in enumerate(sample, 1):
        print(f"\n--- reçu {k}/{len(sample)} ---")
        show(d)
        if args.no_open:
            continue
        img = Path(args.root) / d["meta"]["file"]
        if hasattr(os, "startfile") and img.exists():
            os.startfile(str(img))
        else:
            print("image à ouvrir à la main :", img)
        input("Comparez avec l'image, puis Entrée pour le suivant... ")


if __name__ == "__main__":
    main()
