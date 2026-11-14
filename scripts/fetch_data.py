"""抓 TWSE(上市)與 TPEx(上櫃)官方 OpenAPI 的全市場收盤行情,存成給靜態網頁讀的 JSON。

輸出: data/stock_day_all.json
"""

import datetime
import json
import pathlib

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

SESSION = requests.Session()
SESSION.mount(
    "https://",
    HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])),
)

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_INDEX_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
TPEX_INDEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_index"
TWSE_VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TPEX_VALUATION_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
TWSE_EPS_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap14_L"
TPEX_EPS_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O"
OUTPUT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "stock_day_all.json"
EPS_HISTORY_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "eps_history.json"
PRICE_HISTORY_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "price_history.json"
PRICE_HISTORY_MAX_DAYS = 30


def roc_to_iso(roc_date: str) -> str:
    year = int(roc_date[:-4]) + 1911
    return f"{year}-{roc_date[-4:-2]}-{roc_date[-2:]}"


def fetch_twse() -> list[dict]:
    resp = SESSION.get(TWSE_URL, timeout=10)
    resp.raise_for_status()
    quotes = resp.json()
    for q in quotes:
        q["Market"] = "TWSE"
    return quotes


def fetch_tpex() -> list[dict]:
    """TPEx 的欄位名稱跟 TWSE 不同,轉成跟 TWSE 一致的格式。

    回傳資料裡代號 6 碼的是權證,不是股票,過濾掉。
    """
    resp = SESSION.get(TPEX_URL, timeout=10)
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
    resp = SESSION.get(TWSE_INDEX_URL, timeout=10)
    resp.raise_for_status()
    taiex = next(r for r in resp.json() if r["指數"] == "發行量加權股價指數")
    taiex_sign = "" if taiex["漲跌"] == "+" else "-"

    resp = SESSION.get(TPEX_INDEX_URL, timeout=10)
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

    resp = SESSION.get(TWSE_VALUATION_URL, timeout=10)
    resp.raise_for_status()
    for r in resp.json():
        valuations[r["Code"]] = {
            "PERatio": r["PEratio"],
            "DividendYield": r["DividendYield"],
            "PBRatio": r["PBratio"],
        }

    resp = SESSION.get(TPEX_VALUATION_URL, timeout=10)
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


def fetch_eps() -> dict[str, dict]:
    """抓最新一季的每股盈餘(EPS),用股票代號對應。

    TWSE 跟 TPEx 用字段名稱有全形/半形括號的差異,統一轉成同一個格式。
    """
    eps: dict[str, dict] = {}

    resp = SESSION.get(TWSE_EPS_URL, timeout=10)
    resp.raise_for_status()
    for r in resp.json():
        eps[r["公司代號"]] = {
            "EPS": r["基本每股盈餘(元)"],
            "NetIncome": r["稅後淨利"],
            "EPSYear": r["年度"],
            "EPSQuarter": r["季別"],
        }

    resp = SESSION.get(TPEX_EPS_URL, timeout=10)
    resp.raise_for_status()
    for r in resp.json():
        eps[r["SecuritiesCompanyCode"]] = {
            "EPS": r["基本每股盈餘"],
            "NetIncome": r["稅後淨利"],
            "EPSYear": r["Year"],
            "EPSQuarter": r["季別"],
        }

    return eps


def merge_eps(quotes: list[dict], eps: dict[str, dict]) -> None:
    for q in quotes:
        e = eps.get(q["Code"])
        if e:
            q.update(e)


def load_eps_history() -> dict[str, list[dict]]:
    if EPS_HISTORY_PATH.exists():
        return json.loads(EPS_HISTORY_PATH.read_text(encoding="utf-8"))
    return {}


