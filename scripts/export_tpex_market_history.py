"""把上櫃(TPEx)股票過去一年的日線資料整理成 CSV,給量化分析用。

上市(TWSE)那份用官方 MI_INDEX 端點,一天一次就能拿到全市場;但上櫃沒有找到
對應的官方歷史端點(試過好幾種參數都抓不到資料),所以這邊改用 FinMind(第三方,
整理自官方資料)的 TaiwanStockPrice,一檔股票一次 API 就能拿整年資料。

免費額度未註冊是每小時 300 次,上櫃約 900 檔股票,抓完一輪要 3 小時多,所以這支
腳本比照 backfill_eps_history.py 的做法:分次跑、記錄進度,中斷後重跑會接著做。

用法: python scripts/export_tpex_market_history.py [--minutes 100] [--days 365]
"""

import argparse
import csv
import datetime
import json
import pathlib
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
SLEEP_SECONDS = 13

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_DATA_PATH = ROOT / "data" / "stock_day_all.json"
OUTPUT_PATH = ROOT / "data" / "exports" / "tpex_market_history_1y.csv"
STATE_PATH = ROOT / "data" / "exports" / "tpex_export_state.json"

SESSION = requests.Session()
SESSION.mount(
    "https://",
    HTTPAdapter(max_retries=Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])),
)

CSV_HEADER = [
    "date", "code", "name", "open", "high", "low", "close",
    "change_amount", "volume", "transaction_count", "value",
]


def tpex_codes() -> dict[str, str]:
    """回傳 {代號: 名稱},從現有的收盤行情資料取上櫃的部分。"""
    data = json.loads(STOCK_DATA_PATH.read_text(encoding="utf-8"))
    return {q["Code"]: q["Name"] for q in data["quotes"] if q["Market"] == "TPEx"}


def fetch_stock_year(code: str, start_date: str, end_date: str) -> list[dict] | None:
    resp = SESSION.get(
        FINMIND_URL,
        params={"dataset": "TaiwanStockPrice", "data_id": code, "start_date": start_date, "end_date": end_date},
        timeout=15,
    )
    if resp.status_code in (400, 402):
        return None  # 額度用完或這檔代號沒資料,跳過
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != 200:
        return None
    return body.get("data", [])


def load_state() -> set[str]:
    if STATE_PATH.exists():
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8"))["done"])
    return set()


def save_state(done: set[str]) -> None:
    STATE_PATH.write_text(json.dumps({"done": sorted(done)}, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=100)
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    deadline = time.monotonic() + args.minutes * 60
    codes = tpex_codes()
    done = load_state()
    remaining = [c for c in codes if c not in done]

    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=args.days)).isoformat()
    end_date = today.isoformat()

    print(f"上櫃共 {len(codes)} 檔,已完成 {len(done)} 檔,這次還有 {len(remaining)} 檔待處理")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUTPUT_PATH.exists()
    processed = 0

    with OUTPUT_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(CSV_HEADER)

        for code in remaining:
            if time.monotonic() >= deadline:
                print("時間到,存檔並結束這次執行")
                break

            rows = fetch_stock_year(code, start_date, end_date)
            if rows:
                for r in rows:
                    writer.writerow([
                        r["date"], code, codes[code],
                        r["open"], r["max"], r["min"], r["close"],
                        r["spread"], r["Trading_Volume"], r["Trading_turnover"], r["Trading_money"],
                    ])

            done.add(code)
            processed += 1
            if processed % 15 == 0:
                save_state(done)
                print(f"已處理 {processed} 檔(累計完成 {len(done)}/{len(codes)}),進度已存檔")

            time.sleep(SLEEP_SECONDS)

    save_state(done)
    print(f"這次共處理 {processed} 檔,累計完成 {len(done)}/{len(codes)}")


if __name__ == "__main__":
    main()
