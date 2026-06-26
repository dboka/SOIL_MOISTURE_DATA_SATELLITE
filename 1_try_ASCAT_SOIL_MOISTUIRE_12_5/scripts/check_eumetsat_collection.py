from __future__ import annotations

import os
import sys
import eumdac

COLLECTION_ID = "EO:EUM:DAT:METOP:SOMO12"


def main():
    key = os.environ.get("EUMETSAT_CONSUMER_KEY")
    secret = os.environ.get("EUMETSAT_CONSUMER_SECRET")

    if not key or not secret:
        raise RuntimeError(
            "Missing credentials. Set EUMETSAT_CONSUMER_KEY and "
            "EUMETSAT_CONSUMER_SECRET first."
        )

    token = eumdac.AccessToken((key, secret))
    datastore = eumdac.DataStore(token)

    print("Token OK")
    print(f"Trying collection: {COLLECTION_ID}")

    collection = datastore.get_collection(COLLECTION_ID)

    print("\n=== COLLECTION ===")
    print("ID:", getattr(collection, "id", None))
    print("TITLE:", getattr(collection, "title", None))
    print("ABSTRACT:", str(getattr(collection, "abstract", ""))[:800])

    print("\nSearching products for 2024-08-01...")
    products = list(
        collection.search(
            dtstart="2026-06-01T00:00:00Z",
            dtend="2026-06-02T00:00:00Z",
        )
    )

    print("Products found:", len(products))

    for p in products[:10]:
        print("-" * 80)
        print("ID:", getattr(p, "id", None))
        print("TITLE:", getattr(p, "title", None))
        print("SENSING START:", getattr(p, "sensing_start", None))
        print("SENSING END:", getattr(p, "sensing_end", None))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:")
        print(repr(exc))
        sys.exit(1)