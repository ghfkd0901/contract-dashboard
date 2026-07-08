"""
계약전 / 공급전 원본 CSV를 읽어 미리 LEFT JOIN 한 결과를
data 폴더에 CSV로 저장합니다.

원본 데이터(계약전현황조회_*.csv, 공급전현황조회_*.csv)가 갱신될 때마다
이 스크립트를 다시 실행해서 매칭 결과 파일을 새로 만들어주세요.
앱은 이 파일을 읽기만 하고, merge는 하지 않습니다.

실행: python build_merged_data.py
"""
import sys
from pathlib import Path
from datetime import date

# Windows 콘솔(cp949)에서 이모지 출력 시 UnicodeEncodeError 방지
sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    DATA_DIR,
    CONTRACT_PATTERN,
    SUPPLY_PATTERN,
    _latest_file,
    _read_csv_robust,
    _process_contract,
    _process_supply,
    _build_merged,
)


def main():
    fc = _latest_file(CONTRACT_PATTERN)
    fs = _latest_file(SUPPLY_PATTERN)

    if fc is None:
        print(f"❌ 계약전 파일을 찾을 수 없습니다: {DATA_DIR / CONTRACT_PATTERN}")
        return
    if fs is None:
        print(f"❌ 공급전 파일을 찾을 수 없습니다: {DATA_DIR / SUPPLY_PATTERN}")
        return

    print(f"계약전 원본: {fc.name}")
    print(f"공급전 원본: {fs.name}")

    df_c = _process_contract(_read_csv_robust(fc))
    df_s = _process_supply(_read_csv_robust(fs))

    # ── 중복키 체크: 머지 결과가 비정상적으로 불어나는지 미리 확인 ──
    dup_c = df_c["공급신청번호"].duplicated().sum()
    dup_s = df_s["공급신청번호"].duplicated().sum()
    uniq_c = df_c["공급신청번호"].nunique()
    uniq_s = df_s["공급신청번호"].nunique()
    print(f"계약전 {len(df_c):,}행 (고유 신청번호 {uniq_c:,}개, 중복 {dup_c:,}건)")
    print(f"공급전 {len(df_s):,}행 (고유 신청번호 {uniq_s:,}개, 중복 {dup_s:,}건)")

    print("머지 중...")
    df_merged = _build_merged(df_c, df_s)
    print(f"머지 결과: {len(df_merged):,}행")
    print(
        "  ※ 공급계약(계량기 집계) : 사용계약(계량기 단위 1행)이 1:N 구조라 "
        "행 수가 늘어나는 게 정상입니다."
    )

    out_path = DATA_DIR / f"계약공급연계_{date.today():%Y%m%d}.parquet"
    df_merged.to_parquet(out_path, index=False, compression="snappy")
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"✅ 저장 완료: {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()