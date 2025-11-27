#!/usr/bin/env python3
import csv
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"
CURRENCY = "USD"
RI_TERMS = ("1 Year", "3 Years")
REQUEST_TIMEOUT = 15  # seconds
DEFAULT_REGION = "swedencentral"  # Fallback region if SKU entry omits one
DEFAULT_CAPACITY_GB = 1000  # Default storage amount for cost estimates
STORAGE_TYPES = ("LRS")  # Storage redundancy options to include

# Define the SKUs you want to query. Add more entries by providing product/meter filters.
STORAGE_SKUS = [
    {
        "friendly_name": "Blob Hot {redundancy} ({region})",
        "region": "swedencentral",
        "service_family": "Storage",
        "storage_types": STORAGE_TYPES,
        # PAYG data stored for Block Blob Hot LRS
        "paygo": {
            "product_name": "General Block Blob v2",
            "meter_contains_all": ["Hot {redundancy}", "Data Stored"],
            "price_type": None,  # priceType is null for these rows
        },
        # Reserved capacity for Hot LRS
        "ri": {
            "product_name": "Storage Reserved Capacity",
            "meter_contains_all": ["Hot", "{redundancy}", "Data Stored"],
            "price_type": None,  # priceType is null, reservationTerm differentiates 1Y/3Y
            "reservation_terms": RI_TERMS,
        },
    },
]


def build_filters(region, service_family, product_name=None, price_type=None, reservation_term=None):
    filters = [
        f"serviceFamily eq '{service_family}'",
        f"armRegionName eq '{region}'",
    ]
    if product_name:
        filters.append(f"productName eq '{product_name}'")
    if price_type:
        filters.append(f"priceType eq '{price_type}'")
    if reservation_term:
        filters.append(f"reservationTerm eq '{reservation_term}'")
    return filters


