# Dick's Sporting Goods (dickssportinggoods.com) Product Scraper

Automated product extraction software tailored for **Dick's Sporting Goods** (`dickssportinggoods.com`). Extracts detailed product and variant information given any product page URL.

---

## 🚀 Features

- **Field Extraction**:
  - **Product Info**: Title, Brand, Product URL, Description, Rating, Review Count, Image Gallery.
  - **Identifiers**: Master SKU / Style ID, MPN, UPC / GTIN barcode.
  - **Pricing**: Current / Sale Price, List / Regular MSRP Price, Currency.
  - **Stock Status**: Overall in-stock/out-of-stock indicator.
  - **Available Options**: Full list of available Colors and Sizes.
  - **Variant Matrix**: Granular SKU, UPC, Size, Color, Price, and Stock status for each individual variant combination.
- **Resilient Multi-Layer Extraction**:
  1. **Schema.org JSON-LD Parser**: Extracts standard canonical product schema embedded in the page.
  2. **Hydration State Parser (`window.__INITIAL_STATE__`)**: Captures complete variant matrices, SKU tables, and inventory data before DOM rendering.
  3. **Visual DOM Fallbacks**: Fallback selectors for any custom or missing UI elements.
- **Anti-Bot & Automation Protection**:
  - Built on **Playwright** with stealth injection (`navigator.webdriver` masking, randomized viewports, human scroll emulation).
  - Supports HTTP / SOCKS5 proxies (residential proxies recommended for large-scale operations).
  - Configurable delays and optional headful mode for manual verification.
- **Export Formats**: JSON and CSV.

---

## 📦 Installation

1. Navigate to the project directory:
   ```bash
   cd C:\Users\dell\.gemini\antigravity\scratch\dicks_scraper
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install Playwright browser binaries:
   ```bash
   playwright install chromium
   ```

---

## 🛠️ Usage

### 1. Test Single Product URL
```bash
python cli.py --url "https://www.dickssportinggoods.com/p/nike-mens-air-zoom-pegasus-running-shoes/..."
```

### 2. Export to CSV or JSON
```bash
# Save to JSON
python cli.py --url "https://www.dickssportinggoods.com/p/..." --output product.json

# Save to CSV (flattens all variants into individual rows)
python cli.py --url "https://www.dickssportinggoods.com/p/..." --output product.csv
```

### 3. Batch Scraping from URL File
Create a `urls.txt` file with one product URL per line:
```bash
python cli.py --file urls.txt --output catalog.json --delay 4.0
```

### 4. Running with Proxies & Headful Mode
Dick's Sporting Goods utilizes Akamai Bot Manager. For high volume or if requests are blocked, use a residential proxy:
```bash
python cli.py --url "https://www.dickssportinggoods.com/p/..." --proxy "http://user:password@proxy.example.com:8000" --headful
```

---

## 🧪 Testing Parser Offline
You can test the parsing engine immediately using mock data without a live network request:
```bash
python test_parser.py
```

---

## 📋 Sample Output JSON
```json
{
  "url": "https://www.dickssportinggoods.com/p/...",
  "title": "Nike Men's Air Zoom Pegasus Running Shoes",
  "brand": "Nike",
  "sku": "24NIKMPGSMENXXXXX",
  "upc": "0194500123456",
  "mpn": "CW7183-001",
  "price": 129.99,
  "currency": "USD",
  "in_stock": true,
  "colors": ["Black/White", "Grey/Volt"],
  "sizes": ["9.5", "10.0"],
  "rating": 4.7,
  "review_count": 1280,
  "variants": [
    {
      "sku": "SKU-9901",
      "upc": "194500123457",
      "size": "9.5",
      "color": "Black/White",
      "price": 129.99,
      "in_stock": true
    }
  ]
}
```
