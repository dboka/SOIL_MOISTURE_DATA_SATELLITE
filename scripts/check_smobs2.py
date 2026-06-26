from __future__ import annotations

import os
import sys
import eumdac

COLLECTION_ID = "EO:EUM:DAT:METOP:SMOBS2"

TEST_RANGES = [
    ("2025-07-01T00:00:00Z", "2025-07-02T00:00:00Z"),
    ("2024-07-01T00:00:00Z", "2024-07-02T00:00:00Z"),
    ("2023-07-01T00:00:00Z", "2023-07-02T00:00:00Z"),
]


def main():
    key = os.environ["EUMETSAT_CONSUMER_KEY"]
    secret = os.environ["EUMETSAT_CONSUMER_SECRET"]

    token = eumdac.AccessToken((key, secret))
    datastore = eumdac.DataStore(token)

    print("Trying collection:", COLLECTION_ID)
    collection = datastore.get_collection(COLLECTION_ID)

    print("\n=== COLLECTION ===")
    print("OBJECT:", collection)
    print("TITLE:", getattr(collection, "title", None))
    print("DICT:", getattr(collection, "__dict__", None))

    for start, end in TEST_RANGES:
        print("\n" + "=" * 100)
        print("Search:", start, "to", end)

        products = list(collection.search(dtstart=start, dtend=end))
        print("Products found:", len(products))

        for p in products[:10]:
            print("-" * 80)
            print("PRODUCT:", p)
            print("ID:", getattr(p, "_id", None))
            print("TITLE:", getattr(p, "title", None))
            print("SENSING START:", getattr(p, "sensing_start", None))
            print("SENSING END:", getattr(p, "sensing_end", None))
            print("DICT:", getattr(p, "__dict__", None))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:")
        print(repr(exc))
        sys.exit(1)