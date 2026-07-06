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
DETAIL_COLS = ["연월", "공급신청일", "공급신청명", "시군구", "주소",
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

def make_excel(df_pivot: pd.DataFrame, df_raw: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book
        fmt_header      = wb.add_format({"bold": True, "bg_color": "#4472C4", "font_color": "#FFFFFF", "border": 1, "align": "center"})
        fmt_number      = wb.add_format({"num_format": "#,##0", "border": 1})
        fmt_number_bold = wb.add_format({"bold": True, "num_format": "#,##0", "bg_color": "#F0F2F6", "border": 1})
        fmt_cell        = wb.add_format({"border": 1})
        num_cols = ["전수", "시설분담금"]

        # 시트1: 집계
        ws1 = wb.add_worksheet("집계")
        writer.sheets["집계"] = ws1
        ws1.write(0, 0, "항목", fmt_header)
        ws1.set_column(0, 0, 20)
        for ci, col in enumerate(df_pivot.columns):
            ws1.write(0, ci + 1, str(col), fmt_header)
            ws1.set_column(ci + 1, ci + 1, 12)
        for ri, idx in enumerate(df_pivot.index):
            is_total = str(idx) in ["합계", "✅ 총합계"] or str(idx).startswith("▶")
            ws1.write(ri + 1, 0, str(idx), fmt_number_bold if is_total else fmt_cell)
            for ci, val in enumerate(df_pivot.iloc[ri]):
                ws1.write(ri + 1, ci + 1, val, fmt_number_bold if is_total else fmt_number)

        # 시트2: 원본데이터
        raw_cols = [c for c in DETAIL_COLS if c in df_raw.columns]
        df_out = df_raw[raw_cols].sort_values("연월", ascending=False)
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
st.set_page_config(page_title="연간계약실적조회", layout="wide")
st.title("📊 연간계약실적조회")

df_raw_orig = load_latest_csv(CONTRACT_FOLDER_ID)
if df_raw_orig.empty:
    st.stop()

# ───────────────────────────────
# 전처리
# ───────────────────────────────
first_col = df_raw_orig.columns[0]
df_clean = df_raw_orig[~df_raw_orig[first_col].astype(str).str.contains("총 계|총계|총합계", na=False)].copy()
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
df_base["연도"] = df_base["연월"].str[:4]
df_base["월"]   = df_base["연월"].str[5:7]  # "01" ~ "12"

if "주소" in df_base.columns:
    df_base["시군구"] = df_base["주소"].astype(str).str[:3].str.replace(" ", "")
df_base["시도"] = df_base["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")
for col in ["계약구분", "상품명", "용도"]:
    if col in df_base.columns:
        df_base[col] = df_base[col].astype(str).str.strip()

# ───────────────────────────────
# 🔧 사이드바 전체
# ───────────────────────────────
all_years = sorted(df_base["연도"].dropna().unique().tolist(), reverse=True)
has_fee = "시설분담금" in df_base.columns

with st.sidebar:
    st.header("🔍 조회 설정")

    # 📅 연도 선택
    st.markdown("#### 📅 조회 연도")
    sel_year = st.selectbox("연도", all_years, index=0)
    df_period = df_base[df_base["연도"] == sel_year].copy()

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

    st.divider()
    st.markdown("#### 📥 엑셀 다운로드")
    download_placeholder = st.empty()

df = df_s.copy()
fmt_cols = {"전수": "{:,.0f}", **({"시설분담금": "{:,.0f}"} if has_fee else {})}

# ───────────────────────────────
# 📊 요약 지표
# ───────────────────────────────
st.markdown(f"#### 📅 {sel_year}년 실적")
m1, m2, m3 = st.columns(3)
m1.metric("총 전수",       f"{int(df['전수'].sum()):,}")
m2.metric("총 시설분담금", f"{int(df['시설분담금'].sum()):,} 원" if has_fee else "-")
m3.metric("총 건수",       f"{len(df):,} 건")
st.divider()

# ───────────────────────────────
# 📊 집계 옵션 (라디오 두 개)
# ───────────────────────────────
rc1, rc2 = st.columns([2, 1])
with rc1:
    AGG_OPTIONS = {
        "용도별":      ("single",       "용도",   None),
        "상품별":      ("single",       "상품명",  None),
        "용도 › 상품": ("hierarchical", "용도",   "상품명"),
        "상품 › 용도": ("hierarchical", "상품명", "용도"),
    }
    sel_agg = st.radio("집계 기준", list(AGG_OPTIONS.keys()), index=0, horizontal=True)
with rc2:
    val_col = st.radio("표시 값", ["전수", "시설분담금"] if has_fee else ["전수"], index=0, horizontal=True)

mode, col_a, col_b = AGG_OPTIONS[sel_agg]

# ───────────────────────────────
# 📊 12개월 가로 피벗 생성
# ───────────────────────────────
ALL_MONTHS = [f"{m:02d}" for m in range(1, 13)]  # 01 ~ 12
MONTH_LABELS = {f"{m:02d}": f"{m}월" for m in range(1, 13)}

def build_annual_pivot(df_in, group_col, child_col, val):
    """행: 항목(소계포함), 열: 1월~12월 + 합계"""
    rows, bolds = [], []

    if mode == "single":
        items = sorted(df_in[group_col].dropna().unique())
        for item in items:
            df_i = df_in[df_in[group_col] == item]
            row = {"항목": item}
            for m in ALL_MONTHS:
                row[MONTH_LABELS[m]] = df_i[df_i["월"] == m][val].sum()
            row["합계"] = df_i[val].sum()
            rows.append(row); bolds.append(False)
        # 총합계
        total = {"항목": "✅ 합계"}
        for m in ALL_MONTHS:
            total[MONTH_LABELS[m]] = df_in[df_in["월"] == m][val].sum()
        total["합계"] = df_in[val].sum()
        rows.append(total); bolds.append(True)

    else:  # hierarchical
        parents = sorted(df_in[col_a].dropna().unique())
        for parent in parents:
            df_p = df_in[df_in[col_a] == parent]
            # 소계 행
            sub = {"항목": f"▶ {parent} 소계"}
            for m in ALL_MONTHS:
                sub[MONTH_LABELS[m]] = df_p[df_p["월"] == m][val].sum()
            sub["합계"] = df_p[val].sum()
            rows.append(sub); bolds.append(True)
            # 자식 행
            children = sorted(df_p[col_b].dropna().unique())
            for child in children:
                df_c = df_p[df_p[col_b] == child]
                row = {"항목": f"　{child}"}
                for m in ALL_MONTHS:
                    row[MONTH_LABELS[m]] = df_c[df_c["월"] == m][val].sum()
                row["합계"] = df_c[val].sum()
                rows.append(row); bolds.append(False)
        # 총합계
        total = {"항목": "✅ 총합계"}
        for m in ALL_MONTHS:
            total[MONTH_LABELS[m]] = df_in[df_in["월"] == m][val].sum()
        total["합계"] = df_in[val].sum()
        rows.append(total); bolds.append(True)

    return pd.DataFrame(rows), pd.Series(bolds)

# ───────────────────────────────
# 📊 테이블 출력
# ───────────────────────────────
if not df.empty:
    tbl, bold_mask = build_annual_pivot(df, col_a, col_b, val_col)

    month_cols   = [MONTH_LABELS[m] for m in ALL_MONTHS]
    display_cols = ["항목"] + month_cols + ["합계"]
    # 해당 연도에 데이터 없는 월은 0으로 유지 (컬럼은 항상 12개)
    for c in display_cols[1:]:
        if c not in tbl.columns:
            tbl[c] = 0
    tbl = tbl[display_cols]

    def style_tbl(df_tbl):
        def _row(row):
            if bold_mask.iloc[row.name]:
                return ["font-weight:bold; background-color:#f0f2f6"] * len(row)
            return ["color:#444"] * len(row)
        fmt = {c: "{:,.0f}" for c in display_cols[1:]}
        return df_tbl.style.apply(_row, axis=1).format(fmt)

    st.dataframe(style_tbl(tbl), use_container_width=True, hide_index=True, height=520)

    # 내역 보기
    with st.expander("📋 내역 보기"):
        month_opts = sorted(df["월"].dropna().unique().tolist())
        month_display = ["전체"] + [f"{int(m)}월" for m in month_opts]
        sel_m = st.selectbox("월 선택", month_display, key="detail_month")
        if sel_m == "전체":
            df_d = df
        else:
            sel_m_val = f"{int(sel_m.replace('월','')):02d}"
            df_d = df[df["월"] == sel_m_val]

        detail_cols = [c for c in DETAIL_COLS if c in df_d.columns]
        st.markdown(f"**{len(df_d):,}건 / {val_col} {int(df_d[val_col].sum()):,}**")
        st.dataframe(
            df_d[detail_cols].sort_values("연월", ascending=False).style.format(fmt_cols),
            use_container_width=True, hide_index=True, height=380
        )

    # 📥 사이드바 다운로드
    excel_bytes = make_excel(tbl.set_index("항목"), df)
    download_placeholder.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"연간계약실적_{sel_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    st.info("조건에 맞는 데이터가 없습니다.")