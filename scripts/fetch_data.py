"""抓 TWSE(上市)與 TPEx(上櫃)官方 OpenAPI 的全市場收盤行情,存成給靜態網頁讀的 JSON。

輸出: data/stock_day_all.json
"""

import datetime
import json
import pathlib

import requests

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
OUTPUT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "stock_day_all.json"


def fetch_twse() -> list[dict]:
    resp = requests.get(TWSE_URL, timeout=10)
    resp.raise_for_status()
    quotes = resp.json()
    for q in quotes:
        q["Market"] = "TWSE"
    return quotes


def fetch_tpex() -> list[dict]:
    """TPEx 的欄位名稱跟 TWSE 不同,轉成跟 TWSE 一致的格式。

    回傳資料裡代號 6 碼的是權證,不是股票,過濾掉。
    """
    resp = requests.get(TPEX_URL, timeout=10)
    resp.raise_for_status()
    raw = resp.json()

    quotes = []
    for r in raw:
        code = r["SecuritiesCompanyCode"]
        if len(code) > 5:
            continue
        quotes.append(
            {
                "Date": r["Date"],
                "Code": code,
                "Name": r["CompanyName"],
                "TradeVolume": r["TradingShares"],
                "TradeValue": r["TransactionAmount"],
                "OpeningPrice": r["Open"].strip(),
                "HighestPrice": r["High"].strip(),
                "LowestPrice": r["Low"].strip(),
                "ClosingPrice": r["Close"].strip(),
                "Change": r["Change"].strip().lstrip("+"),
                "Transaction": r["TransactionNumber"],
                "Market": "TPEx",
            }
        )
    return quotes


def main() -> None:
    quotes = fetch_twse() + fetch_tpex()

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
