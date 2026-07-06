import streamlit as st
import pandas as pd
import io
from utils import load_contract_df

DETAIL_COLS = ["연월", "공급신청일", "공급신청명", "시군구", "주소",
               "상품명", "용도", "계약구분", "전수", "시설분담금"]

def make_excel(df_pivot: pd.DataFrame, df_raw: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter",
                        engine_kwargs={"options": {"nan_inf_to_errors": True}}) as writer:
        wb = writer.book
        fmt_header      = wb.add_format({"bold": True, "bg_color": "#4472C4", "font_color": "#FFFFFF", "border": 1, "align": "center"})
        fmt_number      = wb.add_format({"num_format": "#,##0", "border": 1})
        fmt_number_bold = wb.add_format({"bold": True, "num_format": "#,##0", "bg_color": "#F0F2F6", "border": 1})
        fmt_cell        = wb.add_format({"border": 1})
        num_cols = ["전수", "시설분담금"]

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
                    v = 0 if pd.isna(v) else v
                except:
                    v = 0
                ws1.write(ri + 1, ci + 1, v, fmt_number_bold if is_bold else fmt_number)

        raw_cols = [c for c in DETAIL_COLS if c in df_raw.columns]
        df_out = df_raw[raw_cols].sort_values("연월", ascending=False).reset_index(drop=True)
        ws2 = wb.add_worksheet("원본데이터")
        writer.sheets["원본데이터"] = ws2
        for ci, col in enumerate(raw_cols):
            ws2.write(0, ci, col, fmt_header)
            ws2.set_column(ci, ci, 18)
        for ri in range(len(df_out)):
            for ci, col in enumerate(raw_cols):
                val = df_out.iloc[ri][col]
                if col in num_cols:
                    try:
                        v = float(val)
                        v = 0 if pd.isna(v) else v
                    except:
                        v = 0
                    ws2.write(ri + 1, ci, v, fmt_number)
                else:
                    ws2.write(ri + 1, ci, str(val) if pd.notna(val) else "", fmt_cell)
    return output.getvalue()

st.set_page_config(page_title="연간월별계약전실적조회", layout="wide")
st.title("📊 연간월별계약전실적조회")

df_base = load_contract_df()
if df_base.empty:
    st.stop()

all_years = sorted(df_base["연도"].dropna().unique().tolist(), reverse=True)
has_fee = "시설분담금" in df_base.columns

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

st.markdown(f"#### 📅 {sel_year}년 실적")
m1, m2, m3 = st.columns(3)
m1.metric("총 전수", f"{int(df['전수'].sum()):,}")
m2.metric("총 시설분담금", f"{int(df['시설분담금'].sum()):,} 원" if has_fee else "-")
m3.metric("총 건수", f"{len(df):,} 건")
st.divider()

ALL_MONTHS   = [f"{m:02d}" for m in range(1, 13)]
MONTH_LABELS = {f"{m:02d}": f"{m}월" for m in range(1, 13)}

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

def get_val(df_in, col):
    return df_in[col].sum()

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

if not df.empty:
    tbl, bold_mask = build_annual_pivot(df, val_col)
    month_cols = [MONTH_LABELS[m] for m in ALL_MONTHS]
    display_cols = ["항목"] + month_cols + ["합계"]
    for c in display_cols[1:]:
        if c not in tbl.columns:
            tbl[c] = 0
    tbl = tbl[display_cols]

    num_fmt = "{:,.0f}"

    def style_tbl(df_tbl):
        def _row(row):
            if bold_mask.iloc[row.name]:
                return ["font-weight:bold; background-color:#f0f2f6"] * len(row)
            return ["color:#444"] * len(row)
        return df_tbl.style.apply(_row, axis=1).format({c: num_fmt for c in display_cols[1:]})

    st.dataframe(style_tbl(tbl), use_container_width=True, hide_index=True, height=520)

    with st.expander("📋 월별 내역 보기"):
        month_opts = sorted([m for m in df["월"].dropna().unique() if str(m).strip().isdigit()])
        sel_m = st.selectbox("월 선택", ["전체"] + [f"{int(m)}월" for m in month_opts], key="d_ym")
        if sel_m == "전체":
            df_d = df
        else:
            sel_m_val = f"{int(sel_m.replace('월', '')):02d}"
            df_d = df[df["월"] == sel_m_val]
        detail_cols = [c for c in DETAIL_COLS if c in df_d.columns]
        st.markdown(f"**{len(df_d):,}건 / 전수 {int(df_d['전수'].sum()):,}**")
        st.dataframe(df_d[detail_cols].sort_values("연월", ascending=False).style.format(fmt_cols),
                     use_container_width=True, hide_index=True, height=380)

    excel_bytes = make_excel(tbl.set_index("항목"), df)
    download_placeholder.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"연간계약전실적_{sel_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )