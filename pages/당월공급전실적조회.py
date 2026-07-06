import streamlit as st
import pandas as pd
import io
from utils import load_supply_df

DETAIL_COLS = ["공급일", "신청명", "시군구", "주소", "상품", "용도", "업종",
               "등급", "월 사용예정량", "신규개발량"]

def make_excel(df_summary: pd.DataFrame, df_raw: pd.DataFrame, sel_ym: str) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter",
                        engine_kwargs={"options": {"nan_inf_to_errors": True}}) as writer:
        wb = writer.book
        fmt_header      = wb.add_format({"bold": True, "bg_color": "#4472C4", "font_color": "#FFFFFF", "border": 1, "align": "center"})
        fmt_number      = wb.add_format({"num_format": "#,##0.##", "border": 1})
        fmt_number_bold = wb.add_format({"bold": True, "num_format": "#,##0.##", "bg_color": "#F0F2F6", "border": 1})
        fmt_cell        = wb.add_format({"border": 1})
        fmt_cell_bold   = wb.add_format({"bold": True, "bg_color": "#F0F2F6", "border": 1})
        num_cols = ["전수", "신규개발량"]

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
                    try:
                        v = float(val)
                        v = 0 if pd.isna(v) else v
                    except:
                        v = 0
                    ws1.write(ri + 1, ci, v, fmt_number_bold if is_bold else fmt_number)
                else:
                    ws1.write(ri + 1, ci, str(val) if pd.notna(val) else "",
                              fmt_cell_bold if is_bold else fmt_cell)

        raw_cols = [c for c in DETAIL_COLS if c in df_raw.columns]
        df_out = df_raw[raw_cols].sort_values("공급일", ascending=False).reset_index(drop=True)
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

st.set_page_config(page_title="당월공급전실적조회", layout="wide")
st.title("📅 당월공급전실적조회")

df_base = load_supply_df()
if df_base.empty:
    st.stop()

all_ym = sorted(df_base["연월"].dropna().unique().tolist(), reverse=True)

with st.sidebar:
    st.header("🔍 조회 설정")
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

st.markdown(f"#### 📅 {sel_ym} 공급전 실적")
m1, m2 = st.columns(2)
m1.metric("총 전수",       f"{len(df):,} 건")
m2.metric("총 신규개발량", f"{df['신규개발량'].sum():,.2f}")
st.divider()

def style_bold(df_tbl, bold_mask):
    def _row(row):
        if bold_mask.iloc[row.name]:
            return ["font-weight:bold; background-color:#f0f2f6"] * len(row)
        return ["color:#444"] * len(row)
    return df_tbl.style.apply(_row, axis=1)

def show_detail(df_detail, label):
    cols = [c for c in DETAIL_COLS if c in df_detail.columns]
    st.markdown(f"**📋 내역: {label} — {len(df_detail):,}건 / 신규개발량 {df_detail['신규개발량'].sum():,.2f}**")
    st.dataframe(
        df_detail[cols].sort_values("공급일", ascending=False).style.format({"신규개발량": "{:,.2f}"}),
        use_container_width=True, hide_index=True, height=380
    )

def agg_single(df_in, group_col):
    grp = df_in.groupby(group_col, as_index=False).agg(
        전수=(group_col, "count"), 신규개발량=("신규개발량", "sum")
    ).sort_values("전수", ascending=False)
    grp["신규개발량"] = grp["신규개발량"].round(2)
    total = {group_col: "✅ 합계", "전수": int(grp["전수"].sum()),
             "신규개발량": round(float(grp["신규개발량"].sum()), 2)}
    grp = pd.concat([grp, pd.DataFrame([total])], ignore_index=True)
    return grp, grp[group_col] == "✅ 합계"

def agg_hierarchical(df_in, parent_col, child_col):
    rows, bolds = [], []
    for parent in sorted(df_in[parent_col].dropna().unique()):
        df_p = df_in[df_in[parent_col] == parent]
        rows.append({"구분": f"▶ {parent} 소계", "전수": len(df_p),
                     "신규개발량": round(float(df_p["신규개발량"].sum()), 2)})
        bolds.append(True)
        child_grp = df_p.groupby(child_col, as_index=False).agg(
            전수=(child_col, "count"), 신규개발량=("신규개발량", "sum")
        ).sort_values("전수", ascending=False)
        for _, r in child_grp.iterrows():
            rows.append({"구분": f"　{r[child_col]}", "전수": int(r["전수"]),
                         "신규개발량": round(float(r["신규개발량"]), 2)})
            bolds.append(False)
    rows.append({"구분": "✅ 총합계", "전수": len(df_in),
                 "신규개발량": round(float(df_in["신규개발량"].sum()), 2)})
    bolds.append(True)
    return pd.DataFrame(rows), pd.Series(bolds)

st.markdown("### 📊 항목별 집계")
AGG_OPTIONS = {
    "용도 › 상품": ("hierarchical", "용도", "상품"),
    "상품 › 용도": ("hierarchical", "상품", "용도"),
    "용도별":      ("single",       "용도",  None),
    "상품별":      ("single",       "상품",  None),
}
sel_agg = st.radio("집계 기준", list(AGG_OPTIONS.keys()), index=0, horizontal=True)
mode, col_a, col_b = AGG_OPTIONS[sel_agg]

summary_df = pd.DataFrame()
if not df.empty:
    if mode == "hierarchical":
        tbl, bold_mask = agg_hierarchical(df, col_a, col_b)
        summary_df = tbl.copy()
        st.dataframe(
            style_bold(tbl, bold_mask).format({"전수": "{:,.0f}", "신규개발량": "{:,.2f}"}),
            use_container_width=True, hide_index=True, height=520
        )
        with st.expander("📋 내역 보기"):
            d1, d2 = st.columns(2)
            with d1:
                sel_a_v = st.selectbox(col_a, ["전체"] + sorted(df[col_a].dropna().unique()), key="h_a")
            df_tmp = df if sel_a_v == "전체" else df[df[col_a] == sel_a_v]
            with d2:
                sel_b_v = st.selectbox(col_b, ["전체"] + sorted(df_tmp[col_b].dropna().unique()), key="h_b")
            show_detail(df_tmp if sel_b_v == "전체" else df_tmp[df_tmp[col_b] == sel_b_v], f"{sel_a_v} › {sel_b_v}")
    else:
        tbl, bold_mask = agg_single(df, col_a)
        summary_df = tbl.copy()
        st.dataframe(
            style_bold(tbl, bold_mask).format({"전수": "{:,.0f}", "신규개발량": "{:,.2f}"}),
            use_container_width=True, hide_index=True
        )
        with st.expander("📋 내역 보기"):
            sel_a_v = st.selectbox(col_a, ["전체"] + sorted(df[col_a].dropna().unique()), key="s_a")
            show_detail(df if sel_a_v == "전체" else df[df[col_a] == sel_a_v], sel_a_v)

if not summary_df.empty:
    excel_bytes = make_excel(summary_df, df, sel_ym)
    download_placeholder.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"당월공급전실적_{sel_ym}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )