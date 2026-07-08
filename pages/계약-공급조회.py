import streamlit as st
import pandas as pd
import io
import datetime
from utils import load_contract_df, load_supply_df

st.set_page_config(page_title="계약-공급 연계 현황", layout="wide")
st.title("🔗 계약-공급 연계 현황")

with st.spinner("데이터 로딩 중..."):
    df_c = load_contract_df()
    df_s_raw = load_supply_df()

if df_c.empty or df_s_raw.empty:
    st.error("데이터 로드 실패")
    st.stop()

# 계약전 연월 컬럼명 변경
df_c["연월_계약"] = df_c["연월"]

# 공급전 연월 컬럼
df_s_raw["연월_공급"] = df_s_raw["연월"]

# 공급전 컬럼 전체에 _공급 접미사 (공급신청번호 제외)
df_s_renamed = df_s_raw.rename(columns={
    col: f"{col}_공급" for col in df_s_raw.columns if col != "공급신청번호"
})

# ───────────────────────────────
# 🔧 사이드바
# ───────────────────────────────
all_ym_c = sorted(df_c["연월_계약"].dropna().unique().tolist(), reverse=True)
all_ym_s = sorted(df_s_raw["연월_공급"].dropna().unique().tolist(), reverse=True)
current_year = str(datetime.datetime.now().year)

with st.sidebar:
    st.header("🔍 조회 설정")

    # 계약전 연월 — 멀티셀렉트, 기본값: 가장 최근 연월
    st.markdown("#### 📋 계약전 연월 (공급신청일)")
    sel_ym_c = st.multiselect(
        "연월 선택",
        all_ym_c,
        default=[all_ym_c[0]] if all_ym_c else [],
        key="sel_ym_c"
    )
    if not sel_ym_c:
        st.warning("⚠️ 최소 1개 이상의 연월을 선택하세요")

    # 공급전 기간 — 기본값: 올해 1월 ~ 최신월
    st.markdown("#### 🏠 공급전 기간 (공급일)")
    default_start_s = f"{current_year}-01"
    start_idx_s = all_ym_s.index(default_start_s) if default_start_s in all_ym_s else len(all_ym_s) - 1
    c3, c4 = st.columns(2)
    with c3:
        start_s = st.selectbox("시작", all_ym_s, index=start_idx_s, key="start_s")
    with c4:
        end_s = st.selectbox("종료", all_ym_s, index=0, key="end_s")
    if start_s > end_s:
        st.warning("⚠️ 시작이 종료보다 늦습니다")

    st.divider()
    st.markdown("#### 🔎 상세 필터 (계약전 기준)")

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
# 필터 적용
# ───────────────────────────────
sel_ym_s = [ym for ym in all_ym_s if start_s <= ym <= end_s]

df_c_filtered = df_f5[df_f5["연월_계약"].isin(sel_ym_c)].copy()
df_s_filtered = df_s_renamed[df_s_renamed["연월_공급_공급"].isin(sel_ym_s)].copy()

# ───────────────────────────────
# LEFT JOIN
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

ym_c_label = ", ".join(sel_ym_c) if sel_ym_c else "선택 없음"

st.markdown("### 📊 매칭 현황 요약")
st.caption(f"계약전: {ym_c_label}  |  공급전: {start_s} ~ {end_s}")

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
    st.dataframe(df_join[display_cols].sort_values("공급신청일", ascending=False),
                 use_container_width=True, hide_index=True, height=600)
with tab2:
    st.dataframe(df_done[display_cols].sort_values("소요일수", ascending=False),
                 use_container_width=True, hide_index=True, height=600)
with tab3:
    st.dataframe(df_undone[display_cols].sort_values("공급신청일", ascending=False),
                 use_container_width=True, hide_index=True, height=600)

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
    ym_c_file = "_".join(sel_ym_c) if len(sel_ym_c) <= 3 else f"{sel_ym_c[-1]}~{sel_ym_c[0]}"
    excel_bytes = make_excel(df_join, df_done, df_undone)
    download_placeholder.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"계약공급연계_{ym_c_file}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )