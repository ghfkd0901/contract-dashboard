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

SUPPLY_FOLDER_ID = st.secrets["drive_folders"]["supply_view"]
DETAIL_COLS = ["공급일", "신청명", "시군구", "주소", "상품", "용도", "업종",
               "등급", "월 사용예정량", "신규개발량"]

@st.cache_data(ttl=300)
def load_latest_csv(folder_id):
    query = f"'{folder_id}' in parents and trashed = false"
    try:
        results = drive_service.files().list(
            q=query,
            fields="files(id, name, mimeType, modifiedTime)",
            orderBy="modifiedTime desc"
        ).execute()
        files = results.get("files", [])
        if not files:
            st.error("❌ 폴더에 파일이 없습니다.")
            return pd.DataFrame()
        file = files[0]
        st.caption(f"📄 로드된 파일: `{file['name']}`")
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
        return df
    except Exception as e:
        st.error(f"❌ 파일 로드 실패: {e}")
        return pd.DataFrame()

def calc_monthly_dev(월사용, 등급):
    try:
        월사용 = float(str(월사용).replace(",", "").strip()) if pd.notna(월사용) else 0
    except:
        월사용 = 0
    try:
        등급 = float(등급) if pd.notna(등급) else 0
    except:
        등급 = 0
    base = 월사용 if 월사용 > 1 else 등급 * 0.6 * 10145 * 90 / 11000
    return round(base * 0.504, 2)

def make_excel(df_pivot: pd.DataFrame, df_raw: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter",
                        engine_kwargs={"options": {"nan_inf_to_errors": True}}) as writer:
        wb = writer.book
        fmt_header      = wb.add_format({"bold": True, "bg_color": "#4472C4", "font_color": "#FFFFFF", "border": 1, "align": "center"})
        fmt_number      = wb.add_format({"num_format": "#,##0.##", "border": 1})
        fmt_number_bold = wb.add_format({"bold": True, "num_format": "#,##0.##", "bg_color": "#F0F2F6", "border": 1})
        fmt_cell        = wb.add_format({"border": 1})

        # 시트1: 집계
        ws1 = wb.add_worksheet("집계")
        writer.sheets["집계"] = ws1
        ws1.write(0, 0, "항목", fmt_header)
        ws1.set_column(0, 0, 20)
        for ci, col in enumerate(df_pivot.columns):
            ws1.write(0, ci + 1, str(col), fmt_header)
            ws1.set_column(ci + 1, ci + 1, 12)
        for ri, idx in enumerate(df_pivot.index):
            is_bold = str(idx) in ["✅ 합계", "✅ 총합계"] or str(idx).startswith("▶")
            ws1.write(ri + 1, 0, str(idx), fmt_number_bold if is_bold else fmt_cell)
            for ci, val in enumerate(df_pivot.iloc[ri]):
                try:
                    v = float(val)
                    v = 0 if (pd.isna(v) or v != v) else v
                except:
                    v = 0
                ws1.write(ri + 1, ci + 1, v, fmt_number_bold if is_bold else fmt_number)

        # 시트2: 원본데이터
        raw_cols = [c for c in DETAIL_COLS if c in df_raw.columns]
        df_out = df_raw[raw_cols].copy().sort_values("공급일", ascending=False).reset_index(drop=True)
        ws2 = wb.add_worksheet("원본데이터")
        writer.sheets["원본데이터"] = ws2
        for ci, col in enumerate(raw_cols):
            ws2.write(0, ci, col, fmt_header)
            ws2.set_column(ci, ci, 18)
        num_cols = ["신규개발량"]
        for ri in range(len(df_out)):
            for ci, col in enumerate(raw_cols):
                val = df_out.iloc[ri][col]
                if col in num_cols:
                    try:
                        v = float(val)
                        v = 0 if (pd.isna(v) or v != v) else v
                    except:
                        v = 0
                    ws2.write(ri + 1, ci, v, fmt_number)
                else:
                    ws2.write(ri + 1, ci, str(val) if pd.notna(val) else "", fmt_cell)
    return output.getvalue()

# ───────────────────────────────
# 🚀 화면 설정
# ───────────────────────────────
st.set_page_config(page_title="연간월별공급전실적조회", layout="wide")
st.title("📊 연간월별공급전실적조회")

df_raw_orig = load_latest_csv(SUPPLY_FOLDER_ID)
if df_raw_orig.empty:
    st.stop()

# ───────────────────────────────
# 전처리
# ───────────────────────────────
df_base = df_raw_orig.copy()
df_base.columns = [c.strip() for c in df_base.columns]

first_col = df_base.columns[0]
df_base = df_base[~df_base[first_col].astype(str).str.contains("계", na=False)].copy()

df_base["공급일"] = df_base["공급일"].astype(str).str.strip()
parsed_date = pd.to_datetime(df_base["공급일"], errors="coerce")
df_base["연월"] = parsed_date.dt.strftime("%Y-%m").where(parsed_date.notna(), df_base["공급일"].str[:7])
df_base["연도"] = df_base["연월"].str[:4]
df_base["월"]   = df_base["연월"].str[5:7]

# 월 컬럼 정리 — 빈 문자열/NaN 제거
df_base = df_base[df_base["월"].str.match(r"^\d{2}$", na=False)].copy()

df_base["시군구"] = df_base["주소"].astype(str).str[:3].str.replace(" ", "")
df_base["시도"]   = df_base["시군구"].apply(lambda x: "경북" if x in ["경산시", "고령군"] else "대구")

df_base["신규개발량"] = df_base.apply(
    lambda r: calc_monthly_dev(r.get("월 사용예정량"), r.get("등급")), axis=1
)

for col in ["상품", "용도", "업종"]:
    if col in df_base.columns:
        df_base[col] = df_base[col].astype(str).str.strip()

# ───────────────────────────────
# 🔧 사이드바
# ───────────────────────────────
all_years = sorted(df_base["연도"].dropna().unique().tolist(), reverse=True)

with st.sidebar:
    st.header("🔍 조회 설정")

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

    if "상품" in df_s.columns:
        opts = sorted(df_s["상품"].dropna().unique())
        sel = st.multiselect("상품", opts, default=opts)
        df_s = df_s[df_s["상품"].isin(sel)]

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

# ───────────────────────────────
# 📊 요약 지표
# ───────────────────────────────
st.markdown(f"#### 📅 {sel_year}년 공급전 실적")
m1, m2 = st.columns(2)
m1.metric("총 전수",       f"{len(df):,} 건")
m2.metric("총 신규개발량", f"{df['신규개발량'].sum():,.2f}")
st.divider()

# ───────────────────────────────
# 📊 집계 옵션
# ───────────────────────────────
ALL_MONTHS   = [f"{m:02d}" for m in range(1, 13)]
MONTH_LABELS = {f"{m:02d}": f"{m}월" for m in range(1, 13)}

rc1, rc2 = st.columns([2, 1])
with rc1:
    AGG_OPTIONS = {
        "용도별":      ("single",       "용도",  None),
        "상품별":      ("single",       "상품",  None),
        "용도 › 상품": ("hierarchical", "용도",  "상품"),
        "상품 › 용도": ("hierarchical", "상품",  "용도"),
    }
    sel_agg = st.radio("집계 기준", list(AGG_OPTIONS.keys()), index=0, horizontal=True)
with rc2:
    val_label = st.radio("표시 값", ["전수", "신규개발량"], index=0, horizontal=True)

mode, col_a, col_b = AGG_OPTIONS[sel_agg]

# ───────────────────────────────
# 📊 연간 피벗 생성
# ───────────────────────────────
def get_val(df_in, val):
    return len(df_in) if val == "전수" else round(float(df_in["신규개발량"].sum()), 2)

