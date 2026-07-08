import streamlit as st
import pandas as pd
from pathlib import Path

VALID_STATES = ["공급계약", "공급승인"]

# ───────────────────────────────
# 데이터 폴더 / 파일 패턴
# ───────────────────────────────
DATA_DIR = Path(r"D:\Project\계약내역조회웹앱\data")
CONTRACT_PATTERN = "계약전현황조회_*.csv"
SUPPLY_PATTERN = "공급전현황조회_*.csv"


def _latest_file(pattern: str) -> Path | None:
    """DATA_DIR 안에서 파일명 패턴에 맞는 파일 중 가장 최근에 수정된 파일 반환"""
    files = list(DATA_DIR.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _read_csv_robust(path: Path) -> pd.DataFrame:
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc, low_memory=False)
            df.columns = [c.strip() for c in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 확인할 수 없습니다: {path}")


# ───────────────────────────────
# 원본 → 가공 로직 (기존 로직 그대로)
# ───────────────────────────────
def _process_contract(df: pd.DataFrame) -> pd.DataFrame:
    first_col = df.columns[0]
    df = df[~df[first_col].astype(str).str.contains("총 계|총계|총합계", na=False)].copy()

    df["공급신청상태"] = df["공급신청상태"].astype(str).str.replace(" ", "").str.strip()
    df = df[df["공급신청상태"].isin(VALID_STATES)].copy()

    df["전수"] = pd.to_numeric(
        df["전수"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce"
    ).fillna(0)

    if "시설분담금" in df.columns:
        df["시설분담금"] = pd.to_numeric(
            df["시설분담금"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce"
        ).fillna(0)

    parsed = pd.to_datetime(df["공급신청일"], errors="coerce")
    df["연월"] = parsed.dt.strftime("%Y-%m").where(parsed.notna(), df["공급신청일"].astype(str).str[:7])
    df["연도"] = df["연월"].str[:4]
    df["월"] = df["연월"].str[5:7]

    df["시군구"] = df["주소"].astype(str).str[:3].str.replace(" ", "")
    df["시도"] = df["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")

    for col in ["계약구분", "상품명", "용도", "공급신청번호"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


def _process_supply(df: pd.DataFrame) -> pd.DataFrame:
    first_col = df.columns[0]
    df = df[~df[first_col].astype(str).str.contains("계", na=False)].copy()

    df["공급일"] = df["공급일"].astype(str).str.strip()
    parsed = pd.to_datetime(df["공급일"], errors="coerce")
    df["연월"] = parsed.dt.strftime("%Y-%m").where(parsed.notna(), df["공급일"].astype(str).str[:7])
    df["연도"] = df["연월"].str[:4]
    df["월"] = df["연월"].str[5:7]

    df = df[df["월"].str.match(r"^\d{2}$", na=False)].copy()

    df["시군구"] = df["주소"].astype(str).str[:3].str.replace(" ", "")
    df["시도"] = df["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")

    월사용 = pd.to_numeric(
        df["월 사용예정량"].astype(str).str.replace(",", "").str.strip(),
        errors="coerce"
    ).fillna(0)
    등급 = pd.to_numeric(df["등급"], errors="coerce").fillna(0)
    base = 월사용.where(월사용 > 1, 등급 * 0.6 * 10145 * 90 / 11000)
    df["신규개발량"] = (base * 0.504).round(2)

    for col in ["계약구분", "상품", "용도", "업종", "공급신청번호"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


# ───────────────────────────────
# 캐시된 로더 (path + mtime을 키로 사용 → 파일이 바뀌면 자동 갱신)
# ───────────────────────────────
@st.cache_data(show_spinner="계약전 데이터 불러오는 중...")
def _load_contract_cached(path_str: str, mtime: float) -> pd.DataFrame:
    df = _read_csv_robust(Path(path_str))
    return _process_contract(df)


@st.cache_data(show_spinner="공급전 데이터 불러오는 중...")
def _load_supply_cached(path_str: str, mtime: float) -> pd.DataFrame:
    df = _read_csv_robust(Path(path_str))
    return _process_supply(df)


# ───────────────────────────────
# 외부에서 호출하는 함수 (기존과 시그니처 동일)
# ───────────────────────────────
def load_contract_df() -> pd.DataFrame:
    try:
        f = _latest_file(CONTRACT_PATTERN)
        if f is None:
            st.error(f"❌ 계약전 데이터 파일을 찾을 수 없습니다: {DATA_DIR / CONTRACT_PATTERN}")
            return pd.DataFrame()
        return _load_contract_cached(str(f), f.stat().st_mtime)
    except Exception as e:
        st.error(f"❌ 계약전 데이터 로드 실패: {e}")
        return pd.DataFrame()


def load_supply_df() -> pd.DataFrame:
    try:
        f = _latest_file(SUPPLY_PATTERN)
        if f is None:
            st.error(f"❌ 공급전 데이터 파일을 찾을 수 없습니다: {DATA_DIR / SUPPLY_PATTERN}")
            return pd.DataFrame()
        return _load_supply_cached(str(f), f.stat().st_mtime)
    except Exception as e:
        st.error(f"❌ 공급전 데이터 로드 실패: {e}")
        return pd.DataFrame()