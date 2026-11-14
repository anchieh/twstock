"""抓 TWSE 官方 OpenAPI 的全市場收盤行情,存成給靜態網頁讀的 JSON。

輸出: data/stock_day_all.json
"""

import datetime
import json
import pathlib

import requests

STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
OUTPUT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "stock_day_all.json"


def main() -> None:
    resp = requests.get(STOCK_DAY_ALL_URL, timeout=10)
    resp.raise_for_status()
    quotes = resp.json()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "quotes": quotes,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"寫入 {len(quotes)} 筆資料到 {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
