"""用 FinMind 免費 API 把 EPS 歷史回補進 data/eps_history.json,讓「連續獲利年數」不用等好幾年才有資料。

FinMind 官方 OpenAPI(t187ap14_L / mopsfin_t187ap14_O)只給最新一季的快照,沒有歷史可查,
所以連續獲利年數原本只能從現在開始,每季慢慢累積。FinMind(第三方,整理自 MOPS)有完整
歷史財報,免費額度(未註冊)是每小時 300 次,所以這支腳本:
  - 每次只處理一部分股票代號,避免超過額度
  - 處理進度存在 data/finmind_backfill_state.json,中斷後重跑會接著做,不會重複浪費額度
  - 每股票抓到的歷史財報,只在「有完整 4 季資料」的年度才算進年度淨利/EPS,避免算進沒結束的年度
  - 只補「原本就沒有的年度」,不覆蓋已經由官方資料(t187ap14_L)寫入的紀錄

用法: python scripts/backfill_eps_history.py [--minutes 100]
"""

import argparse
import json
import pathlib
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
START_DATE = "2014-01-01"
SLEEP_SECONDS = 13  # 免費額度每小時 300 次,平均 12 秒一次,留點緩衝

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_DATA_PATH = ROOT / "data" / "stock_day_all.json"
EPS_HISTORY_PATH = ROOT / "data" / "eps_history.json"
STATE_PATH = ROOT / "data" / "finmind_backfill_state.json"

SESSION = requests.Session()
SESSION.mount(
    "https://",
    HTTPAdapter(max_retries=Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])),
)


def load_json(path: pathlib.Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: pathlib.Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def codes_to_backfill() -> list[str]:
    stock_data = load_json(STOCK_DATA_PATH, {"quotes": []})
    return sorted({q["Code"] for q in stock_data["quotes"] if "EPS" in q})


class RateLimited(Exception):
    """FinMind 額度用完,跟「這檔代號真的沒財報資料」要分開處理,不能誤標成已完成。"""


def fetch_statements(code: str) -> list[dict] | None:
    resp = SESSION.get(
        FINMIND_URL,
        params={"dataset": "TaiwanStockFinancialStatements", "data_id": code, "start_date": START_DATE},
        timeout=15,
    )
    if resp.status_code == 402:
        raise RateLimited()
    if resp.status_code == 400:
        return None  # 這檔代號真的沒有財報資料(例如 ETF、下市),跳過且標記完成
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") == 402:
        raise RateLimited()
    if body.get("status") != 200:
        return None
    return body.get("data", [])


def annual_records_from_statements(rows: list[dict]) -> dict[str, dict]:
    """把逐季的 EPS/稅後淨利彙總成完整年度的年度 EPS/淨利,用 ROC 年度當 key。

    FinMind 在 2020 年把「NetIncome」欄位改名成「IncomeAfterTaxes」(數值一樣,只是改名),
    2014~2019 兩個名稱同時存在,2020 年之後只剩 IncomeAfterTaxes,所以只用這個欄位,
    避免兩個名稱重複加總。
    """
    by_year: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["type"] not in ("EPS", "IncomeAfterTaxes"):
            continue
        date = r["date"]  # 例如 "2024-09-30"
        quarter_end = date[5:]
        if quarter_end not in ("03-31", "06-30", "09-30", "12-31"):
            continue
        year = int(date[:4])
        year_entry = by_year.setdefault(year, {})
        quarters = year_entry.setdefault("quarters", set())
        quarters.add(quarter_end)
        year_entry[r["type"]] = year_entry.get(r["type"], 0) + r["value"]

    records = {}
    for year, entry in by_year.items():
        if len(entry.get("quarters", set())) != 4:
            continue  # 年度資料不完整(只有部分季別),不能算進連續獲利判斷
        if "EPS" not in entry or "IncomeAfterTaxes" not in entry:
            continue
        roc_year = str(year - 1911)
        records[roc_year] = {
            "year": roc_year,
            "quarter": "4",
            "eps": round(entry["EPS"], 2),
            "netIncome": entry["IncomeAfterTaxes"],
            "source": "finmind_backfill",
        }
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=100, help="這次最多跑幾分鐘,時間到就存檔退出")
    args = parser.parse_args()

    deadline = time.monotonic() + args.minutes * 60
    codes = codes_to_backfill()
    state = load_json(STATE_PATH, {"done": []})
    done = set(state["done"])
    eps_history = load_json(EPS_HISTORY_PATH, {})

    remaining = [c for c in codes if c not in done]
    print(f"總共 {len(codes)} 檔需要回補,已完成 {len(done)} 檔,這次還有 {len(remaining)} 檔待處理")

    processed_this_run = 0
    for code in remaining:
        if time.monotonic() >= deadline:
            print("時間到,存檔並結束這次執行")
            break

        try:
            rows = fetch_statements(code)
        except RateLimited:
            print(f"額度用完,停止這次執行,{code} 留給下次重試(不標記完成)")
            save_json(EPS_HISTORY_PATH, eps_history)
            save_json(STATE_PATH, {"done": sorted(done)})
            return

        if rows:
            annual = annual_records_from_statements(rows)
            existing = eps_history.setdefault(code, [])
            existing_years = {r["year"] for r in existing}
            for roc_year, record in annual.items():
                if roc_year not in existing_years:
                    existing.append(record)
            existing.sort(key=lambda r: (r["year"], r["quarter"]))

        done.add(code)
        processed_this_run += 1

        if processed_this_run % 15 == 0:
            save_json(EPS_HISTORY_PATH, eps_history)
            save_json(STATE_PATH, {"done": sorted(done)})
            print(f"已處理 {processed_this_run} 檔(累計完成 {len(done)}/{len(codes)}),進度已存檔")

        time.sleep(SLEEP_SECONDS)

    save_json(EPS_HISTORY_PATH, eps_history)
    save_json(STATE_PATH, {"done": sorted(done)})
    print(f"這次共處理 {processed_this_run} 檔,累計完成 {len(done)}/{len(codes)}")


if __name__ == "__main__":
    main()