def fetch_prices(filter_parts, max_pages=None, timeout=REQUEST_TIMEOUT):
    """Call Azure Retail Prices API with the supplied OData filter parts.

    If max_pages is provided, we only iterate that many pages. This is handy for
    quick probes where we just want to see whether any results exist.
    """
    params = {
        "api-version": API_VERSION,
        "currencyCode": CURRENCY,
        "$filter": " and ".join(filter_parts),
    }

    items = []

    page_count = 0
    resp = requests.get(BASE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    items.extend(data.get("Items", []))
    page_count += 1

    next_link = data.get("NextPageLink")
    while next_link and (max_pages is None or page_count < max_pages):
        resp = requests.get(next_link, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("Items", []))
        next_link = data.get("NextPageLink")
        page_count += 1

    return items


def filter_by_meter_contains(items, contains_all=None):
    if not contains_all:
        return items
    contains_all = [c.lower() for c in contains_all]
    filtered = []
    for i in items:
        meter = (i.get("meterName") or "").lower()
        if all(snippet in meter for snippet in contains_all):
            filtered.append(i)
    return filtered


def pick_cheapest(items):
    """Pick the cheapest non-null unitPrice from a list of retail API items."""
    return min(
        (i for i in items if i.get("unitPrice") is not None),
        key=lambda i: i["unitPrice"],
        default=None,
    )


def fmt_price(val):
    return f"{val:.6f}" if val is not None else "n/a"


def probe_available_skus(region, service_family, hint=None, max_results=5):
    """Return a small sample of SKU/meter names for quick validation.

    This makes a single-page call (cheap) so we can confirm whether the filters
    we intend to use are in the right ballpark before attempting full pricing.
    """

    probe_filters = build_filters(region, service_family)
    items = fetch_prices(probe_filters, max_pages=1)

    if hint:
        hint = hint.lower()
        items = [
            i
            for i in items
            if hint in (i.get("meterName") or "").lower()
            or hint in (i.get("skuName") or "").lower()
        ]

    samples = []
    seen = set()
    for i in items:
        key = (i.get("productName"), i.get("skuName"), i.get("meterName"))
        if key in seen:
            continue
        seen.add(key)
        samples.append(
            {
                "productName": i.get("productName"),
                "skuName": i.get("skuName"),
                "meterName": i.get("meterName"),
                "priceType": i.get("priceType"),
            }
        )
        if len(samples) >= max_results:
            break

    return samples


def main():
    timestamp = datetime.now().strftime("%d%m%y_%H%M")
    output_csv = Path(__file__).with_name(f"storage_prices_{timestamp}.csv")
    print(f"CSV output path will be: {output_csv}")

    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "Friendly Name",
                "Storage Type",
                "Product Name",
                "Capacity (GB)",
                "Currency",
                "PayGo Unit Price",
                "PayGo Est @Capacity",
                "RI 1Yr Unit Price",
                "RI 1Yr Est @Capacity",
                "RI 3Yr Unit Price",
                "RI 3Yr Est @Capacity",
                "Unit of Measure",
                "Meter Name",
                "Sku Name",
            ]
        )

        header = (
            f"{'Friendly Name':24} {'Type':6} {'Product Name':36} {'Cap(GB)':8} {'Currency':8} "
            f"{'PayGo':12} {'PayGo Est':12} {'RI-1Y':12} {'RI-1Y Est':12} {'RI-3Y':12} {'RI-3Y Est':12} "
            f"{'Unit':12} {'Meter Name':35} {'Sku Name'}"
        )
        print(header)
        print("-" * len(header))

        for sku_conf in STORAGE_SKUS:
            storage_types = sku_conf.get("storage_types", STORAGE_TYPES)
            region = sku_conf.get("region", DEFAULT_REGION)
            capacity_gb = sku_conf.get("capacity_gb", DEFAULT_CAPACITY_GB)

            paygo_conf = sku_conf["paygo"]
            ri_conf = sku_conf["ri"]

            for redundancy in storage_types:
                friendly = sku_conf["friendly_name"].format(redundancy=redundancy, region=region)

                formatted_paygo_contains = None
                if paygo_conf.get("meter_contains_all"):
                    formatted_paygo_contains = [
                        token.format(redundancy=redundancy) for token in paygo_conf["meter_contains_all"]
                    ]

                try:
                    paygo_filters = build_filters(
                        region,
                        sku_conf["service_family"],
                        product_name=paygo_conf.get("product_name"),
                        price_type=paygo_conf.get("price_type"),
                    )
                    paygo_items = filter_by_meter_contains(
                        fetch_prices(paygo_filters), formatted_paygo_contains
                    )
                    if not paygo_items:
                        print(
                            f"[WARN] {friendly}: No PAYG matches for product='{paygo_conf.get('product_name')}' "
                            f"meter contains {formatted_paygo_contains}. Showing sample SKUs for validation."
                        )
                        for sample in probe_available_skus(
                            region,
                            sku_conf["service_family"],
                            hint=(formatted_paygo_contains or [None])[0],
                        ):
                            print(
                                "    product={productName}, sku={skuName}, meter={meterName}, priceType={priceType}".format(
                                    **{k: (v or '') for k, v in sample.items()}
                                )
                            )
                except requests.HTTPError as e:
                    print(f"[ERROR] {friendly}: PAYG lookup failed ({e})")
                    paygo_items = []
                except requests.RequestException as e:
                    print(f"[ERROR] {friendly}: PAYG lookup failed (network/timeout: {e})")
                    paygo_items = []

                paygo_pick = pick_cheapest(paygo_items)
                paygo_price = paygo_pick.get("unitPrice") if paygo_pick else None
                paygo_unit = paygo_pick.get("unitOfMeasure") if paygo_pick else None
                paygo_est = paygo_price * capacity_gb if paygo_price is not None else None

                formatted_ri_contains = None
                if ri_conf.get("meter_contains_all"):
                    formatted_ri_contains = [
                        token.format(redundancy=redundancy) for token in ri_conf["meter_contains_all"]
                    ]

                ri_prices = {}
                for term in ri_conf.get("reservation_terms", RI_TERMS):
                    try:
                        ri_filters = build_filters(
                            region,
                            sku_conf["service_family"],
                            product_name=ri_conf.get("product_name"),
                            price_type=ri_conf.get("price_type"),
                            reservation_term=term,
                        )
                        ri_items = filter_by_meter_contains(
                            fetch_prices(ri_filters), formatted_ri_contains
                        )
                        if not ri_items:
                            print(
                                f"[WARN] {friendly}: No RI matches for term '{term}' product='{ri_conf.get('product_name')}' "
                                f"meter contains {formatted_ri_contains}. Showing sample SKUs for validation."
                            )
                            for sample in probe_available_skus(
                                region,
                                sku_conf["service_family"],
                                hint=(formatted_ri_contains or [None])[0],
                            ):
                                print(
                                    "    product={productName}, sku={skuName}, meter={meterName}, priceType={priceType}".format(
                                        **{k: (v or '') for k, v in sample.items()}
                                    )
                                )
                        ri_pick = pick_cheapest(ri_items)
                        ri_prices[term] = (
                            ri_pick.get("unitPrice") if ri_pick else None,
                            ri_pick.get("unitOfMeasure") if ri_pick else None,
                        )
                    except requests.HTTPError as e:
                        print(f"[WARN] {friendly}: RI {term} lookup failed ({e}); column will show n/a.")
                        ri_prices[term] = (None, None)
                    except requests.RequestException as e:
                        print(f"[WARN] {friendly}: RI {term} lookup failed (network/timeout: {e}); column will show n/a.")
                        ri_prices[term] = (None, None)

                ri_1y_price, ri_1y_unit = ri_prices.get("1 Year", (None, None))
                ri_3y_price, ri_3y_unit = ri_prices.get("3 Years", (None, None))
                ri_1y_est = ri_1y_price * capacity_gb if ri_1y_price is not None else None
                ri_3y_est = ri_3y_price * capacity_gb if ri_3y_price is not None else None

                unit = paygo_unit or ri_1y_unit or ri_3y_unit or ""

                # Use the first available meterName/skuName for display
                sample_item = paygo_pick or {}
                meter_name = sample_item.get("meterName", "")
                sku_name = sample_item.get("skuName", "")

                product_name_display = paygo_conf.get("product_name") or ri_conf.get("product_name") or ""

                writer.writerow(
                    [
                        friendly,
                        redundancy,
                        product_name_display,
                        capacity_gb,
                        CURRENCY,
                        fmt_price(paygo_price),
                        fmt_price(paygo_est),
                        fmt_price(ri_1y_price),
                        fmt_price(ri_1y_est),
                        fmt_price(ri_3y_price),
                        fmt_price(ri_3y_est),
                        unit,
                        meter_name or "",
                        sku_name or "",
                    ]
                )

                print(
                    f"{friendly:24} {redundancy:6} {product_name_display:36} {capacity_gb:8} {CURRENCY:8} "
                    f"{fmt_price(paygo_price):12} {fmt_price(paygo_est):12} "
                    f"{fmt_price(ri_1y_price):12} {fmt_price(ri_1y_est):12} "
                    f"{fmt_price(ri_3y_price):12} {fmt_price(ri_3y_est):12} "
                    f"{unit:12} {meter_name or '':35} {sku_name or ''}"
                )


if __name__ == "__main__":
    main()
