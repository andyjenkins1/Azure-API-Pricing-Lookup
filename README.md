# Azure API Pricing Lookup

Small Python utilities that call the Azure Retail Prices API to capture pricing snapshots for common VM and storage SKUs.

## What's here
- `azure_pricing_lookup.py` — fetches Spot, PAYG, and Reserved Instance prices for the VM SKUs defined in `VM_SKUS`, printing a table and writing a timestamped CSV.
- `storage_pricing_lookup.py` — estimates storage costs (PAYG + reserved capacity) for the SKUs in `STORAGE_SKUS`, printing a table and writing a timestamped CSV.
- `paygo_hot_blob_price.py` — quick one-off that prints the PAYG Hot LRS per-GB price and the monthly cost for 1 PB in `swedencentral`.

## Setup
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install requests
```

## Usage
- VM pricing snapshot:
  ```bash
  python azure_pricing_lookup.py
  ```
  Adjust `VM_SKUS`, `REGION`, and `CURRENCY` at the top of the file as needed. Output CSV is named `spot_prices_<timestamp>.csv`.

- Storage pricing snapshot:
  ```bash
  python storage_pricing_lookup.py
  ```
  Tune `STORAGE_SKUS`, `DEFAULT_REGION`, `DEFAULT_CAPACITY_TB`, and `STORAGE_TYPES` to your needs. Output CSV is named `storage_prices_<timestamp>.csv`.

- Quick PAYG Hot LRS check:
  ```bash
  python paygo_hot_blob_price.py
  ```
  Prints region, product, meter, currency, per-unit price, and the monthly cost for 1 PB.

Both scripts use the `2023-01-01-preview` Azure Retail Prices API and default to `USD` currency and the `swedencentral` region; tweak the constants at the top of each file to change those defaults.
