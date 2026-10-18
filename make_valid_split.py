#!/usr/bin/env python3
"""Crée une partie validation à partir de train.txt (tirage reproductible).

Usage :
  python make_valid_split.py --train wildreceipt/train.txt --out-dir wildreceipt
Produit : valid.txt (150 reçus par défaut) et train_rest.txt (le reste de train).
test.txt n'est jamais modifié ni utilisé ici.
"""
import argparse
import random
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--valid-size", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    lines = [l for l in Path(args.train).read_text(encoding="utf-8").splitlines() if l.strip()]
    rng = random.Random(args.seed)
    rng.shuffle(lines)
    valid, rest = lines[:args.valid_size], lines[args.valid_size:]

    out = Path(args.out_dir)
    (out / "valid.txt").write_text("\n".join(valid) + "\n", encoding="utf-8")
    (out / "train_rest.txt").write_text("\n".join(rest) + "\n", encoding="utf-8")
    print(f"valid.txt: {len(valid)} reçus | train_rest.txt: {len(rest)} reçus | graine: {args.seed}")


if __name__ == "__main__":
    main()
