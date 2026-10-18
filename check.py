#!/usr/bin/env python3
"""Vérifie le dossier WildReceipt avant de lancer le pipeline.

Contrôles :
- chaque image citée dans train.txt / test.txt existe sur le disque ;
- aucune image n'apparaît à la fois dans train et test (fuite de données exacte) ;
- nombre de reçus par fichier et nombre de dossiers d'images.

Usage (depuis n'importe où) :
  python check_dataset.py --root "C:/chemin/vers/le/dossier/wildreceipt"
Le dossier --root doit contenir train.txt, test.txt et le dossier image_files.
"""
import argparse
import json
from pathlib import Path


def load(path):
    names = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                names.append(json.loads(line)["file_name"])
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root)

    splits = {}
    for split in ("train", "test"):
        txt = root / f"{split}.txt"
        if not txt.exists():
            print(f"{split}.txt introuvable dans {root}")
            return
        splits[split] = load(txt)

    for split, names in splits.items():
        missing = [n for n in names if not (root / n).exists()]
        print(f"{split}: {len(names)} reçus, {len(names) - len(missing)} images trouvées, "
              f"{len(missing)} manquantes")
        for n in missing[:5]:
            print(f"   manquante : {n}")

    common = set(splits["train"]) & set(splits["test"])
    print(f"images communes à train et test : {len(common)}")

    img_dir = root / "image_files"
    if img_dir.exists():
        folders = [p for p in img_dir.iterdir() if p.is_dir()]
        print(f"dossiers dans image_files : {len(folders)}")
    else:
        print("dossier image_files introuvable")


if __name__ == "__main__":
    main()