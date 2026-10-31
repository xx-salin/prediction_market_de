import requests, pandas as pd

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"

# 1. pick a closed, high-volume market
m = requests.get(f"{GAMMA}/markets", params={"closed": "true", "limit": 1,
                 "order": "volumeNum", "ascending": "false"}).json()[0]
print("Market:", m["question"])

# 2. its trades -> wallets
t = pd.DataFrame(requests.get(f"{DATA}/trades",
                 params={"market": m["conditionId"], "limit": 500}).json())
print("Unique wallets in this market:", t["proxyWallet"].nunique())
print(t["proxyWallet"].value_counts().head())

# 3. follow ONE wallet across all markets
w = t["proxyWallet"].value_counts().index[0]
u = pd.DataFrame(requests.get(f"{DATA}/trades", params={"user": w, "limit": 500}).json())
print(f"\nWallet {w}")
print("Trades:", len(u), "| Distinct markets:", u["conditionId"].nunique())
print(u[["timestamp", "title", "side", "outcome", "price", "size"]].head(10))

# 4. verify on-chain
print(f"\nOn-chain check: https://polygonscan.com/address/{w}")
print(f"Profile:        https://polymarket.com/profile/{w}")