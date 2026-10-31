"""
Polymarket data pipeline — demo
================================
Setup (VS Code terminal):
    pip install requests pandas dune-client python-dotenv
 
Optional (full-scale on-chain data via Dune):
    1. Free account at https://dune.com -> Settings -> API -> create key
    2. Create a file named .env next to this script containing:  DUNE_API_KEY=your_key
 
Run:
    python polymarket_pipeline.py
"""
 
import json
import os
import time
 
import pandas as pd
import requests
 
GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
OUT = "data"
os.makedirs(OUT, exist_ok=True)
 
 
# ---------------------------------------------------------------------------
# 1. Market metadata (Gamma API, no key)
# ---------------------------------------------------------------------------
def get_markets(end_min="2024-01-01", end_max="2026-06-30", max_pages=5, page=100):
    rows = []
    for i in range(max_pages):
        r = requests.get(
            f"{GAMMA}/markets",
            params={
                "closed": "true",
                "end_date_min": end_min,
                "end_date_max": end_max,
                "limit": page,
                "offset": i * page,
                "order": "volumeNum",
                "ascending": "false",
            },
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        time.sleep(0.2)
 
    df = pd.DataFrame(rows)
    keep = ["id", "conditionId", "question", "slug", "outcomes", "clobTokenIds",
            "createdAt", "endDate", "closedTime", "volumeNum", "negRisk", "events"]
    df = df[[c for c in keep if c in df.columns]].copy()
 
    # Gamma returns these as JSON strings
    for c in ["outcomes", "clobTokenIds"]:
        df[c] = df[c].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
 
    # category = first event tag label (if present)
    def first_tag(ev):
        try:
            return ev[0]["tags"][0]["label"]
        except Exception:
            return None
    df["category"] = df["events"].apply(first_tag) if "events" in df else None
    df = df.drop(columns=["events"], errors="ignore")
 
    for c in ["createdAt", "endDate", "closedTime"]:
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
 
    # "fixed, pre-announced resolution date": actual close within 1 day of scheduled end
    df["fixed_date"] = (df["closedTime"] - df["endDate"]).abs() <= pd.Timedelta(days=1)
    return df
 
 
# ---------------------------------------------------------------------------
# 2. Trades for one market (Data API, no key) — fine for testing / small samples
# ---------------------------------------------------------------------------
def get_trades(condition_id, page=500, max_pages=20):
    rows = []
    for i in range(max_pages):
        r = requests.get(
            f"{DATA}/trades",
            params={"market": condition_id, "limit": page, "offset": i * page,
                    "takerOnly": "false"},
            timeout=30,
        )
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        time.sleep(0.2)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df[["time", "proxyWallet", "side", "outcome", "price", "size",
               "conditionId", "transactionHash"]]
 
 
# ---------------------------------------------------------------------------
# 3. Daily wallet x position panel + one-sided (retail) filter
# ---------------------------------------------------------------------------
def build_panel(trades):
    t = trades.copy()
    t["signed"] = t["size"].where(t["side"] == "BUY", -t["size"])
    t["date"] = t["time"].dt.floor("D")
 
    daily = (t.groupby(["conditionId", "proxyWallet", "outcome", "date"])
               .agg(net_shares=("signed", "sum"),
                    n_trades=("signed", "size"),
                    vwap=("price", "mean"))
               .reset_index()
               .sort_values("date"))
    daily["position"] = daily.groupby(
        ["conditionId", "proxyWallet", "outcome"])["net_shares"].cumsum()
 
    # keep wallets that ever traded only ONE outcome in the market
    sides = t.groupby(["conditionId", "proxyWallet"])["outcome"].nunique()
    one_sided = sides[sides == 1].index
    daily = daily.set_index(["conditionId", "proxyWallet"]).loc[
        lambda d: d.index.isin(one_sided)].reset_index()
    return daily
 
 
# ---------------------------------------------------------------------------
# 4. (Optional) Full on-chain trades via Dune — use for the real sample
# ---------------------------------------------------------------------------
DUNE_SQL = """
SELECT block_time, tx_hash, condition_id, question, token_outcome,
       price, shares, amount, maker, taker
FROM polymarket_polygon.market_trades
WHERE block_time BETWEEN TIMESTAMP '2024-01-01' AND TIMESTAMP '2026-06-30'
  AND condition_id = {{condition_id}}
"""
# Paste DUNE_SQL into a new query on dune.com, add a text parameter
# `condition_id`, save it, and put its numeric ID below.
DUNE_QUERY_ID = None
 
 
def get_dune_trades(condition_id):
    from dotenv import load_dotenv
    from dune_client.client import DuneClient
    from dune_client.query import QueryBase
    from dune_client.types import QueryParameter
 
    load_dotenv()
    dune = DuneClient(os.environ["DUNE_API_KEY"])
    q = QueryBase(query_id=DUNE_QUERY_ID,
                  params=[QueryParameter.text_type("condition_id", condition_id)])
    return dune.run_query_dataframe(q)
 
 
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("1) Fetching markets ...")
    mkts = get_markets(max_pages=2)
    mkts.to_csv(f"{OUT}/markets.csv", index=False)
    print(mkts[["question", "category", "createdAt", "endDate",
                "closedTime", "fixed_date"]].head(), "\n")
 
    sample = mkts[mkts["fixed_date"]].iloc[0]
    print(f"2) Trades for: {sample['question']}")
    trades = get_trades(sample["conditionId"])
    trades.to_csv(f"{OUT}/trades_sample.csv", index=False)
    print(trades.head(), f"\n   {len(trades)} trades\n")
 
    print("3) Daily wallet x position panel (one-sided wallets) ...")
    panel = build_panel(trades)
    panel.to_csv(f"{OUT}/panel_sample.csv", index=False)
    print(panel.head(10))
    print(f"   {panel['proxyWallet'].nunique()} one-sided wallets")