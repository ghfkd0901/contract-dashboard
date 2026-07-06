import streamlit as st
import pandas as pd
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

creds = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=["https://www.googleapis.com/auth/drive.readonly"]
) 
drive_service = build('drive', 'v3', credentials=creds)

CONTRACT_FOLDER_ID = st.secrets["drive_folders"]["contract_view"]
SUPPLY_FOLDER_ID   = st.secrets["drive_folders"]["supply_view"]
VALID_STATES = ["공급계약", "공급승인"]

@st.cache_data(ttl=300)
def load_csv(folder_id, encoding="cp949"):
    query = f"'{folder_id}' in parents and trashed = false"
    try:
        results = drive_service.files().list(
            q=query,
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
        return df
    except Exception as e:
        st.error(f"❌ 로드 실패: {e}")
        return pd.DataFrame()

st.set_page_config(page_title="계약-공급 연계 현황", layout="wide")
st.title("🔗 계약-공급 연계 현황")

# ───────────────────────────────
# 데이터 로드
# ───────────────────────────────
with st.spinner("데이터 로딩 중..."):
    df_contract_raw = load_csv(CONTRACT_FOLDER_ID)
    df_supply_raw   = load_csv(SUPPLY_FOLDER_ID)

if df_contract_raw.empty or df_supply_raw.empty:
    st.error("데이터 로드 실패")
    st.stop()

# ───────────────────────────────
# 계약전 전처리
# ───────────────────────────────
first_col = df_contract_raw.columns[0]
df_c = df_contract_raw[~df_contract_raw[first_col].astype(str).str.contains("총 계|총계|총합계", na=False)].copy()
df_c["공급신청상태"] = df_c["공급신청상태"].astype(str).str.replace(" ", "").str.strip()
df_c = df_c[df_c["공급신청상태"].isin(VALID_STATES)].copy()
df_c["공급신청번호"] = df_c["공급신청번호"].astype(str).str.strip()

parsed_c = pd.to_datetime(df_c["공급신청일"], errors="coerce")
df_c["연월_계약"] = parsed_c.dt.strftime("%Y-%m").where(parsed_c.notna(), df_c["공급신청일"].astype(str).str[:7])

df_c["시군구"] = df_c["주소"].astype(str).str[:3].str.replace(" ", "")
df_c["시도"]   = df_c["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")
for col in ["상품명", "용도", "계약구분"]:
    if col in df_c.columns:
        df_c[col] = df_c[col].astype(str).str.strip()

# ───────────────────────────────
# 공급전 전처리
# ───────────────────────────────
first_col_s = df_supply_raw.columns[0]
df_s = df_supply_raw[~df_supply_raw[first_col_s].astype(str).str.contains("계", na=False)].copy()
df_s["공급신청번호"] = df_s["공급신청번호"].astype(str).str.strip()

parsed_s = pd.to_datetime(df_s["공급일"], errors="coerce")
df_s["연월_공급"] = parsed_s.dt.strftime("%Y-%m").where(parsed_s.notna(), df_s["공급일"].astype(str).str[:7])

# 공급전 컬럼 전체에 _공급 접미사 (공급신청번호 제외)
df_s_renamed = df_s.rename(columns={
    col: f"{col}_공급" for col in df_s.columns if col != "공급신청번호"
})

# ───────────────────────────────
# 🔧 사이드바
# ───────────────────────────────
all_ym_c = sorted(df_c["연월_계약"].dropna().unique().tolist(), reverse=True)
all_ym_s = sorted(df_s["연월_공급"].dropna().unique().tolist(), reverse=True)

with st.sidebar:
    st.header("🔍 조회 설정")

    # 계약전 기간
    st.markdown("#### 📋 계약전 기간 (공급신청일)")
    c1, c2 = st.columns(2)
    with c1:
        start_c = st.selectbox("시작", all_ym_c, index=len(all_ym_c) - 1, key="start_c")
    with c2:
        end_c = st.selectbox("종료", all_ym_c, index=0, key="end_c")
    if start_c > end_c:
        st.warning("⚠️ 시작이 종료보다 늦습니다")

    # 공급전 기간
    st.markdown("#### 🏠 공급전 기간 (공급일)")
    c3, c4 = st.columns(2)
    with c3:
        start_s = st.selectbox("시작", all_ym_s, index=len(all_ym_s) - 1, key="start_s")
    with c4:
        end_s = st.selectbox("종료", all_ym_s, index=0, key="end_s")
    if start_s > end_s:
        st.warning("⚠️ 시작이 종료보다 늦습니다")

    st.divider()
    st.markdown("#### 🔎 상세 필터 (계약전 기준)")

    # 계층적 필터
    all_sido = sorted(df_c["시도"].dropna().unique())
    sel_sido = st.multiselect("시도", all_sido, default=all_sido)
    df_f1 = df_c[df_c["시도"].isin(sel_sido)]

    all_sg = sorted(df_f1["시군구"].dropna().unique())
    sel_sg = st.multiselect("시군구", all_sg, default=all_sg)
    df_f2 = df_f1[df_f1["시군구"].isin(sel_sg)]

    all_ct = sorted(df_f2["계약구분"].dropna().unique())
    sel_ct = st.multiselect("계약구분", all_ct, default=all_ct)
    df_f3 = df_f2[df_f2["계약구분"].isin(sel_ct)]

    if "상품명" in df_f3.columns:
        all_prod = sorted(df_f3["상품명"].dropna().unique())
        sel_prod = st.multiselect("상품", all_prod, default=all_prod)
        df_f4 = df_f3[df_f3["상품명"].isin(sel_prod)]
    else:
        df_f4 = df_f3

    if "용도" in df_f4.columns:
        all_usage = sorted(df_f4["용도"].dropna().unique())
        sel_usage = st.multiselect("용도", all_usage, default=all_usage)
        df_f5 = df_f4[df_f4["용도"].isin(sel_usage)]
    else:
        df_f5 = df_f4

    st.divider()
    if st.button("🔄 필터 초기화"):
        st.rerun()

    st.divider()
    st.markdown("#### 📥 엑셀 다운로드")
    download_placeholder = st.empty()

# ───────────────────────────────
# 필터 적용 — 계약전 기간 + 상세필터
# ───────────────────────────────
sel_ym_c = [ym for ym in all_ym_c if start_c <= ym <= end_c]
sel_ym_s = [ym for ym in all_ym_s if start_s <= ym <= end_s]

df_c_filtered = df_f5[df_f5["연월_계약"].isin(sel_ym_c)].copy()

# 공급전은 기간만 필터링
df_s_filtered = df_s_renamed[df_s_renamed["연월_공급_공급"].isin(sel_ym_s)].copy()

# ───────────────────────────────
# LEFT JOIN (계약전 기준)
# ───────────────────────────────
df_join = df_c_filtered.merge(df_s_filtered, on="공급신청번호", how="left")

df_join["공급신청일"]  = pd.to_datetime(df_join["공급신청일"], errors="coerce")
df_join["공급일_공급"] = pd.to_datetime(df_join["공급일_공급"], errors="coerce")
df_join["소요일수"]    = (df_join["공급일_공급"] - df_join["공급신청일"]).dt.days
df_join["완료여부"]    = df_join["공급일_공급"].notna().map({True: "✅ 완료", False: "⏳ 미완료"})

# ───────────────────────────────
# 📊 요약 지표
# ───────────────────────────────
total      = len(df_join)
completed  = int(df_join["공급일_공급"].notna().sum())
incomplete = total - completed
avg_days   = df_join["소요일수"].dropna().mean()
rate       = completed / total * 100 if total > 0 else 0

st.markdown("### 📊 매칭 현황 요약")
st.caption(f"계약전: {start_c} ~ {end_c}  |  공급전: {start_s} ~ {end_s}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("계약전 전체",   f"{total:,} 건")
m2.metric("✅ 공급 완료",  f"{completed:,} 건")
m3.metric("⏳ 미완료",     f"{incomplete:,} 건")
m4.metric("완료율",        f"{rate:.1f} %")
m5.metric("평균 소요일수", f"{avg_days:,.0f} 일" if not pd.isna(avg_days) else "-")

st.progress(int(rate), text=f"공급 완료율: {rate:.1f}%")
st.divider()

# ───────────────────────────────
# 📋 탭
# ───────────────────────────────
df_done   = df_join[df_join["공급일_공급"].notna()].copy()
df_undone = df_join[df_join["공급일_공급"].isna()].copy()

tab1, tab2, tab3 = st.tabs([
    f"📋 전체 ({total:,}건)",
    f"✅ 완료 ({completed:,}건)",
    f"⏳ 미완료 ({incomplete:,}건)"
])

priority_cols = ["완료여부", "소요일수", "공급신청번호", "공급신청일", "공급일_공급"]
other_cols    = [c for c in df_join.columns if c not in priority_cols]
display_cols  = priority_cols + other_cols

with tab1:
    st.dataframe(
        df_join[display_cols].sort_values("공급신청일", ascending=False),
        use_container_width=True, hide_index=True, height=600
    )

with tab2:
    st.dataframe(
        df_done[display_cols].sort_values("소요일수", ascending=False),
        use_container_width=True, hide_index=True, height=600
    )

with tab3:
    st.dataframe(
        df_undone[display_cols].sort_values("공급신청일", ascending=False),
        use_container_width=True, hide_index=True, height=600
    )

# ───────────────────────────────
# 📥 엑셀 다운로드
# ───────────────────────────────
def make_excel(df_all, df_done, df_undone) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter",
                        engine_kwargs={"options": {"nan_inf_to_errors": True}}) as writer:
        wb = writer.book
        fmt_header = wb.add_format({"bold": True, "bg_color": "#4472C4",
                                    "font_color": "#FFFFFF", "border": 1, "align": "center"})
        fmt_cell   = wb.add_format({"border": 1})

        for sheet_name, df_sheet in [("전체", df_all), ("완료", df_done), ("미완료", df_undone)]:
            df_out = df_sheet[display_cols].reset_index(drop=True)
            ws = wb.add_worksheet(sheet_name)
            writer.sheets[sheet_name] = ws
            for ci, col in enumerate(df_out.columns):
                ws.write(0, ci, col, fmt_header)
                ws.set_column(ci, ci, 18)
            for ri in range(len(df_out)):
                for ci, col in enumerate(df_out.columns):
                    val = df_out.iloc[ri][col]
                    ws.write(ri + 1, ci, str(val) if pd.notna(val) else "", fmt_cell)
    return output.getvalue()

if not df_join.empty:
    excel_bytes = make_excel(df_join, df_done, df_undone)
    download_placeholder.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"계약공급연계_{start_c}_{end_c}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )