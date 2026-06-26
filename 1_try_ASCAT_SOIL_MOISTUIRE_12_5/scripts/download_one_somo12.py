from __future__ import annotations

import os
import shutil
from pathlib import Path

import eumdac

COLLECTION_ID = "EO:EUM:DAT:METOP:SOMO12"

DTSTART = "2025-07-01T20:00:00Z"
DTEND = "2025-07-02T00:30:00Z"

OUT_DIR = Path("data/raw/eumetsat_somo12")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    key = os.environ["EUMETSAT_CONSUMER_KEY"]
    secret = os.environ["EUMETSAT_CONSUMER_SECRET"]

    token = eumdac.AccessToken((key, secret))
    datastore = eumdac.DataStore(token)
    collection = datastore.get_collection(COLLECTION_ID)

    print("Collection:", collection.title)
    print("Searching:", DTSTART, "to", DTEND)

    products = list(collection.search(dtstart=DTSTART, dtend=DTEND))
    print("Products found:", len(products))

    if not products:
        raise RuntimeError("No products found")

    product = products[0]

    product_id = getattr(product, "_id", None) or str(product)
    print("Downloading product:", product_id)

    out_zip = OUT_DIR / f"{product_id}.zip"

    with product.open() as source:
        with open(out_zip, "wb") as target:
            shutil.copyfileobj(source, target)

    print("Saved:", out_zip)
    print("Size MB:", out_zip.stat().st_size / 1024 / 1024)


if __name__ == "__main__":
    main()