from __future__ import annotations

import os
import eumdac

COLLECTION_ID = "EO:EUM:DAT:METOP:SOMO12"

TEST_RANGES = [
    ("2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"),
    ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
    ("2025-12-01T00:00:00Z", "2025-12-02T00:00:00Z"),
    ("2025-08-01T00:00:00Z", "2025-08-02T00:00:00Z"),
    ("2025-07-01T00:00:00Z", "2025-07-02T00:00:00Z"),
]

LATVIA_BBOX = [20.0, 55.0, 29.0, 59.0]  # west, south, east, north


def print_products(label, products):
    products = list(products)
    print("\n" + "=" * 100)
    print(label)
    print("Products found:", len(products))

    for p in products[:5]:
        print("-" * 80)
        print("PRODUCT:", p)
        print("TITLE:", getattr(p, "title", None))
        print("ID:", getattr(p, "id", None))
        print("SENSING START:", getattr(p, "sensing_start", None))
        print("SENSING END:", getattr(p, "sensing_end", None))
        print("DICT:", getattr(p, "__dict__", None))


def main():
    key = os.environ["EUMETSAT_CONSUMER_KEY"]
    secret = os.environ["EUMETSAT_CONSUMER_SECRET"]

    token = eumdac.AccessToken((key, secret))
    datastore = eumdac.DataStore(token)
    collection = datastore.get_collection(COLLECTION_ID)

    print("Collection object:", collection)
    print("Collection title:", collection.title)
    print("Collection dict:", getattr(collection, "__dict__", None))

    # 1. Try no filter, just first available products
    try:
        iterator = collection.search()
        first = []
        for i, product in enumerate(iterator):
            first.append(product)
            if i >= 4:
                break
        print_products("NO FILTER SEARCH", first)
    except Exception as exc:
        print("\nNO FILTER SEARCH ERROR:", repr(exc))

    # 2. Try date ranges
    for start, end in TEST_RANGES:
        try:
            products = collection.search(dtstart=start, dtend=end)
            print_products(f"DATE SEARCH dtstart={start}, dtend={end}", products)
        except Exception as exc:
            print("\nDATE SEARCH ERROR:", start, end, repr(exc))

    # 3. Try date + Latvia bbox
    for start, end in TEST_RANGES:
        try:
            products = collection.search(
                dtstart=start,
                dtend=end,
                bbox=LATVIA_BBOX,
            )
            print_products(f"DATE + LATVIA BBOX SEARCH {start} to {end}", products)
        except Exception as exc:
            print("\nDATE+BBOX SEARCH ERROR:", start, end, repr(exc))


if __name__ == "__main__":
    main()