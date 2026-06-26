from __future__ import annotations

import os
import sys
import eumdac

KEYWORDS = [
    "soil",
    "moisture",
    "ascat",
    "swi",
    "ssm",
    "h saf",
    "hsaf",
    "metop",
]


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
    print("Listing collections quickly...\n")

    collections = list(datastore.collections)
    print(f"Total collections: {len(collections)}\n")

    matches = []

    for col in collections:
        cid = str(getattr(col, "id", "") or "")
        title = str(getattr(col, "title", "") or "")
        text = f"{cid} {title}".lower()

        if any(k in text for k in KEYWORDS):
            matches.append((cid, title))

    print(f"Matches: {len(matches)}\n")

    for i, (cid, title) in enumerate(matches, start=1):
        print(f"{i:03d} | {cid} | {title}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:")
        print(repr(exc))
        sys.exit(1)