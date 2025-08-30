import pandas as pd
import requests
from datetime import datetime
import time
import logging
from pathlib import Path
import os, json

# ---------------------------
# Config
# ---------------------------
SYMBOLS_FILE = "all_active_symbols.csv"
PARQUET_FILE = "ohlcv.parquet"
BASE_URL = "https://api.nepsetrading.com/historical-chart/daily/unadjusted"
REQUEST_DELAY = 1.2  # ✅ one request every 1.2 seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------
# Fetch OHLCV data from API
# ---------------------------
def fetch_data(symbol, start_date="1970-01-01", end_date=None):
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    url = f"{BASE_URL}?code={symbol}&from={start_date}&to={end_date}"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("s") != "ok":
            logging.warning(f"⚠️ No data for {symbol} (status={data.get('s')})")
            return None

        ts = data["t"]
        # ✅ keep as pandas datetime64[ns] (no Python date objects)
        dates = pd.to_datetime(ts, unit="s").normalize()

        df = pd.DataFrame({
            "date": dates,
            "symbol": symbol,
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
            "volume": data["v"],
        })
        return df
    except Exception as e:
        logging.error(f"❌ Error fetching {symbol}: {e}")
        return None

# ---------------------------
# Main updater
# ---------------------------
def update_parquet():
    # Load existing DB if exists
    if Path(PARQUET_FILE).exists():
        all_data = pd.read_parquet(PARQUET_FILE)
        logging.info(f"📂 Loaded {len(all_data)} rows from {PARQUET_FILE}")
    else:
        all_data = pd.DataFrame()

    # Load active symbols (equity only)
    df_symbols = pd.read_csv(SYMBOLS_FILE)
    symbols = df_symbols[df_symbols["instrumentType"].str.lower() == "equity"]["symbol"].unique()
    logging.info(f"✅ {len(symbols)} active equity symbols loaded")

    updated_frames = []
    today = datetime.now().strftime("%Y-%m-%d")

    for idx, sym in enumerate(symbols, 1):
        if not all_data.empty and sym in all_data["symbol"].values:
            last_date = all_data.loc[all_data["symbol"] == sym, "date"].max()
            start_date = (pd.to_datetime(last_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start_date = "1970-01-01"

        logging.info(f"[{idx}/{len(symbols)}] {sym}: fetching from {start_date} → {today}")
        df_new = fetch_data(sym, start_date, today)
        if df_new is not None and not df_new.empty:
            updated_frames.append(df_new)

        time.sleep(REQUEST_DELAY)

    if updated_frames:
        df_new_all = pd.concat(updated_frames, ignore_index=True)
        all_data = pd.concat([all_data, df_new_all], ignore_index=True)
        all_data.drop_duplicates(subset=["date", "symbol"], inplace=True)
        all_data.to_parquet(PARQUET_FILE, index=False)
        logging.info(f"💾 Updated {PARQUET_FILE} → {len(all_data)} rows")
    else:
        logging.info("ℹ️ No new data to update")

    # ---------------------------
    # Export per-symbol JSONs
    # ---------------------------
    outdir = Path("json")
    outdir.mkdir(exist_ok=True)

    for sym, sdf in all_data.groupby("symbol"):
        sdf = sdf.sort_values("date")

        # ✅ TradingView-like payload: NO raw datetime objects
        # Vectorized epoch seconds (UTC-naive): datetime64[ns] -> int64 ns -> sec
        t = (pd.to_datetime(sdf["date"]).astype("int64") // 10**9).tolist()

        data = {
            "symbol": sym,
            "s": "ok",
            "t": t,
            "o": [float(x) for x in sdf["open"].tolist()],
            "h": [float(x) for x in sdf["high"].tolist()],
            "l": [float(x) for x in sdf["low"].tolist()],
            "c": [float(x) for x in sdf["close"].tolist()],
            "v": [int(x) for x in sdf["volume"].tolist()],
        }

        # ✅ sanitize filename WITHOUT regex (your ask)
        safe_sym = sym.replace("/", "_").replace("\\", "_")
        (outdir / f"{safe_sym}.json").write_text(
            json.dumps(data, separators=(",", ":")),  # compact JSON
            encoding="utf-8"
        )
        logging.info(f"📁 Saved json/{safe_sym}.json")


if __name__ == "__main__":
    update_parquet()
