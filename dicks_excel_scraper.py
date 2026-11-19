import asyncio
import os
import re
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd
from playwright.async_api import async_playwright, BrowserContext, Page

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("dicks_scraper")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

KNOWN_BRANDS = [
    "New Balance", "Under Armour", "The North Face", "Hydro Flask",
    "Brooks", "On Running", "Stanley", "YETI", "Nike", "adidas",
    "Hoka", "Carhartt", "Patagonia", "Columbia", "Callaway"
]

class DicksExcelScraper:
    """Automated batch scraper for Dick's Sporting Goods exporting directly to Excel (.xlsx)."""

    def __init__(self, headless: bool = False, proxy: Optional[str] = None, timeout_ms: int = 45000):
        self.headless = headless
        self.proxy = proxy
        self.timeout_ms = timeout_ms

    async def _setup_stealth(self, page: Page):
        """Mask automated browser fingerprints."""
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

    def parse_page_data(self, html: str, url: str) -> List[Dict[str, Any]]:
        """Extract all variant rows matching the Scheels 12-column standard."""
        rows = []

        # 1. Locate hasVariant JSON payload
        parsed_data = None
        has_variant_scripts = re.findall(r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', html, re.DOTALL)
        for s_txt in has_variant_scripts:
            if "hasVariant" in s_txt:
                try:
                    data = json.loads(s_txt.strip())
                    parsed_data = data[0] if isinstance(data, list) else (data.get("@graph", [data])[0] if "@graph" in data else data)
                    break
                except Exception:
                    continue

        if not parsed_data:
            # Fallback regex search for hasVariant block
            hv_match = re.search(r'"hasVariant"\s*:\s*(\[\s*\{.*?\}\s*\])', html, re.DOTALL)
            if hv_match:
                try:
                    parsed_data = {"hasVariant": json.loads(hv_match.group(1))}
                except Exception:
                    pass

        # 2. Extract Base Product Metadata
        base_title = "Product"
        if parsed_data and parsed_data.get("name"):
            base_title = parsed_data["name"]
        else:
            h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
            if h1_m:
                base_title = re.sub(r'<[^>]+>', '', h1_m.group(1)).strip()

        # Extract Brand
        brand = ""
        if parsed_data and parsed_data.get("brand"):
            b_obj = parsed_data["brand"]
            brand = b_obj.get("name", "") if isinstance(b_obj, dict) else str(b_obj)
        if not brand:
            brand_m = re.search(r'data-test="product-brand"[^>]*>(.*?)<', html, re.IGNORECASE)
            if brand_m:
                brand = brand_m.group(1).strip()
        if not brand:
            for kb in KNOWN_BRANDS:
                if re.match(r'^' + re.escape(kb), base_title, re.IGNORECASE):
                    brand = kb
                    break
        if not brand:
            brand = base_title.split()[0] if base_title else "Brand"

        # Extract Style / MPN
        style_mpn = ""
        if parsed_data and (parsed_data.get("mpn") or parsed_data.get("sku")):
            style_mpn = str(parsed_data.get("mpn") or parsed_data.get("sku"))
        if not style_mpn:
            style_m = re.search(r'Style\s*:\s*([A-Za-z0-9\-_]+)', html, re.IGNORECASE)
            if style_m:
                style_mpn = style_m.group(1).strip()
        if not style_mpn:
            url_slug_m = re.search(r'/([a-z0-9]+)(?:\?|$)', url, re.IGNORECASE)
            if url_slug_m:
                style_mpn = url_slug_m.group(1).upper()

        # 3. Collect Real 12-Digit Manufacturer Barcodes from GTIN14 / UPCs
        real_upc_list = []
        gtin_matches = re.findall(r'"Value"\s*:\s*"(?:00)?([0-9]{12})"', html)
        for u in gtin_matches:
            if u not in real_upc_list:
                real_upc_list.append(u)

        upcs_arr_matches = re.findall(r'"UPCs"\s*:\s*\[\s*"([0-9]{12})"', html)
        for u in upcs_arr_matches:
            if u not in real_upc_list:
                real_upc_list.append(u)

        # 4. Parse hasVariant items
        variants_list = (parsed_data and parsed_data.get("hasVariant")) or []
        logger.info(f"Discovered {len(variants_list)} variants and {len(real_upc_list)} real UPCs for: {base_title}")

        if variants_list:
            for idx, v in enumerate(variants_list):
                row_title = v.get("name") or base_title
                row_url = v.get("url") or url
                sku = str(v.get("sku") or v.get("productID") or (idx + 1))
                color = v.get("color") or "Standard"
                size = v.get("size") or "Standard"

                # Price
                offers = v.get("offers", {})
                price_num = float(offers.get("price", 0)) if offers.get("price") else 0.0
                price_str = f"${price_num:.2f}" if price_num > 0 else "$0.00"
                currency = offers.get("priceCurrency", "USD")

                # Stock
                avail = str(offers.get("availability", ""))
                if "OutOfStock" in avail:
                    stock_status = "Out of Stock"
                elif "InStoreOnly" in avail:
                    stock_status = "In Store Only"
                elif "InStock" in avail:
                    stock_status = "In Stock"
                else:
                    stock_status = "In Stock"

                # UPC
                upc = v.get("gtin13") or v.get("gtin12") or v.get("gtin") or v.get("upc")
                if not upc and "additionalProperty" in v and isinstance(v["additionalProperty"], list):
                    for prop in v["additionalProperty"]:
                        if re.search(r'upc|gtin|barcode', prop.get("name", ""), re.IGNORECASE):
                            upc = prop.get("value")
                            break
                if not upc:
                    upc = real_upc_list[idx] if idx < len(real_upc_list) else (real_upc_list[0] if realUpcList else "N/A")

                # Format clean 12 digits
                upc_str = str(upc)
                digits_m = re.search(r'[0-9]{12}', upc_str)
                if digits_m:
                    upc_str = digits_m.group(0)

                rows.append({
                    "Product URL": row_url,
                    "Product Title": row_title,
                    "Brand": brand,
                    "Style / MPN": style_mpn,
                    "Variant SKU": sku,
                    "UPC / GTIN": upc_str,
                    "Size": size,
                    "Color": color,
                    "Price": price_str,
                    "Regular Price": price_str,
                    "Currency": currency,
                    "Stock Status": stock_status
                })

        else:
            # Fallback for single variant product (tumbler or accessory)
            price_m = re.search(r'class="[^"]*product-price[^"]*"[^>]*>\s*\$?([0-9]+(?:\.[0-9]{2})?)', html)
            price_str = f"${float(price_m.group(1)):.2f}" if price_m else "$0.00"
            single_upc = real_upc_list[0] if real_upc_list else "N/A"

            rows.append({
                "Product URL": url,
                "Product Title": base_title,
                "Brand": brand,
                "Style / MPN": style_mpn,
                "Variant SKU": style_mpn,
                "UPC / GTIN": single_upc,
                "Size": "One Size",
                "Color": "Standard",
                "Price": price_str,
                "Regular Price": price_str,
                "Currency": "USD",
                "Stock Status": "In Stock"
            })

        return rows

    async def scrape_urls(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Scrape list of URLs using stealth Playwright browser."""
        all_results = []

        async with async_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized"
            ]
            proxy_dict = {"server": self.proxy} if self.proxy else None

            browser = await p.chromium.launch(
                headless=self.headless,
                args=launch_args,
                proxy=proxy_dict
            )

            context: BrowserContext = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US"
            )

            page = await context.new_page()
            await self._setup_stealth(page)

            for idx, url in enumerate(urls, 1):
                clean_url = url.strip()
                if not clean_url or clean_url.startswith("#"):
                    continue

                logger.info(f"[{idx}/{len(urls)}] Processing: {clean_url}")
                try:
                    await page.goto(clean_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    # Micro-scroll to trigger lazy loading of schemas
                    await page.evaluate("window.scrollBy({ top: 600, behavior: 'smooth' });")
                    await asyncio.sleep(2.5)

                    html = await page.content()

                    # Check for Geo-Block
                    if "We're sorry! The site is currently unavailable" in html or "waf_brand_header" in html:
                        logger.error(f"[!] GEO-BLOCK DETECTED by Dick's Sporting Goods on: {clean_url}")
                        logger.error("    Please ensure your US VPN (e.g. ProtonVPN US server) is ACTIVE!")
                        continue

                    rows = self.parse_page_data(html, clean_url)
                    all_results.extend(rows)
                    logger.info(f"    --> Extracted {len(rows)} variant row(s)")

                except Exception as e:
                    logger.error(f"Failed to scrape {clean_url}: {e}")

                if idx < len(urls):
                    await asyncio.sleep(1.5)

            await context.close()
            await browser.close()

        return all_results

def export_to_excel(rows: List[Dict[str, Any]], excel_path: str, csv_path: Optional[str] = None):
    """Save rows into a beautifully formatted Excel (.xlsx) and CSV file."""
    if not rows:
        logger.warning("No rows to export.")
        return

    df = pd.DataFrame(rows)

    # 1. Export Excel (.xlsx) with Text formatting for UPC to prevent 1.96E+11 corruption
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Dicks_Products")
        worksheet = writer.sheets["Dicks_Products"]

        # Format column widths and format UPC column as TEXT
        for col_idx, col_name in enumerate(df.columns, 1):
            max_len = max(df[col_name].astype(str).map(len).max(), len(col_name)) + 3
            col_letter = worksheet.cell(row=1, column=col_idx).column_letter
            worksheet.column_dimensions[col_letter].width = min(max_len, 45)

            # If UPC column, format all cells as Text
            if "UPC" in col_name.upper():
                for row_idx in range(2, len(df) + 2):
                    cell = worksheet.cell(row=row_idx, column=col_idx)
                    cell.number_format = "@"  # Excel text format

    logger.info(f"[SUCCESS] Exported {len(rows)} rows to Excel: {excel_path}")

    # 2. Export CSV (.csv) with safe text formatting
    if csv_path:
        csv_df = df.copy()
        # Ensure UPC is safe in CSV
        if "UPC / GTIN" in csv_df.columns:
            csv_df["UPC / GTIN"] = csv_df["UPC / GTIN"].apply(lambda u: f'="{u}"' if re.match(r'^[0-9]{10,14}$', str(u)) else u)
        csv_df.to_csv(csv_path, index=False, encoding="utf-8")
        logger.info(f"[SUCCESS] Exported {len(rows)} rows to CSV: {csv_path}")

async def main():
    print("=" * 65)
    print("      DICK'S SPORTING GOODS AUTOMATED EXCEL SCRAPER")
    print("=" * 65)
    print(" Input:  urls.txt (List of product URLs, one per line)")
    print(" Output: dicks_products.xlsx & dicks_products.csv")
    print(" Format: Scheels 12-Column Standard with Real Color x Size x UPC")
    print("-" * 65)

    urls_file = Path("urls.txt")
    if not urls_file.exists():
        # Create sample urls.txt
        sample_urls = [
            "https://www.dickssportinggoods.com/p/new-balance-womens-574-shoes-22nwbw574blktlmltftw/22nwbw574blktlmltftw",
            "https://www.dickssportinggoods.com/p/yeti-20-ozrambler-tumbler-with-magslider-lid-17yetarmblr20wmgsodr/17yetarmblr20wmgsodr",
            "https://www.dickssportinggoods.com/p/stanley-20-ozcaf-to-go-travel-mug-25stauhydr20zcftgtjam/25stauhydr20zcftgtjam"
        ]
        with open(urls_file, "w", encoding="utf-8") as f:
            f.write("\n".join(sample_urls) + "\n")
        print("[+] Created sample 'urls.txt' with 3 test products.")

    with open(urls_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not urls:
        print("[!] 'urls.txt' is empty. Please add product URLs and run again.")
        return

    print(f"[*] Found {len(urls)} URL(s) in urls.txt to scrape.")
    print("[*] Starting extraction (Please ensure US VPN is ON)...\n")

    is_headless = os.getenv("HEADLESS", "false").lower() == "true" or sys.platform != "win32"
    proxy_val = os.getenv("PROXY_URL") or None
    scraper = DicksExcelScraper(headless=is_headless, proxy=proxy_val)
    results = await scraper.scrape_urls(urls)

    if results:
        export_to_excel(results, "dicks_products.xlsx", "dicks_products.csv")
        print("\n" + "=" * 65)
        print(f"[✔] EXTRACTION COMPLETE: Total {len(results)} variant rows exported!")
        print("    1. Excel file: dicks_products.xlsx")
        print("    2. CSV file:   dicks_products.csv")
        print("=" * 65)
    else:
        print("[!] No data extracted. Please check network/VPN connection.")

if __name__ == "__main__":
    asyncio.run(main())
