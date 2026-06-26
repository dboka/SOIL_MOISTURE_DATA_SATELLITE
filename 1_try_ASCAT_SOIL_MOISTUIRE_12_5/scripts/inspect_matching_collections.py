from __future__ import annotations

import os
import sys
import eumdac

TARGET_WORDS = [
    "ASCAT Soil Moisture at 25 km Swath Grid in NRT - Metop",
    "ASCAT Soil Moisture at 12.5 km Swath Grid in NRT - Metop",
    "ASCAT Winds and Soil Moisture at 25 km Swath Grid - Metop",
]


def main():
    key = os.environ.get("EUMETSAT_CONSUMER_KEY")
    secret = os.environ.get("EUMETSAT_CONSUMER_SECRET")

    if not key or not secret:
        raise RuntimeError("Missing EUMETSAT credentials in environment variables.")

    token = eumdac.AccessToken((key, secret))
    datastore = eumdac.DataStore(token)

    collections = list(datastore.collections)

    for col in collections:
        title = str(getattr(col, "title", "") or "")

        if any(t.lower() in title.lower() for t in TARGET_WORDS):
            print("\n" + "=" * 100)
            print("TITLE:", title)
            print("OBJECT:", col)
            print("TYPE:", type(col))

            print("\n--- dir keys containing id/name/title/url/href ---")
            for name in dir(col):
                low = name.lower()
                if any(k in low for k in ["id", "name", "title", "url", "href", "self"]):
                    try:
                        value = getattr(col, name)
                    except Exception as exc:
                        value = f"<ERROR: {exc}>"
                    print(name, "=", value)

            print("\n--- __dict__ ---")
            print(getattr(col, "__dict__", None))

            print("\n--- try search one day directly from this collection object ---")
            try:
                products = list(
                    col.search(
                        dtstart="2024-08-01T00:00:00Z",
                        dtend="2024-08-02T00:00:00Z",
                    )
                )
                print("Products found:", len(products))
                for p in products[:5]:
                    print("PRODUCT:", p)
                    print("PRODUCT dict:", getattr(p, "__dict__", None))
            except Exception as exc:
                print("Search error:", repr(exc))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:")
        print(repr(exc))
        sys.exit(1)