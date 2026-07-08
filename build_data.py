"""
원본 CSV(계약전현황조회_*.csv, 공급전현황조회_*.csv)를 읽어서
앱이 실제로 쓰는 3개의 Parquet 파일(계약전 / 공급전 / 계약공급연계)을 생성합니다.

이 스크립트는 반드시 "로컬"에서만 실행하세요.
Streamlit Cloud는 이 스크립트를 자동으로 실행해주지 않습니다 — 로컬에서 만든
parquet 파일을 git push 해야 클라우드 앱이 최신 데이터를 볼 수 있습니다.

원본 CSV가 갱신될 때마다:
    1) python build_data.py
    2) git add . && git commit -m "데이터 갱신" && git push
    3) Streamlit Cloud가 push를 감지해 자동 재배포
"""
import sys
from pathlib import Path
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")  # Windows(cp949) 콘솔에서 이모지 출력 에러 방지
sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    DATA_DIR,
    RAW_CONTRACT_PATTERN,
    RAW_SUPPLY_PATTERN,
    _latest_file,
    _read_csv_robust,
    _process_contract,
    _process_supply,
    _build_merged,
)


def save_parquet(df, name: str) -> Path:
    out_path = DATA_DIR / f"{name}_{date.today():%Y%m%d}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ {out_path.name}  ({len(df):,}행, {size_mb:.1f} MB)")
    return out_path


def main():
    fc = _latest_file(RAW_CONTRACT_PATTERN)
    fs = _latest_file(RAW_SUPPLY_PATTERN)

    if fc is None:
        print(f"❌ 계약전 원본 파일을 찾을 수 없습니다: {DATA_DIR / RAW_CONTRACT_PATTERN}")
        return
    if fs is None:
        print(f"❌ 공급전 원본 파일을 찾을 수 없습니다: {DATA_DIR / RAW_SUPPLY_PATTERN}")
        return

    print(f"계약전 원본: {fc.name}")
    print(f"공급전 원본: {fs.name}")

    df_c = _process_contract(_read_csv_robust(fc))
    df_s = _process_supply(_read_csv_robust(fs))

    dup_s = df_s["공급신청번호"].duplicated().sum()
    print(f"계약전 {len(df_c):,}행 / 공급전 {len(df_s):,}행 (공급전 중복 신청번호 {dup_s:,}건 — 계량기 단위라 정상)")

    print("\nParquet 저장 중...")
    save_parquet(df_c, "계약전")
    save_parquet(df_s, "공급전")

    df_merged = _build_merged(df_c, df_s)
    save_parquet(df_merged, "계약공급연계")

    print("\n완료! 이제 git add / commit / push 하면 Streamlit Cloud에 반영됩니다.")


if __name__ == "__main__":
    main()