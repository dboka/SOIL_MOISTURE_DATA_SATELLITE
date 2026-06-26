from __future__ import annotations

import os
import sys
import eumdac


KEYWORDS = [
    "soil moisture",
    "Soil Moisture",
    "ASCAT",
    "SWI",
    "Soil Water Index",
    "H SAF",
    "HSAF",
    "Surface Soil Moisture",
]


def get_datastore():
    key = os.environ.get("EUMETSAT_CONSUMER_KEY")
    secret = os.environ.get("EUMETSAT_CONSUMER_SECRET")

    if not key or not secret:
        raise RuntimeError(
            "Missing credentials. Set:\n"
            'export EUMETSAT_CONSUMER_KEY="..."\n'
            'export EUMETSAT_CONSUMER_SECRET="..."'
        )

    token = eumdac.AccessToken((key, secret))
    print("Token created OK")

    return eumdac.DataStore(token)


def main():
    datastore = get_datastore()

    print("\nReading collections from EUMETSAT Data Store...\n")

    collections = list(datastore.collections)
    print(f"Total collections found: {len(collections)}\n")

    matches = []

    for col in collections:
        cid = getattr(col, "id", "") or ""
        title = getattr(col, "title", "") or ""
        abstract = getattr(col, "abstract", "") or ""

        text = f"{cid} {title} {abstract}"

        if any(k.lower() in text.lower() for k in KEYWORDS):
            matches.append(col)

    print(f"Matching collections: {len(matches)}\n")

    for i, col in enumerate(matches, start=1):
        cid = getattr(col, "id", "") or ""
        title = getattr(col, "title", "") or ""
        abstract = getattr(col, "abstract", "") or ""

        print("=" * 90)
        print(f"{i}. ID: {cid}")
        print(f"TITLE: {title}")

        if abstract:
            print("ABSTRACT:")
            print(abstract[:600].replace("\n", " "))

    if not matches:
        print("\nNo matches found. Next step: print all collection IDs.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:")
        print(repr(exc))
        sys.exit(1)