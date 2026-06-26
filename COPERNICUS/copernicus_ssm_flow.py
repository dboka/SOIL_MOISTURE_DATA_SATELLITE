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
PROCESSED_DIR = DATA_DIR / "processed"
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
        "&$orderby=ContentDate/Start desc"
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
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        payload = response.json()
        products = payload.get("value", [])
        count = int(payload.get("@odata.count", len(products)))
        if products:
            return products, file_format, count, url
    return [], preferred_format, 0, url


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
    with session.get(url, stream=True, timeout=120, allow_redirects=True) as response:
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


def extract_ssm_raster(downloaded_path: Path) -> Path:
    if not is_zipfile(downloaded_path):
        return downloaded_path

    output_dir = EXTRACTED_DIR / downloaded_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(downloaded_path) as archive:
        raster_members = [
            item
            for item in archive.infolist()
            if not item.is_dir() and item.filename.lower().endswith((".tif", ".tiff"))
        ]
        ssm_members = [item for item in raster_members if "-ssm_" in item.filename.lower()]
        selected = ssm_members[0] if ssm_members else raster_members[0]
        output_path = output_dir / Path(selected.filename).name
        if not output_path.exists() or output_path.stat().st_size != selected.file_size:
            with archive.open(selected) as src, output_path.open("wb") as dst:
                dst.write(src.read())

    print(f"Extracted raster: {output_path}")
    return output_path


def clip_cog_to_latvia(input_path: Path, bbox: tuple[float, float, float, float]) -> Path:
    import rasterio
    from rasterio.windows import from_bounds

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / f"{input_path.stem}_latvia.tif"
    min_lon, min_lat, max_lon, max_lat = bbox

    with rasterio.open(input_path) as src:
        window = from_bounds(min_lon, min_lat, max_lon, max_lat, src.transform)
        transform = src.window_transform(window)
        data = src.read(window=window, boundless=True, fill_value=src.nodata)
        profile = src.profile.copy()
        profile.update(
            {
                "driver": "GTiff",
                "height": data.shape[1],
                "width": data.shape[2],
                "transform": transform,
                "compress": "deflate",
            }
        )
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(data)
            dst.update_tags(**src.tags())
            dst.update_tags(1, **src.tags(1))
            dst.scales = src.scales
            dst.offsets = src.offsets

    print(f"Latvia crop written: {output_path}")
    return output_path


def raster_summary(path: Path) -> dict[str, Any]:
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        array = src.read(1, masked=True)
        valid = array.compressed().astype("float64")
        scale = src.scales[0] if src.scales and src.scales[0] else 1.0
        offset = src.offsets[0] if src.offsets and src.offsets[0] else 0.0
        valid_scaled = valid * scale + offset
        return {
            "path": str(path),
            "crs": str(src.crs),
            "bounds": tuple(round(v, 6) for v in src.bounds),
            "width": src.width,
            "height": src.height,
            "total_pixels": int(src.width * src.height),
            "valid_pixels": int(valid_scaled.size),
            "coverage_pct": float(valid_scaled.size / (src.width * src.height) * 100)
            if src.width and src.height
            else None,
            "units": src.tags(1).get("units"),
            "scale": float(scale),
            "offset": float(offset),
            "min": float(np.min(valid_scaled)) if valid_scaled.size else None,
            "mean": float(np.mean(valid_scaled)) if valid_scaled.size else None,
            "max": float(np.max(valid_scaled)) if valid_scaled.size else None,
        }


def save_processing_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / "processing_summary.csv"
    preferred = [
        "date",
        "product",
        "total_pixels",
        "valid_pixels",
        "coverage_pct",
        "units",
        "min",
        "mean",
        "max",
        "path",
    ]
    extra = [key for key in rows[0].keys() if key not in preferred]
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=preferred + extra)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Processing summary written: {output_path}")


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


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("LATVIA_BBOX must have four comma-separated values")
    return parts[0], parts[1], parts[2], parts[3]


def main() -> int:
    load_env(ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Search and optionally download CLMS Surface Soil Moisture products from CDSE OData."
    )
    parser.add_argument("--start-date", default="2026-06-01", help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=50, help="Maximum catalogue records to fetch")
    parser.add_argument("--download-count", type=int, default=1, help="How many products to download")
    parser.add_argument("--no-download", action="store_true", help="Only query the catalogue")
    parser.add_argument("--fallback-format", default="nc", help="Format to try if preferred format is empty")
    args = parser.parse_args()

    catalogue_endpoint = env(
        "CDSE_CATALOGUE_ODATA_ENDPOINT",
        "https://catalogue.dataspace.copernicus.eu/odata/v1",
    )
    download_endpoint = env(
        "CDSE_DOWNLOAD_ODATA_ENDPOINT",
        "https://download.dataspace.copernicus.eu/odata/v1",
    )
    token_endpoint = env(
        "CDSE_TOKEN_ENDPOINT",
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
    )
    collection = env("CDSE_COLLECTION", "CLMS")
    dataset_identifier = env("CDSE_DATASET_IDENTIFIER", "ssm_europe_1km_daily_v1")
    preferred_format = env("CDSE_FILE_FORMAT", "cog")

    products, used_format, total_count, query_url = search_products(
        catalogue_endpoint=catalogue_endpoint,
        collection=collection,
        dataset_identifier=dataset_identifier,
        preferred_format=preferred_format,
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
        token_endpoint=token_endpoint,
        username=env("CDSE_USER"),
        password=env("CDSE_PASSWORD"),
        client_id=env("CDSE_CLIENT_ID", "cdse-public"),
    )

    bbox = parse_bbox(env("LATVIA_BBOX", "20.5,55.6,28.5,58.1"))
    summaries = []
    for product in products[: args.download_count]:
        downloaded = download_product(product, download_endpoint, access_token, RAW_DIR)
        if product_extension(product) == ".tif":
            raster_path = extract_ssm_raster(downloaded)
            clipped = clip_cog_to_latvia(raster_path, bbox)
            summary = raster_summary(clipped)
            summary["date"] = product["ContentDate"]["Start"][:10]
            summary["product"] = product["Name"]
            summaries.append(summary)
            print(json.dumps(summary, indent=2))
            if summary["valid_pixels"] == 0:
                print("No valid SSM pixels inside Latvia bbox for this date.")
        else:
            print(f"Downloaded NetCDF; Latvia clipping is not run for this format yet: {downloaded}")

    save_processing_summary(summaries)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
