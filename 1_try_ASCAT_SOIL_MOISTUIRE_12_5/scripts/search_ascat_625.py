from __future__ import annotations

import os
import sys
import eumdac

TARGET_TITLE_PARTS = [
    "ASCAT",
    "Surface Soil Moisture",
    "6.25",
    "Metop",
]

dtstart="2025-07-01T00:00:00Z",
dtend="2025-07-02T00:00:00Z",

def title_matches(title: str) -> bool:
    title_l = title.lower()
    return all(part.lower() in title_l for part in TARGET_TITLE_PARTS)


def main():
    key = os.environ.get("EUMETSAT_CONSUMER_KEY")
    secret = os.environ.get("EUMETSAT_CONSUMER_SECRET")

    if not key or not secret:
        raise RuntimeError(
            "Missing credentials. Set EUMETSAT_CONSUMER_KEY and EUMETSAT_CONSUMER_SECRET first."
        )

    token = eumdac.AccessToken((key, secret))
    datastore = eumdac.DataStore(token)

    print("Token OK")
    print("Searching collections by title...")

    collections = list(datastore.collections)

    matches = []
    for col in collections:
        title = str(getattr(col, "title", "") or "")
        if title_matches(title):
            matches.append(col)

    print(f"Matching collections: {len(matches)}")

    for i, col in enumerate(matches, start=1):
        title = str(getattr(col, "title", "") or "")
        print("\n" + "=" * 100)
        print(f"{i}. TITLE: {title}")
        print("OBJECT:", col)
        print("__dict__:", getattr(col, "__dict__", None))

        print(f"\nSearching products: {DTSTART} to {DTEND}")
        try:
            products = list(
                col.search(
                    dtstart=DTSTART,
                    dtend=DTEND,
                )
            )
            print("Products found:", len(products))

            for p in products[:10]:
                print("-" * 80)
                print("PRODUCT:", p)
                print("TITLE:", getattr(p, "title", None))
                print("ID:", getattr(p, "id", None))
                print("SENSING START:", getattr(p, "sensing_start", None))
                print("SENSING END:", getattr(p, "sensing_end", None))
                print("DICT:", getattr(p, "__dict__", None))

        except Exception as exc:
            print("Search error:", repr(exc))

    if not matches:
        print("\nNo exact 6.25 km Surface Soil Moisture collection found.")
        print("Relaxing search: print all ASCAT soil moisture collections.\n")

        for col in collections:
            title = str(getattr(col, "title", "") or "")
            title_l = title.lower()

            if "ascat" in title_l and "soil moisture" in title_l:
                print("TITLE:", title)
                print("OBJECT:", col)
                print("__dict__:", getattr(col, "__dict__", None))
                print("-" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:")
        print(repr(exc))
        sys.exit(1)