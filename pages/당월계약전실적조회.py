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
VALID_STATES = ["공급계약", "공급승인"]
DETAIL_COLS = ["공급신청일", "공급신청명", "시군구", "주소",
               "상품명", "용도", "계약구분", "전수", "시설분담금"]

@st.cache_data(ttl=300)
def load_latest_csv(folder_id):
    query = f"'{folder_id}' in parents and name contains '.csv' and trashed = false"
    try:
        results = drive_service.files().list(
            q=query, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc"
        ).execute()
        files = results.get("files", [])
        if not files:
            return pd.DataFrame()
        file = files[0]
        st.caption(f"📄 로드된 파일: `{file['name']}`")
        request = drive_service.files().get_media(fileId=file["id"])
        fh = io.BytesIO()
        dl = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = dl.next_chunk()
        fh.seek(0)
        df = pd.read_csv(fh, encoding="cp949")
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception as e:
        st.error(f"❌ 파일 로드 실패: {e}")
        return pd.DataFrame()

def make_excel(df_summary: pd.DataFrame, df_raw: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book
        fmt_header     = wb.add_format({"bold": True, "bg_color": "#4472C4", "font_color": "#FFFFFF", "border": 1, "align": "center"})
        fmt_number      = wb.add_format({"num_format": "#,##0", "border": 1})
        fmt_number_bold = wb.add_format({"bold": True, "num_format": "#,##0", "bg_color": "#F0F2F6", "border": 1})
        fmt_cell        = wb.add_format({"border": 1})
        fmt_cell_bold   = wb.add_format({"bold": True, "bg_color": "#F0F2F6", "border": 1})
        num_cols = ["전수", "시설분담금"]

        # 시트1: 집계
        ws1 = wb.add_worksheet("집계")
        writer.sheets["집계"] = ws1
        cols = list(df_summary.columns)
        for ci, col in enumerate(cols):
            ws1.write(0, ci, col, fmt_header)
            ws1.set_column(ci, ci, 20)
        for ri, row in df_summary.iterrows():
            is_bold = str(row[cols[0]]).startswith("▶") or str(row[cols[0]]).startswith("✅")
            for ci, col in enumerate(cols):
                val = row[col]
                if col in num_cols:
                    ws1.write(ri + 1, ci, val, fmt_number_bold if is_bold else fmt_number)
                else:
                    ws1.write(ri + 1, ci, val, fmt_cell_bold if is_bold else fmt_cell)

        # 시트2: 원본데이터
        raw_cols = [c for c in DETAIL_COLS if c in df_raw.columns]
        df_out = df_raw[raw_cols].sort_values("공급신청일", ascending=False)
        df_out.to_excel(writer, sheet_name="원본데이터", index=False)
        ws2 = writer.sheets["원본데이터"]
        for ci, col in enumerate(raw_cols):
            ws2.write(0, ci, col, fmt_header)
            ws2.set_column(ci, ci, 18)
        for ri in range(1, len(df_out) + 1):
            for ci, col in enumerate(raw_cols):
                val = df_out.iloc[ri - 1][col]
                ws2.write(ri, ci, val if col in num_cols else (str(val) if pd.notna(val) else ""),
                          fmt_number if col in num_cols else fmt_cell)
    return output.getvalue()

# ───────────────────────────────
# 🚀 화면 설정
# ───────────────────────────────
st.set_page_config(page_title="당월계약실적조회", layout="wide")
st.title("📅 당월계약실적조회")

df_raw = load_latest_csv(CONTRACT_FOLDER_ID)
if df_raw.empty:
    st.stop()

# ───────────────────────────────
# 전처리
# ───────────────────────────────
first_col = df_raw.columns[0]
df_clean = df_raw[~df_raw[first_col].astype(str).str.contains("총 계|총계|총합계", na=False)].copy()
df_clean["공급신청상태"] = df_clean["공급신청상태"].astype(str).str.replace(" ", "").str.strip()
df_base = df_clean[df_clean["공급신청상태"].isin(VALID_STATES)].copy()

df_base["전수"] = pd.to_numeric(
    df_base["전수"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce"
).fillna(0)
if "시설분담금" in df_base.columns:
    df_base["시설분담금"] = pd.to_numeric(
        df_base["시설분담금"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce"
    ).fillna(0)

def extract_ym(series):
    parsed = pd.to_datetime(series, errors="coerce")
    return parsed.dt.strftime("%Y-%m").where(parsed.notna(), series.astype(str).str[:7])

df_base["연월"] = extract_ym(df_base["공급신청일"])
if "주소" in df_base.columns:
    df_base["시군구"] = df_base["주소"].astype(str).str[:3].str.replace(" ", "")
df_base["시도"] = df_base["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")
for col in ["계약구분", "상품명", "용도"]:
    if col in df_base.columns:
        df_base[col] = df_base[col].astype(str).str.strip()

# ───────────────────────────────
# 🔧 사이드바 전체
# ───────────────────────────────
with st.sidebar:
    st.header("🔍 조회 설정")

    # 📅 연월 선택
    all_ym = sorted(df_base["연월"].dropna().unique().tolist(), reverse=True)
    st.markdown("#### 📅 조회 연월")
    sel_ym = st.selectbox("연월", all_ym, index=0)
    df_period = df_base[df_base["연월"] == sel_ym].copy()

    st.divider()
    st.markdown("#### 🔎 상세 필터")

    all_sido = sorted(df_period["시도"].dropna().unique())
    sel_sido = st.multiselect("시도", all_sido, default=all_sido)
    df_s = df_period[df_period["시도"].isin(sel_sido)]

    all_sg = sorted(df_s["시군구"].dropna().unique())
    sel_sg = st.multiselect("시군구", all_sg, default=all_sg)
    df_s = df_s[df_s["시군구"].isin(sel_sg)]

    if "계약구분" in df_s.columns:
        opts = sorted(df_s["계약구분"].dropna().unique())
        sel = st.multiselect("계약구분", opts, default=opts)
        df_s = df_s[df_s["계약구분"].isin(sel)]

    if "상품명" in df_s.columns:
        opts = sorted(df_s["상품명"].dropna().unique())
        sel = st.multiselect("상품", opts, default=opts)
        df_s = df_s[df_s["상품명"].isin(sel)]

    if "용도" in df_s.columns:
        opts = sorted(df_s["용도"].dropna().unique())
        sel = st.multiselect("용도", opts, default=opts)
        df_s = df_s[df_s["용도"].isin(sel)]

    st.divider()
    if st.button("🔄 필터 초기화"):
        st.rerun()

    # 📥 다운로드 (사이드바 맨 아래 — summary_df는 메인에서 채운 뒤 session_state로 전달)
    st.divider()
    st.markdown("#### 📥 엑셀 다운로드")
    download_placeholder = st.empty()  # 집계 완성 후 여기에 버튼 삽입

df = df_s.copy()
has_fee = "시설분담금" in df.columns
fmt_cols = {"전수": "{:,.0f}", **({"시설분담금": "{:,.0f}"} if has_fee else {})}

# ───────────────────────────────
# 📊 요약 지표
# ───────────────────────────────
st.markdown(f"#### 📅 {sel_ym} 실적")
m1, m2, m3 = st.columns(3)
m1.metric("총 전수", f"{int(df['전수'].sum()):,}")
m2.metric("총 시설분담금", f"{int(df['시설분담금'].sum()):,} 원" if has_fee else "-")
m3.metric("총 건수", f"{len(df):,} 건")
st.divider()

# ───────────────────────────────
# 공통 유틸
# ───────────────────────────────
def style_bold(df_tbl, bold_mask):
    def _row(row):
        if bold_mask.iloc[row.name]:
            return ["font-weight:bold; background-color:#f0f2f6"] * len(row)
        return ["color:#444"] * len(row)
    return df_tbl.style.apply(_row, axis=1)

def show_detail(df_detail, label):
    cols = [c for c in DETAIL_COLS if c in df_detail.columns]
    st.markdown(f"**📋 내역: {label} — {len(df_detail):,}건 / 전수 {int(df_detail['전수'].sum()):,}**")
    st.dataframe(
        df_detail[cols].sort_values("공급신청일", ascending=False).style.format(fmt_cols),
        use_container_width=True, hide_index=True, height=380
    )

def agg_single(df_in, group_col):
    agg = {"전수": ("전수", "sum"), **({"시설분담금": ("시설분담금", "sum")} if has_fee else {})}
    grp = df_in.groupby(group_col, as_index=False).agg(**agg).sort_values("전수", ascending=False)
    total = {group_col: "✅ 합계", "전수": grp["전수"].sum()}
    if has_fee:
        total["시설분담금"] = grp["시설분담금"].sum()
    grp = pd.concat([grp, pd.DataFrame([total])], ignore_index=True)
    return grp, grp[group_col] == "✅ 합계"

def agg_hierarchical(df_in, parent_col, child_col):
    rows, bolds = [], []
    for parent in sorted(df_in[parent_col].dropna().unique()):
        df_p = df_in[df_in[parent_col] == parent]
        row = {"구분": f"▶ {parent} 소계", "전수": df_p["전수"].sum()}
        if has_fee:
            row["시설분담금"] = df_p["시설분담금"].sum()
        rows.append(row); bolds.append(True)
        agg = {"전수": ("전수", "sum"), **({"시설분담금": ("시설분담금", "sum")} if has_fee else {})}
        for _, r in df_p.groupby(child_col, as_index=False).agg(**agg).sort_values("전수", ascending=False).iterrows():
            detail = {"구분": f"　{r[child_col]}", "전수": r["전수"]}
            if has_fee:
                detail["시설분담금"] = r["시설분담금"]
            rows.append(detail); bolds.append(False)
    total = {"구분": "✅ 총합계", "전수": df_in["전수"].sum()}
    if has_fee:
        total["시설분담금"] = df_in["시설분담금"].sum()
    rows.append(total); bolds.append(True)
    return pd.DataFrame(rows), pd.Series(bolds)

# ───────────────────────────────
# 📊 집계 기준 선택형 테이블
# ───────────────────────────────
st.markdown("### 📊 항목별 집계")

AGG_OPTIONS = {
    "용도 › 상품": ("hierarchical", "용도", "상품명"),
    "상품 › 용도": ("hierarchical", "상품명", "용도"),
    "용도별":      ("single",       "용도",   None),
    "상품별":      ("single",       "상품명",  None),
}
sel_agg = st.radio("집계 기준", list(AGG_OPTIONS.keys()), index=0, horizontal=True)
mode, col_a, col_b = AGG_OPTIONS[sel_agg]

summary_df = pd.DataFrame()

if not df.empty:
    if mode == "hierarchical":
        tbl, bold_mask = agg_hierarchical(df, col_a, col_b)
        summary_df = tbl.copy()
        st.dataframe(style_bold(tbl, bold_mask).format(fmt_cols),
                     use_container_width=True, hide_index=True, height=520)
        with st.expander("📋 내역 보기"):
            d1, d2 = st.columns(2)
            with d1:
                sel_a = st.selectbox(col_a, ["전체"] + sorted(df[col_a].dropna().unique()), key="h_a")
            df_tmp = df if sel_a == "전체" else df[df[col_a] == sel_a]
            with d2:
                sel_b = st.selectbox(col_b, ["전체"] + sorted(df_tmp[col_b].dropna().unique()), key="h_b")
            show_detail(df_tmp if sel_b == "전체" else df_tmp[df_tmp[col_b] == sel_b], f"{sel_a} › {sel_b}")
    else:
        tbl, bold_mask = agg_single(df, col_a)
        summary_df = tbl.copy()
        st.dataframe(style_bold(tbl, bold_mask).format(fmt_cols),
                     use_container_width=True, hide_index=True)
        with st.expander("📋 내역 보기"):
            sel_a = st.selectbox(col_a, ["전체"] + sorted(df[col_a].dropna().unique()), key="s_a")
            show_detail(df if sel_a == "전체" else df[df[col_a] == sel_a], sel_a)

# ───────────────────────────────
# 📥 사이드바 다운로드 버튼 (집계 완성 후 삽입)
# ───────────────────────────────
if not summary_df.empty:
    excel_bytes = make_excel(summary_df, df)
    download_placeholder.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"당월계약실적_{sel_ym}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )