import asyncio
import pandas as pd
from pathlib import Path
from playwright.async_api import async_playwright

OUT_CSV = Path("all_active_symbols.csv")
TARGET_URL = "https://www.nepalstock.com/company"
XHR_SUBSTR = "/api/nots/company/list"

async def fetch_symbols():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/118.0 Safari/537.36"
        )
        page = await context.new_page()

        data_holder = {}

        async def handle_response(response):
            if XHR_SUBSTR in response.url and response.status == 200:
                try:
                    data_holder["data"] = await response.json()
                except Exception as e:
                    print(f"⚠️ Failed to parse JSON: {e}")

        page.on("response", handle_response)

        await page.goto(TARGET_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)  # give JS time

        await context.close()
        await browser.close()

    if "data" not in data_holder:
        raise RuntimeError("Did not capture company list JSON.")

    df = pd.DataFrame(data_holder["data"])

    # ✅ Filter only active companies
    if "status" in df.columns:
        df = df[df["status"] == "A"]

    keep = [c for c in ["symbol", "companyName", "sectorName", "instrumentType"] if c in df.columns]
    df = df[keep].drop_duplicates().sort_values("symbol").reset_index(drop=True)
    return df

if __name__ == "__main__":
    try:
        df = asyncio.run(fetch_symbols())
        print(f"✅ Found {len(df)} active symbols")
        print(df.head())
        df.to_csv(OUT_CSV, index=False)
        print(f"📁 Saved to {OUT_CSV}")
    except Exception as e:
        print(f"❌ Failed: {e}")
        raise
