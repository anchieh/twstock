"""把之前抓到的兩年歷史行情 CSV(data/exports/)轉成網站自己用的逐股歷史檔(data/history/<代號>.json)。

只跑一次,用來把「取回的資料」變成網站以後長期自己維護、不再依賴外部即時抓取的資料來源。
之後每天的資料會由 fetch_data.py 的 update_history_files() 繼續累積,這支腳本不會再被排程執行。

用法: python scripts/build_price_history.py
"""

import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "data" / "history"
SOURCE_CSVS = [
    ROOT / "data" / "exports" / "twse_market_history_2y.csv",
    ROOT / "data" / "exports" / "tpex_market_history_2y.csv",
]


def main() -> None:
    by_code: dict[str, list[list]] = {}
    for csv_path in SOURCE_CSVS:
        with csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    close = float(row["close"])
                except (ValueError, KeyError):
                    continue
                by_code.setdefault(row["code"], []).append([row["date"], close])

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    for code, records in by_code.items():
        records.sort(key=lambda r: r[0])
        (HISTORY_DIR / f"{code}.json").write_text(
            json.dumps(records, separators=(",", ":")), encoding="utf-8"
        )

    print(f"完成,共寫入 {len(by_code)} 檔股票的歷史資料到 {HISTORY_DIR}")


if __name__ == "__main__":
    main()
