"""用 TWSE 官方 OpenAPI 抓台股上市股票當日收盤行情。

資料來源: https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
"""

import sys

import requests

STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


def roc_date_to_iso(roc_date: str) -> str:
    """把民國年日期字串(如 "1151113")轉成西元日期(如 "2026-11-13")。"""
    year = int(roc_date[:-4]) + 1911
    month = roc_date[-4:-2]
    day = roc_date[-2:]
    return f"{year}-{month}-{day}"


def fetch_stock_day_all() -> list[dict]:
    resp = requests.get(STOCK_DAY_ALL_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_stock_quote(stock_code: str) -> dict | None:
    for row in fetch_stock_day_all():
        if row["Code"] == stock_code:
            return row
    return None


def main() -> None:
    stock_code = sys.argv[1] if len(sys.argv) > 1 else "2330"
    quote = get_stock_quote(stock_code)

    if quote is None:
        print(f"找不到股票代號 {stock_code}")
        return

    print(f"{quote['Name']}({quote['Code']}) {roc_date_to_iso(quote['Date'])}")
    print(f"開盤: {quote['OpeningPrice']}")
    print(f"最高: {quote['HighestPrice']}")
    print(f"最低: {quote['LowestPrice']}")
    print(f"收盤: {quote['ClosingPrice']}")
    print(f"漲跌: {quote['Change']}")
    print(f"成交量: {quote['TradeVolume']} 股")


if __name__ == "__main__":
    main()
