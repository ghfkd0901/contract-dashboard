# utils.py
import streamlit as st
import pandas as pd
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

VALID_STATES = ["공급계약", "공급승인"]

@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build('drive', 'v3', credentials=creds)

@st.cache_data(ttl=600)
def load_contract_df() -> pd.DataFrame:
    """계약전 데이터 로드 + 전처리 (앱 전체 공유, 10분 캐시)"""
    drive_service = get_drive_service()
    folder_id = st.secrets["drive_folders"]["contract_view"]

    try:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id, name, mimeType, modifiedTime)",
            orderBy="modifiedTime desc"
        ).execute()
        files = results.get("files", [])
        if not files:
            return pd.DataFrame()

        file = files[0]
        mime = file.get("mimeType", "")
        if "google-apps" in mime:
            request = drive_service.files().export_media(fileId=file["id"], mimeType="text/csv")
            encoding = "utf-8"
        else:
            request = drive_service.files().get_media(fileId=file["id"])
            encoding = "cp949"

        fh = io.BytesIO()
        dl = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = dl.next_chunk()
        fh.seek(0)

        try:
            df = pd.read_csv(fh, encoding=encoding, low_memory=False)
        except UnicodeDecodeError:
            fh.seek(0)
            df = pd.read_csv(fh, encoding="utf-8-sig", low_memory=False)

        df.columns = [c.strip() for c in df.columns]

        # ── 전처리 ──────────────────────────────
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
        df["월"]   = df["연월"].str[5:7]

        df["시군구"] = df["주소"].astype(str).str[:3].str.replace(" ", "")
        df["시도"]   = df["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")

        for col in ["계약구분", "상품명", "용도", "공급신청번호"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        return df

    except Exception as e:
        st.error(f"❌ 계약전 데이터 로드 실패: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_supply_df() -> pd.DataFrame:
    """공급전 데이터 로드 + 전처리 (앱 전체 공유, 10분 캐시)"""
    drive_service = get_drive_service()
    folder_id = st.secrets["drive_folders"]["supply_view"]

    try:
        results = drive_service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id, name, mimeType, modifiedTime)",
            orderBy="modifiedTime desc"
        ).execute()
        files = results.get("files", [])
        if not files:
            return pd.DataFrame()

        file = files[0]
        mime = file.get("mimeType", "")
        if "google-apps" in mime:
            request = drive_service.files().export_media(fileId=file["id"], mimeType="text/csv")
            encoding = "utf-8"
        else:
            request = drive_service.files().get_media(fileId=file["id"])
            encoding = "cp949"

        fh = io.BytesIO()
        dl = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = dl.next_chunk()
        fh.seek(0)

        try:
            df = pd.read_csv(fh, encoding=encoding, low_memory=False)
        except UnicodeDecodeError:
            fh.seek(0)
            df = pd.read_csv(fh, encoding="utf-8-sig", low_memory=False)

        df.columns = [c.strip() for c in df.columns]

        # ── 전처리 ──────────────────────────────
        first_col = df.columns[0]
        df = df[~df[first_col].astype(str).str.contains("계", na=False)].copy()

        df["공급일"] = df["공급일"].astype(str).str.strip()
        parsed = pd.to_datetime(df["공급일"], errors="coerce")
        df["연월"] = parsed.dt.strftime("%Y-%m").where(parsed.notna(), df["공급일"].astype(str).str[:7])
        df["연도"] = df["연월"].str[:4]
        df["월"]   = df["연월"].str[5:7]

        # 월 컬럼 정리 — 빈 문자열/NaN 제거
        df = df[df["월"].str.match(r"^\d{2}$", na=False)].copy()

        df["시군구"] = df["주소"].astype(str).str[:3].str.replace(" ", "")
        df["시도"]   = df["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")

        # 신규개발량 계산
        def calc_monthly_dev(row):
            try:
                월사용 = float(str(row.get("월 사용예정량", 0)).replace(",", "").strip()) if pd.notna(row.get("월 사용예정량")) else 0
            except:
                월사용 = 0
            try:
                등급 = float(row.get("등급", 0)) if pd.notna(row.get("등급")) else 0
            except:
                등급 = 0
            base = 월사용 if 월사용 > 1 else 등급 * 0.6 * 10145 * 90 / 11000
            return round(base * 0.504, 2)

        df["신규개발량"] = df.apply(calc_monthly_dev, axis=1)

        for col in ["계약구분", "상품", "용도", "업종", "공급신청번호"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        return df

    except Exception as e:
        st.error(f"❌ 공급전 데이터 로드 실패: {e}")
        return pd.DataFrame()