def save_eps_history(history: dict[str, list[dict]]) -> None:
    EPS_HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def update_eps_history(history: dict[str, list[dict]], eps: dict[str, dict]) -> None:
    """把每次抓到的季 EPS 存進歷史記錄,同一季重複抓不會重複累積,只會更新數字(財報有時會追溯更正)。

    這個端點官方只給「最新一季」的快照,沒有歷史可以一次補,所以連續獲利年數
    只能靠長期、每季持續執行這支腳本慢慢累積,現在剛開始接,資料會隨時間變多。
    """
    for code, e in eps.items():
        year, quarter = e.get("EPSYear"), e.get("EPSQuarter")
        if not year or not quarter:
            continue
        records = history.setdefault(code, [])
        record = {"year": year, "quarter": quarter, "eps": e["EPS"], "netIncome": e["NetIncome"]}
        existing = next((r for r in records if r["year"] == year and r["quarter"] == quarter), None)
        if existing:
            existing.update(record)
        else:
            records.append(record)
        records.sort(key=lambda r: (r["year"], r["quarter"]))


def consecutive_profitable_years(records: list[dict]) -> int:
    """從最新完整年度(第4季累計淨利)往回算,連續幾年都賺錢。

    年度之間必須逐年相接,中間缺一年就視為資料不足,停止往回算。
    """
    annual = {r["year"]: r for r in records if r["quarter"] == "4"}
    years_desc = sorted(annual.keys(), key=int, reverse=True)

    count = 0
    expected_year = None
    for year in years_desc:
        if expected_year is not None and int(year) != expected_year:
            break
        try:
            net_income = float(annual[year]["netIncome"])
        except (TypeError, ValueError):
            break
        if net_income <= 0:
            break
        count += 1
        expected_year = int(year) - 1
    return count


def load_price_history() -> dict[str, list[list]]:
    if PRICE_HISTORY_PATH.exists():
        return json.loads(PRICE_HISTORY_PATH.read_text(encoding="utf-8"))
    return {}


def save_price_history(history: dict[str, list[list]]) -> None:
    PRICE_HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def update_price_history(history: dict[str, list[list]], quotes: list[dict]) -> None:
    """把今天的收盤價存進歷史記錄,每天呼叫一次慢慢累積,用來算乖離率(跟均線的偏離)。

    這邊沒有額外打 API 回補歷史,因為 STOCK_DAY_ALL 本身就只有當天的資料;
    歷史序列只能從今天開始,每天執行一次慢慢累積,累積不到門檻天數的均線不會顯示。
    """
    for q in quotes:
        close_raw = q.get("ClosingPrice")
        if not close_raw:
            continue
        try:
            close = float(close_raw)
        except ValueError:
            continue
        date_iso = roc_to_iso(q["Date"])
        records = history.setdefault(q["Code"], [])
        if records and records[-1][0] == date_iso:
            records[-1][1] = close
        else:
            records.append([date_iso, close])
        history[q["Code"]] = records[-PRICE_HISTORY_MAX_DAYS:]


def compute_bias(records: list[list], window: int) -> float | None:
    """算乖離率:(今天收盤價 - N 日均線) / N 日均線 * 100。資料不夠 N 天就回傳 None。"""
    if len(records) < window:
        return None
    closes = [r[1] for r in records[-window:]]
    moving_average = sum(closes) / window
    if not moving_average:
        return None
    latest_close = records[-1][1]
    return round((latest_close - moving_average) / moving_average * 100, 2)


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

    eps = fetch_eps()
    merge_eps(quotes, eps)

    eps_history = load_eps_history()
    update_eps_history(eps_history, eps)
    save_eps_history(eps_history)
    for q in quotes:
        records = eps_history.get(q["Code"], [])
        if records:
            q["EPSQuartersTracked"] = len(records)
            years = consecutive_profitable_years(records)
            if years:
                q["ConsecutiveProfitableYears"] = years

    price_history = load_price_history()
    update_price_history(price_history, quotes)
    save_price_history(price_history)
    for q in quotes:
        records = price_history.get(q["Code"], [])
        if records:
            q["PriceHistoryDaysTracked"] = len(records)
            for window in (6, 10, 20):
                bias = compute_bias(records, window)
                if bias is not None:
                    q[f"Bias{window}"] = bias

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
