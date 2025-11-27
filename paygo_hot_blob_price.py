#!/usr/bin/env python3
"""Fetch PAYG price for Blob Hot LRS in Sweden Central and show 1 PB monthly cost."""

import requests

BASE_URL = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"
CURRENCY = "USD"
REGION = "swedencentral"
PRODUCT_NAME = "General Block Blob v2"
METER_MATCH = ("Hot LRS", "Data Stored")
CAPACITY_PB = 1
GB_PER_PB = 1_000_000  # Azure retail prices use decimal units


def fetch_items():
    params = {
        "api-version": API_VERSION,
        "currencyCode": CURRENCY,
        "$filter": " and ".join(
            [
                "serviceFamily eq 'Storage'",
                f"armRegionName eq '{REGION}'",
                f"productName eq '{PRODUCT_NAME}'",
            ]
        ),
    }
    resp = requests.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("Items", [])


def pick_paygo_hot_lrs(items):
    filtered = []
    for i in items:
        meter = (i.get("meterName") or "").lower()
        if all(snippet.lower() in meter for snippet in METER_MATCH):
            filtered.append(i)
    return min(filtered, key=lambda i: i["unitPrice"], default=None)


def main():
    items = fetch_items()
    pick = pick_paygo_hot_lrs(items)
    if not pick:
        raise SystemExit("No PAYG Hot LRS price found.")

    unit_price = pick["unitPrice"]
    unit = pick.get("unitOfMeasure", "GB/Month")
    monthly_cost = unit_price * GB_PER_PB * CAPACITY_PB

    print(f"Region: {REGION}")
    print(f"Product: {PRODUCT_NAME}")
    print(f"Meter: {pick.get('meterName')}")
    print(f"Currency: {CURRENCY}")
    print(f"Unit price: {unit_price} per {unit}")
    print(f"{CAPACITY_PB} PB monthly cost: {monthly_cost}")


if __name__ == "__main__":
    main()
