"""用 TWSE 官方歷史全市場行情端點,把上市股票過去一年的每日 OHLCV 整理成一個 CSV。

跟 FinMind 那個「每檔股票打一次 API」的方案不同,這裡用的是官方 MI_INDEX 端點,
可以指定任意過去交易日,一次拿回「那一天全市場」的資料,所以是「每個交易日打一次 API」
(一年約 240 個交易日),不是「每檔股票打一次」(2292 檔),效率好很多,而且是第一手
政府資料,不依賴 FinMind 的免費額度。

只涵蓋上市(TWSE)。上櫃(TPEx)目前沒找到對應的官方歷史端點,之後要補再用 FinMind。

用法: python scripts/export_twse_market_history.py [--days 365] [--out FILE]
"""

import argparse
import csv
import datetime
import pathlib
import re
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TABLE_TITLE_KEYWORD = "每日收盤行情"
SLEEP_SECONDS = 2.5

SESSION = requests.Session()
SESSION.mount(
    "https://",
    HTTPAdapter(max_retries=Retry(total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])),
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "exports" / "twse_market_history_1y.csv"

CHANGE_SIGN_RE = re.compile(r">\s*([+-])\s*<")


def parse_change_sign(raw: str) -> str:
    match = CHANGE_SIGN_RE.search(raw or "")
    return match.group(1) if match else ""


def clean_number(raw: str) -> str:
    if raw is None:
        return ""
    value = raw.replace(",", "").strip()
    return "" if value in ("", "--", "---") else value


def fetch_day(date: datetime.date, attempts: int = 5) -> list[list[str]] | None:
    """抓一個交易日全市場收盤行情,不是交易日(假日/週末)回傳 None。

    這個網路環境偶爾會回傳空白或壞掉的回應(不是 HTTP 錯誤碼,單純內容是空的),
    用一般的 HTTP 重試機制(urllib3 Retry)抓不到這種狀況,所以這裡自己重試。
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = SESSION.get(
                MI_INDEX_URL,
                params={"date": date.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
                timeout=15,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("stat") != "OK":
                return None
            table = next((t for t in body.get("tables", []) if TABLE_TITLE_KEYWORD in (t.get("title") or "")), None)
            return table["data"] if table else None
        except (requests.exceptions.RequestException, ValueError) as e:
            last_error = e
            time.sleep(SLEEP_SECONDS * (attempt + 1))
    print(f"{date.isoformat()} 重試 {attempts} 次都失敗,略過這天: {last_error}")
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365, help="往回抓幾個日曆天(含假日,實際只對交易日有資料)")
    parser.add_argument("--start-date", type=str, default=None, help="指定起始日(YYYY-MM-DD),優先於 --days")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUTPUT, help="輸出 CSV 路徑")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today()
    if args.start_date:
        start = datetime.date.fromisoformat(args.start_date)
        dates = [start + datetime.timedelta(days=i) for i in range((today - start).days + 1)]
    else:
        dates = [today - datetime.timedelta(days=i) for i in range(args.days)]
    dates = [d for d in dates if d.weekday() < 5]  # 只打平日,跳過週六週日,假日另外靠 stat 判斷略過
    dates.sort()

    rows_written = 0
    trading_days = 0
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "date", "code", "name", "open", "high", "low", "close",
            "change_sign", "change_amount", "volume", "transaction_count", "value", "pe_ratio",
        ])

        for i, date in enumerate(dates):
            rows = fetch_day(date)
            if rows:
                trading_days += 1
                for r in rows:
                    writer.writerow([
                        date.isoformat(),
                        r[0].strip(),
                        r[1].strip(),
                        clean_number(r[5]),
                        clean_number(r[6]),
                        clean_number(r[7]),
                        clean_number(r[8]),
                        parse_change_sign(r[9]),
                        clean_number(r[10]),
                        clean_number(r[2]),
                        clean_number(r[3]),
                        clean_number(r[4]),
                        clean_number(r[15]) if len(r) > 15 else "",
                    ])
                    rows_written += 1
            if (i + 1) % 20 == 0:
                print(f"進度 {i + 1}/{len(dates)} 個日曆天,已有 {trading_days} 個交易日、{rows_written} 筆資料")
            time.sleep(SLEEP_SECONDS)

    print(f"完成,共 {trading_days} 個交易日、{rows_written} 筆資料,寫入 {args.out}")


if __name__ == "__main__":
    main()
