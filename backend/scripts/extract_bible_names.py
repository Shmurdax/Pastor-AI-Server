"""One-off helper: download BibleNLP names.tsv and write lowercase unique English lemmas."""
import csv
import os
from pathlib import Path
from urllib.request import urlretrieve

OUT = Path(__file__).resolve().parents[1] / "app" / "core" / "data" / "bible_names.txt"
TSV = Path(os.environ.get("TEMP", "/tmp")) / "names.tsv"


def main():
    url = "https://raw.githubusercontent.com/BibleNLP/biblical-names-data/main/names.tsv"
    if not TSV.is_file():
        urlretrieve(url, TSV)

    names: set[str] = set()
    with open(TSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            raw = (row.get("macula_eng") or "").strip()
            if not raw:
                continue
            for chunk in raw.replace(",", " ").split():
                w = chunk.strip("'-\u2019")
                if len(w) >= 2 and any(c.isalpha() for c in w):
                    names.add(w.lower())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for n in sorted(names):
            f.write(n + "\n")
    print(f"Wrote {len(names)} names to {OUT}")


if __name__ == "__main__":
    main()
