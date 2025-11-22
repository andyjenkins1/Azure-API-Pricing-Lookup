#!/usr/bin/env python3
import requests
import csv
from datetime import datetime
from pathlib import Path

# Region and currency settings
REGION = "swedencentral"      # Azure ARM region name
CURRENCY = "USD"              # Change to "USD", "EUR", etc. if you prefer

# Map friendly names to armSkuName values
VM_SKUS = {
    "NC16asT4 v3":       "Standard_NC16as_T4_v3",
    "D96ads v5":         "Standard_D96ads_v5",
    "NV36ads A10 v5":    "Standard_NV36ads_A10_v5",
    "D32ads v5":         "Standard_D32ads_v5",
    "NC24ads_A100_v4":   "Standard_NC24ads_A100_v4",
    "NC64asT4 v3":       "Standard_NC64as_T4_v3",
    "E32ads v5":         "Standard_E32ads_v5",
}

BASE_URL = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"  # per MS docs

def fetch_spot_prices_for_sku(arm_sku_name: str):
    """Call Azure Retail Prices API for a single armSkuName in Sweden Central, returning all Spot VM prices."""
    # Filter:
    # - Virtual Machines
    # - Specific region
    # - Specific armSkuName
    # - Spot prices (Consumption + meterName contains 'Spot')
    query = (
        f"serviceName eq 'Virtual Machines' and "
        f"armRegionName eq '{REGION}' and "
        f"armSkuName eq '{arm_sku_name}' and "
        f"priceType eq 'Consumption' and "
        f"contains(meterName, 'Spot')"
    )

    params = {
        "api-version": API_VERSION,
        "currencyCode": CURRENCY,
        "$filter": query,
    }

    items = []

    # First page
    resp = requests.get(BASE_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    items.extend(data.get("Items", []))

    # Handle pagination if needed
    next_link = data.get("NextPageLink")
    while next_link:
        resp = requests.get(next_link)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("Items", []))
        next_link = data.get("NextPageLink")

    return items


def fetch_paygo_prices_for_sku(arm_sku_name: str):
    """
    Call Azure Retail Prices API for a single armSkuName in Sweden Central, returning PAYG (non-Spot) prices.
    Note: the API doesn't like `not contains(...)`, so we fetch Consumption rows and drop Spot meters (and Dev/Test, promo) client-side.
    """
    # Filter:
    # - Virtual Machines
    # - Specific region
    # - Specific armSkuName
    # - PAYG prices (Consumption) – Spot filtered out in code
    query = (
        f"serviceName eq 'Virtual Machines' and "
        f"armRegionName eq '{REGION}' and "
        f"armSkuName eq '{arm_sku_name}' and "
        f"priceType eq 'Consumption'"
    )

    params = {
        "api-version": API_VERSION,
        "currencyCode": CURRENCY,
        "$filter": query,
    }

    items = []

    # First page
    resp = requests.get(BASE_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    items.extend(data.get("Items", []))

    # Handle pagination if needed
    next_link = data.get("NextPageLink")
    while next_link:
        resp = requests.get(next_link)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("Items", []))
        next_link = data.get("NextPageLink")

    disallowed = ("spot", "dev/test", "devtest", "promo", "low priority")
    filtered = []
    for i in items:
        meter = (i.get("meterName") or "").lower()
        if any(tag in meter for tag in disallowed):
            continue
        filtered.append(i)
    return filtered


def main():
    timestamp = datetime.now().strftime("%d%m%y_%H%M")
    output_csv = Path(__file__).with_name(f"spot_prices_{timestamp}.csv")
    print(f"CSV output path will be: {output_csv}")

    def fmt_price(val):
        return f"{val:.6f}" if val is not None else "n/a"

    def pick_cheapest_paygo(paygo_items):
        """Prefer 1 Hour meters; otherwise pick any cheapest non-null price."""
        one_hour = [i for i in paygo_items if (i.get("unitOfMeasure") or "").lower() == "1 hour"]
        pool = one_hour if one_hour else paygo_items
        cheapest = min(
            (i for i in pool if i.get("unitPrice") is not None),
            key=lambda i: i["unitPrice"],
            default=None,
        )
        if cheapest:
            return cheapest.get("unitPrice"), cheapest.get("unitOfMeasure")
        return None, None

    # Open CSV and write header
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "Friendly Name",
                "armSkuName",
                "Currency",
                "Spot Unit Price",
                "PayGo Unit Price",
                "Unit of Measure",
                "Region",
                "Meter Name",
                "Product Name",
            ]
        )

        # Print table header to console
        header = (
            f"{'Friendly Name':25} {'armSkuName':30} "
            f"{'Currency':8} {'Spot':12} {'PayGo':12} {'Unit':6} {'Region':15} {'Meter Name':30} {'Product Name'}"
        )
        print(header)
        print("-" * len(header))

        units_seen = set()

        for friendly_name, arm_sku in VM_SKUS.items():
            try:
                spot_items = fetch_spot_prices_for_sku(arm_sku)
            except requests.HTTPError as e:
                print(f"[ERROR] {friendly_name} ({arm_sku}): Spot HTTP error {e}")
                continue

            paygo_items = []
            try:
                paygo_items = fetch_paygo_prices_for_sku(arm_sku)
            except requests.HTTPError as e:
                print(f"[WARN] {friendly_name} ({arm_sku}): PayGo lookup failed ({e}); PayGo column will show n/a.")

            paygo_price, paygo_unit = pick_cheapest_paygo(paygo_items)

            if not spot_items:
                print(f"[NO DATA] {friendly_name} ({arm_sku}) – no Spot prices found in {REGION}")
                continue

            # There are often multiple rows (Linux vs Windows, Dev/Test vs normal, etc.)
            for item in spot_items:
                currency = item.get("currencyCode")
                price = item.get("unitPrice")
                unit = item.get("unitOfMeasure")
                region = item.get("armRegionName")
                meter = item.get("meterName")
                product_name = item.get("productName")

                units_seen.update(filter(None, [unit, paygo_unit]))

                if paygo_price is not None and price is not None and paygo_price < price:
                    print(f"[WARN] {friendly_name}: PAYG ({paygo_price}) is below Spot ({price}); verify filtering.")

                # Write to CSV
                writer.writerow(
                    [
                        friendly_name,
                        arm_sku,
                        currency,
                        fmt_price(price),
                        fmt_price(paygo_price),
                        unit or paygo_unit,
                        region,
                        meter,
                        product_name,
                    ]
                )

                # Also print to console
                print(
                    f"{friendly_name:25} {arm_sku:30} "
                    f"{currency:8} {fmt_price(price):12} {fmt_price(paygo_price):12} {unit or paygo_unit:6} {region:15} "
                    f"{meter:30} {product_name}"
                )

        # Confirm units for sanity
        if units_seen:
            print(f"\n[INFO] Units observed: {', '.join(sorted(units_seen))}")


if __name__ == "__main__":
    main()