def build_annual_pivot(df_in, val):
    rows, bolds = [], []

    if mode == "single":
        for item in sorted(df_in[col_a].dropna().unique()):
            df_i = df_in[df_in[col_a] == item]
            row = {"항목": item}
            for m in ALL_MONTHS:
                row[MONTH_LABELS[m]] = get_val(df_i[df_i["월"] == m], val)
            row["합계"] = get_val(df_i, val)
            rows.append(row); bolds.append(False)
        total = {"항목": "✅ 합계"}
        for m in ALL_MONTHS:
            total[MONTH_LABELS[m]] = get_val(df_in[df_in["월"] == m], val)
        total["합계"] = get_val(df_in, val)
        rows.append(total); bolds.append(True)

    else:
        for parent in sorted(df_in[col_a].dropna().unique()):
            df_p = df_in[df_in[col_a] == parent]
            sub = {"항목": f"▶ {parent} 소계"}
            for m in ALL_MONTHS:
                sub[MONTH_LABELS[m]] = get_val(df_p[df_p["월"] == m], val)
            sub["합계"] = get_val(df_p, val)
            rows.append(sub); bolds.append(True)
            for child in sorted(df_p[col_b].dropna().unique()):
                df_c = df_p[df_p[col_b] == child]
                row = {"항목": f"　{child}"}
                for m in ALL_MONTHS:
                    row[MONTH_LABELS[m]] = get_val(df_c[df_c["월"] == m], val)
                row["합계"] = get_val(df_c, val)
                rows.append(row); bolds.append(False)
        total = {"항목": "✅ 총합계"}
        for m in ALL_MONTHS:
            total[MONTH_LABELS[m]] = get_val(df_in[df_in["월"] == m], val)
        total["합계"] = get_val(df_in, val)
        rows.append(total); bolds.append(True)

    return pd.DataFrame(rows), pd.Series(bolds)

# ───────────────────────────────
# 📊 테이블 출력
# ───────────────────────────────
if not df.empty:
    tbl, bold_mask = build_annual_pivot(df, val_label)
    month_cols   = [MONTH_LABELS[m] for m in ALL_MONTHS]
    display_cols = ["항목"] + month_cols + ["합계"]
    for c in display_cols[1:]:
        if c not in tbl.columns:
            tbl[c] = 0
    tbl = tbl[display_cols]

    num_fmt = "{:,.2f}" if val_label == "신규개발량" else "{:,.0f}"

    def style_tbl(df_tbl):
        def _row(row):
            if bold_mask.iloc[row.name]:
                return ["font-weight:bold; background-color:#f0f2f6"] * len(row)
            return ["color:#444"] * len(row)
        return df_tbl.style.apply(_row, axis=1).format({c: num_fmt for c in display_cols[1:]})

    st.dataframe(style_tbl(tbl), use_container_width=True, hide_index=True, height=520)

    with st.expander("📋 내역 보기"):
        # 월 컬럼이 "01"~"12" 형식임이 보장된 상태
        month_opts = sorted([m for m in df["월"].dropna().unique() if str(m).strip().isdigit()])
        month_display = ["전체"] + [f"{int(m)}월" for m in month_opts]
        sel_m = st.selectbox("월 선택", month_display, key="detail_month")
        if sel_m == "전체":
            df_d = df
        else:
            sel_m_val = f"{int(sel_m.replace('월', '')):02d}"
            df_d = df[df["월"] == sel_m_val]
        detail_cols = [c for c in DETAIL_COLS if c in df_d.columns]
        st.markdown(f"**{len(df_d):,}건 / 신규개발량 {df_d['신규개발량'].sum():,.2f}**")
        st.dataframe(
            df_d[detail_cols].sort_values("공급일", ascending=False)
            .style.format({"신규개발량": "{:,.2f}"}),
            use_container_width=True, hide_index=True, height=380
        )

    excel_bytes = make_excel(tbl.set_index("항목"), df)
    download_placeholder.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"연간공급전실적_{sel_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    st.info("조건에 맞는 데이터가 없습니다.")