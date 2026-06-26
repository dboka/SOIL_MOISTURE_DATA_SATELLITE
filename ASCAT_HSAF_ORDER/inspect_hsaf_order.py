from __future__ import annotations

import argparse
import csv
import re
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TAR_PATTERN = "h28_*.tar.gz"
OUT_DIR = ROOT / "data"
RELEVANT_TILES = {"E054N024", "E054N030", "E060N024", "E060N030", "E066N024", "E066N030"}
NAME_RE = re.compile(
    r"ASCAT-(?P<sat>METOP[BC])-0\.5km-H28_.*?_LIIB_"
    r"(?P<created>\d{14})_(?P<sensing_start>\d{14})_(?P<sensing_end>\d{14})_EU_"
    r"(?P<tile>E\d{3}N\d{3})\.nc$"
)


def parse_name(name: str) -> dict[str, str]:
    match = NAME_RE.search(name)
    if not match:
        return {"name": name}
    row = match.groupdict()
    row["name"] = name
    row["date"] = row["sensing_start"][:8]
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory H SAF H28 order archives.")
    parser.add_argument("--extract-relevant", action="store_true")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    relevant_dir = out_dir / "extracted_relevant"
    inventory_rows = []

    for tar_path in sorted(ROOT.glob(TAR_PATTERN)):
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile() or not member.name.endswith(".nc"):
                    continue
                name = Path(member.name).name
                row = parse_name(name)
                row["archive"] = tar_path.name
                row["size"] = member.size
                row["relevant_to_latvia_grid"] = row.get("tile") in RELEVANT_TILES
                inventory_rows.append(row)

                if args.extract_relevant and row["relevant_to_latvia_grid"]:
                    target = relevant_dir / name
                    if not target.exists() or target.stat().st_size != member.size:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tar.extractfile(member) as src, target.open("wb") as dst:
                            dst.write(src.read())

    fieldnames = [
        "archive",
        "name",
        "date",
        "sat",
        "tile",
        "created",
        "sensing_start",
        "sensing_end",
        "size",
        "relevant_to_latvia_grid",
    ]
    inventory_path = out_dir / "hsaf_h28_inventory.csv"
    with inventory_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(inventory_rows)

    relevant = [row for row in inventory_rows if row["relevant_to_latvia_grid"]]
    print(f"Total NetCDF files: {len(inventory_rows)}")
    print(f"Latvia-relevant tile files: {len(relevant)}")
    print(f"Inventory written: {inventory_path}")
    if args.extract_relevant:
        print(f"Relevant files extracted to: {relevant_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
