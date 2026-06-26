from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zipfile import ZipFile, is_zipfile

import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CATALOG_DIR = DATA_DIR / "catalog"
EXTRACTED_DIR = DATA_DIR / "extracted"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment value: {name}")
    return value


def iso_day_start(value: str) -> str:
    parsed = datetime.combine(date.fromisoformat(value), time.min, timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def iso_day_end(value: str) -> str:
    parsed = datetime.combine(date.fromisoformat(value), time.max, timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.999Z")


def attr_filter(name: str, value: str) -> str:
    return (
        "Attributes/OData.CSC.StringAttribute/any("
        f"att:att/Name eq '{name}' and att/OData.CSC.StringAttribute/Value eq '{value}'"
        ")"
    )


def attr_map(product: dict[str, Any]) -> dict[str, Any]:
    return {item.get("Name"): item.get("Value") for item in product.get("Attributes", [])}


def product_extension(product: dict[str, Any]) -> str:
    attrs = attr_map(product)
    file_format = str(attrs.get("fileFormat", "")).lower()
    content_type = str(product.get("ContentType", "")).lower()
    if file_format == "cog" or "tiff" in content_type:
        return ".tif"
    if file_format == "nc" or "netcdf" in content_type:
        return ".nc"
    if "zip" in content_type:
        return ".zip"
    return ".bin"


def build_search_url(
    catalogue_endpoint: str,
    collection: str,
    dataset_identifier: str,
    file_format: str,
    start_date: str,
    end_date: str,
    limit: int,
) -> str:
    filters = [
        f"Collection/Name eq '{collection}'",
        attr_filter("datasetIdentifier", dataset_identifier),
        attr_filter("fileFormat", file_format),
        f"ContentDate/Start ge {iso_day_start(start_date)}",
        f"ContentDate/Start le {iso_day_end(end_date)}",
    ]
    query = " and ".join(filters)
    encoded_filter = quote(query, safe="'()/=:,. ")
    return (
        f"{catalogue_endpoint.rstrip('/')}/Products"
        f"?$count=true&$top={limit}&$expand=Attributes"
        "&$orderby=ContentDate/Start asc"
        f"&$filter={encoded_filter}"
    )


def search_products(
    catalogue_endpoint: str,
    collection: str,
    dataset_identifier: str,
    preferred_format: str,
    start_date: str,
    end_date: str,
    limit: int,
    fallback_format: str,
) -> tuple[list[dict[str, Any]], str, int, str]:
    last_url = ""
    for file_format in [preferred_format, fallback_format]:
        if not file_format:
            continue
        url = build_search_url(
            catalogue_endpoint,
            collection,
            dataset_identifier,
            file_format,
            start_date,
            end_date,
            limit,
        )
        last_url = url
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        payload = response.json()
        products = payload.get("value", [])
        count = int(payload.get("@odata.count", len(products)))
        if products:
            return products, file_format, count, url
    return [], preferred_format, 0, last_url


def get_access_token(token_endpoint: str, username: str, password: str, client_id: str) -> str:
    response = requests.post(
        token_endpoint,
        data={
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Token request failed with HTTP {response.status_code}: {response.text[:500]}"
        )
    return response.json()["access_token"]


def checksum_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_md5(product: dict[str, Any]) -> str | None:
    for item in product.get("Checksum", []):
        if item.get("Algorithm") == "MD5":
            return item.get("Value")
    return None


def download_product(
    product: dict[str, Any],
    download_endpoint: str,
    access_token: str,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    product_id = product["Id"]
    name = product["Name"]
    extension = product_extension(product)
    output_path = output_dir / f"{name}{extension}"
    if output_path.exists() and output_path.stat().st_size == product.get("ContentLength"):
        print(f"Already downloaded: {output_path}")
        return output_path

    url = f"{download_endpoint.rstrip('/')}/Products({product_id})/$value"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {access_token}"})
    with session.get(url, stream=True, timeout=180, allow_redirects=True) as response:
        if response.status_code >= 400:
            raise RuntimeError(
                f"Download failed for {name} with HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        with output_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)

    md5 = expected_md5(product)
    if md5:
        actual = checksum_md5(output_path)
        if actual.lower() != md5.lower():
            raise RuntimeError(f"MD5 mismatch for {output_path.name}: {actual} != {md5}")
    print(f"Downloaded: {output_path}")
    return output_path


def extract_swi_raster(downloaded_path: Path, band: str) -> Path:
    band_upper = band.upper()
    if not is_zipfile(downloaded_path):
        target = EXTRACTED_DIR / downloaded_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_size != downloaded_path.stat().st_size:
            target.write_bytes(downloaded_path.read_bytes())
        return target

    output_dir = EXTRACTED_DIR / downloaded_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(downloaded_path) as archive:
        raster_members = [
            item
            for item in archive.infolist()
            if not item.is_dir() and item.filename.lower().endswith((".tif", ".tiff"))
        ]
        band_members = [item for item in raster_members if band_upper in item.filename.upper()]
        selected = band_members[0] if band_members else raster_members[0]
        output_path = output_dir / Path(selected.filename).name
        if not output_path.exists() or output_path.stat().st_size != selected.file_size:
            with archive.open(selected) as src, output_path.open("wb") as dst:
                dst.write(src.read())
    print(f"Extracted {band_upper} raster: {output_path}")
    return output_path


def save_catalog(products: list[dict[str, Any]], used_format: str, query_url: str) -> None:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    (CATALOG_DIR / "last_query_url.txt").write_text(query_url, encoding="utf-8")
    (CATALOG_DIR / "products.json").write_text(
        json.dumps(products, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    rows = []
    for product in products:
        attrs = attr_map(product)
        rows.append(
            {
                "Id": product.get("Id"),
                "Name": product.get("Name"),
                "ContentDateStart": product.get("ContentDate", {}).get("Start"),
                "ContentLength": product.get("ContentLength"),
                "fileFormat": attrs.get("fileFormat", used_format),
                "datasetIdentifier": attrs.get("datasetIdentifier"),
                "S3Path": product.get("S3Path"),
            }
        )
    with (CATALOG_DIR / "products.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys() if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def main() -> int:
    load_env(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Search, download, and extract CLMS Soil Water Index v2 products from CDSE OData."
    )
    parser.add_argument("--start-date", default="2026-06-01", help="YYYY-MM-DD")
    parser.add_argument("--end-date", default="2026-06-23", help="YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--download-count", type=int, default=23)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--fallback-format", default="nc")
    parser.add_argument("--band", default=os.getenv("SWI_BAND", "SWI010"))
    args = parser.parse_args()

    products, used_format, total_count, query_url = search_products(
        catalogue_endpoint=env(
            "CDSE_CATALOGUE_ODATA_ENDPOINT",
            "https://catalogue.dataspace.copernicus.eu/odata/v1",
        ),
        collection=env("CDSE_COLLECTION", "CLMS"),
        dataset_identifier=env("CDSE_DATASET_IDENTIFIER", "swi_europe_1km_daily_v2"),
        preferred_format=env("CDSE_FILE_FORMAT", "cog"),
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit,
        fallback_format=args.fallback_format,
    )
    save_catalog(products, used_format, query_url)

    print(f"Search format: {used_format}")
    print(f"Matching products in catalogue: {total_count}")
    print(f"Fetched products: {len(products)}")
    for product in products[:10]:
        print(f"- {product['ContentDate']['Start']}: {product['Name']} ({product['Id']})")

    if not products or args.no_download or args.download_count <= 0:
        return 0

    access_token = get_access_token(
        token_endpoint=env(
            "CDSE_TOKEN_ENDPOINT",
            "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        ),
        username=env("CDSE_USER"),
        password=env("CDSE_PASSWORD"),
        client_id=env("CDSE_CLIENT_ID", "cdse-public"),
    )

    for product in products[: args.download_count]:
        downloaded = download_product(
            product,
            env("CDSE_DOWNLOAD_ODATA_ENDPOINT", "https://download.dataspace.copernicus.eu/odata/v1"),
            access_token,
            RAW_DIR,
        )
        extract_swi_raster(downloaded, args.band)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
