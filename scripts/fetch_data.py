"""抓 TWSE(上市)與 TPEx(上櫃)官方 OpenAPI 的全市場收盤行情,存成給靜態網頁讀的 JSON。

輸出: data/stock_day_all.json
"""

import datetime
import json
import pathlib

import requests

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_INDEX_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
TPEX_INDEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_index"
TWSE_VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TPEX_VALUATION_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
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


def fetch_indices() -> list[dict]:
    """抓大盤指數:加權指數(TWSE)跟櫃買指數(TPEx)。"""
    resp = requests.get(TWSE_INDEX_URL, timeout=10)
    resp.raise_for_status()
    taiex = next(r for r in resp.json() if r["指數"] == "發行量加權股價指數")
    taiex_sign = "" if taiex["漲跌"] == "+" else "-"

    resp = requests.get(TPEX_INDEX_URL, timeout=10)
    resp.raise_for_status()
    tpex_latest = resp.json()[-1]
    tpex_close = float(tpex_latest["Close"])
    tpex_change = float(tpex_latest["Change"])
    tpex_prev_close = tpex_close - tpex_change
    tpex_percent = (tpex_change / tpex_prev_close * 100) if tpex_prev_close else 0
    tpex_percent_str = f"{'-' if tpex_percent < 0 else ''}{abs(tpex_percent):.2f}"

    return [
        {
            "name": "加權指數",
            "close": taiex["收盤指數"],
            "change": f"{taiex_sign}{taiex['漲跌點數']}",
            "changePercent": f"{taiex_sign}{taiex['漲跌百分比']}",
        },
        {
            "name": "櫃買指數",
            "close": tpex_latest["Close"],
            "change": tpex_latest["Change"],
            "changePercent": tpex_percent_str,
        },
    ]


def fetch_valuations() -> dict[str, dict]:
    """抓本益比/殖利率/股價淨值比,用股票代號對應,合併到收盤行情裡。"""
    valuations: dict[str, dict] = {}

    resp = requests.get(TWSE_VALUATION_URL, timeout=10)
    resp.raise_for_status()
    for r in resp.json():
        valuations[r["Code"]] = {
            "PERatio": r["PEratio"],
            "DividendYield": r["DividendYield"],
            "PBRatio": r["PBratio"],
        }

    resp = requests.get(TPEX_VALUATION_URL, timeout=10)
    resp.raise_for_status()
    for r in resp.json():
        valuations[r["SecuritiesCompanyCode"]] = {
            "PERatio": r["PriceEarningRatio"],
            "DividendYield": r["YieldRatio"],
            "PBRatio": r["PriceBookRatio"],
        }

    return valuations


def merge_valuations(quotes: list[dict], valuations: dict[str, dict]) -> None:
    for q in quotes:
        v = valuations.get(q["Code"])
        if v:
            q.update(v)


def market_averages(quotes: list[dict]) -> dict:
    """算全市場本益比與殖利率的平均值,給前端當篩選預設門檻。"""

    def valid_values(field: str) -> list[float]:
        values = []
        for q in quotes:
            raw = q.get(field)
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if value > 0:
                values.append(value)
        return values

    def median(values: list[float]) -> float | None:
        if not values:
            return None
        values = sorted(values)
        mid = len(values) // 2
        if len(values) % 2:
            return round(values[mid], 2)
        return round((values[mid - 1] + values[mid]) / 2, 2)

    return {
        "medianPERatio": median(valid_values("PERatio")),
        "medianDividendYield": median(valid_values("DividendYield")),
    }


def main() -> None:
    quotes = fetch_twse() + fetch_tpex()
    indices = fetch_indices()
    merge_valuations(quotes, fetch_valuations())
    averages = market_averages(quotes)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "indices": indices,
                "marketAverages": averages,
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
