"""Construit les données de l'appli Révision BAC et BFEM (docs/revision/data/).

python revision/build.py               -> questions.json et config.json
python revision/build.py --codes 200   -> ajoute 200 codes premium ; la liste en clair
                                          est écrite hors du dépôt (public), seul le hachage est publié.
"""
import argparse
import hashlib
import json
import random
import secrets
from pathlib import Path

from questions import FREE, LEVELS, SUBJECTS

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "docs" / "revision" / "data"
HASHES = ROOT / "code_hashes.txt"
SALT = "rev-bac-bfem:"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O ni 1/I

# Réglages de vente (à remplir par Est : numéro Wave et WhatsApp au format 221XXXXXXXXX)
CONFIG = {
    "price_fcfa": 2000,
    "wave_number": "",
    "whatsapp": "",
    # classes d'examen : nom de l'examen et date indicative
    "exams": {"3e": ["BFEM", "2027-07-06"], "Tle L": ["BAC", "2027-07-01"], "Tle S": ["BAC", "2027-07-01"]},
}


def code_hash(code):
    return hashlib.sha256((SALT + code.strip().upper().replace(" ", "")).encode()).hexdigest()


def new_codes(n, dest):
    codes = ["".join(secrets.choice(ALPHABET) for _ in range(4)) + "-" + "".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(n)]
    with HASHES.open("a") as f:
        f.writelines(code_hash(c) + "\n" for c in codes)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a") as f:
        f.writelines(c + "\n" for c in codes)
    print(f"{n} codes ajoutés dans {dest}")


def build():
    questions, subjects = [], []
    for sid, levels, name, items in SUBJECTS:
        assert set(levels) <= set(LEVELS), sid
        subjects.append({"id": sid, "levels": levels, "name": name, "count": len(items), "free": min(FREE, len(items))})
        for i, (q, choices, a, ex) in enumerate(items):
            assert len(choices) == 4 and 0 <= a < 4, (sid, q)
            qid = f"{sid}-{i + 1}"
            # ordre des choix mélangé (fixe pour chaque question) pour que la bonne réponse ne soit pas toujours à la même place
            order = list(range(4))
            random.Random(qid).shuffle(order)
            questions.append({"id": qid, "s": sid, "q": q, "c": [choices[j] for j in order], "a": order.index(a), "e": ex, "free": i < FREE})
    hashes = HASHES.read_text().split() if HASHES.exists() else []
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "questions.json").write_text(json.dumps({"levels": LEVELS, "subjects": subjects, "questions": questions}, ensure_ascii=False, separators=(",", ":")))
    (OUT / "config.json").write_text(json.dumps({**CONFIG, "salt": SALT, "codes": hashes}, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(questions)} questions, {len(subjects)} matières, {len(hashes)} codes")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--codes", type=int, default=0)
    p.add_argument("--dest", default="/mnt/project-files/revision/codes-premium.txt")
    args = p.parse_args()
    if args.codes:
        new_codes(args.codes, args.dest)
    build()
