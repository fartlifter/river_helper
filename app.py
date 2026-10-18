import streamlit as st
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import os
import re
import html
from collector import (
    CITY_KEYWORDS, parse_yonhap, parse_newsis, parse_naver_exclusive
)
from summarizer import summarize_with_gemini

# === 보안 인증 정보 로드 ===
def get_secret(key_name, default_val=""):
    try:
        if key_name in st.secrets:
            return st.secrets[key_name]
    except Exception:
        pass
    return os.environ.get(key_name, default_val)

NAVER_CLIENT_ID = get_secret("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = get_secret("NAVER_CLIENT_SECRET", "")

raw_keys = get_secret("GEMINI_API_KEYS", get_secret("GEMINI_API_KEY", ""))
GEMINI_API_KEYS = [k.strip() for k in str(raw_keys).split(",") if k.strip()]

st.set_page_config(page_title="서울시·행안부 보고생성기", layout="wide")

# === st.code 박스 내부 글자 잘림 방지 (자동 줄바꿈 & 복사 아이콘 유지) ===
st.markdown("""
<style>
div[data-testid="stCode"] pre {
    white-space: pre-wrap !important;
    word-break: break-all !important;
    overflow-x: hidden !important;
}
div[data-testid="stCode"] code {
    white-space: pre-wrap !important;
    word-break: break-all !important;
}
</style>
""", unsafe_allow_html=True)

st.title("📰 강민이의 보고를 돕습니다")

now = datetime.now(ZoneInfo("Asia/Seoul"))

# 세션 상태 초기화
if "report_slot" not in st.session_state:
    st.session_state.report_slot = "오전보고"
if "start_dt" not in st.session_state:
    st.session_state.start_dt = datetime.combine(now.date(), dtime(0, 0)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
if "end_dt" not in st.session_state:
    st.session_state.end_dt = datetime.combine(now.date(), dtime(9, 30)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
if "wire_articles" not in st.session_state:
    st.session_state.wire_articles = []
if "naver_articles" not in st.session_state:
    st.session_state.naver_articles = []
if "gemini_summary" not in st.session_state:
    st.session_state.gemini_summary = ""

def format_highlighted_content(content_text: str, keywords: list) -> str:
    safe_text = html.escape(content_text)
    for kw in keywords:
        if kw:
            safe_text = re.sub(
                f"({re.escape(kw)})",
                r'<mark style="background-color: #fffb91; font-weight: bold;">\1</mark>',
                safe_text
            )
    return safe_text.replace("\n", "<br><br>")

st.subheader("⏱️ 수집 시간대 선택")
col_b1, col_b2, col_b3, col_b4, col_b5 = st.columns(5)

def set_time_range(slot: str, start_h: int, start_m: int, end_h: int, end_m: int):
    st.session_state.report_slot = slot
    current_time = datetime.now(ZoneInfo("Asia/Seoul"))
    slot_start = datetime.combine(current_time.date(), dtime(start_h, start_m)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
    slot_end = datetime.combine(current_time.date(), dtime(end_h, end_m)).replace(tzinfo=ZoneInfo("Asia/Seoul"))
    st.session_state.start_dt = slot_start
    st.session_state.end_dt = slot_end

with col_b1:
    if st.button("🌅 오전 (00:00~09:30)", use_container_width=True):
        set_time_range("오전보고", 0, 0, 9, 30)
with col_b2:
    if st.button("☀️ 오후 (09:00~13:20)", use_container_width=True):
        set_time_range("오후보고", 9, 0, 13, 20)
with col_b3:
    if st.button("🌇 저녁1 (13:00~17:00)", use_container_width=True):
        set_time_range("저녁보고1", 13, 0, 17, 0)
with col_b4:
    if st.button("🌙 저녁2 (16:30~19:00)", use_container_width=True):
        set_time_range("저녁보고2", 16, 30, 19, 0)
with col_b5:
    if st.button("⚙️ 수동 설정", use_container_width=True):
        st.session_state.report_slot = "수동설정"

col_d1, col_d2 = st.columns(2)
with col_d1:
    s_date = st.date_input("시작 날짜", value=st.session_state.start_dt.date())
    s_time = st.time_input("시작 시각", value=st.session_state.start_dt.time())
with col_d2:
    e_date = st.date_input("종료 날짜", value=st.session_state.end_dt.date())
    e_time = st.time_input("종료 시각", value=st.session_state.end_dt.time())

start_dt = datetime.combine(s_date, s_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))
end_dt = datetime.combine(e_date, e_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))
st.session_state.start_dt = start_dt
st.session_state.end_dt = end_dt

st.info(f"선택 모드: **{st.session_state.report_slot}** | 수집 범위: `{start_dt.strftime('%Y-%m-%d %H:%M')}` ~ `{end_dt.strftime('%Y-%m-%d %H:%M')}`")

# 키워드 멀티셀렉트 (지정 키워드 33개 기본 전체 선택)
selected_keywords = st.multiselect(
    "수집 키워드 선택",
    options=CITY_KEYWORDS,
    default=CITY_KEYWORDS
)

# === 기사 수집 실행 ===
if st.button("🚀 기사 수집 시작", type="primary", use_container_width=True):
    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def update_progress(val, text):
        progress_bar.progress(min(max(val, 0.0), 1.0))
        status_text.info(text)

    yonhap = parse_yonhap(start_dt, end_dt, selected_keywords, progress_callback=update_progress)
    newsis = parse_newsis(start_dt, end_dt, selected_keywords, progress_callback=update_progress)
    wire = yonhap + newsis
    naver = parse_naver_exclusive(start_dt, end_dt, selected_keywords, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, progress_callback=update_progress)

    progress_bar.empty()
    status_text.empty()

    st.session_state.wire_articles = wire
    st.session_state.naver_articles = naver
    st.session_state.gemini_summary = ""
    st.success(f"✅ 수집 완료: 통신기사 {len(wire)}건 (연합 {len(yonhap)}건 / 뉴시스 {len(newsis)}건) | 단독기사 {len(naver)}건")

# === 기사 리스트 선택 ===
selected_wires = []
selected_navers = []

st.divider()
st.subheader(f"◆ 통신기사 ({len(st.session_state.wire_articles)}건)")
if st.session_state.wire_articles:
    for idx, art in enumerate(st.session_state.wire_articles):
        matched = art.get('matched_kw', [])
        with st.expander(f"{art['source']} | {art['title']}"):
            checked = st.checkbox("이 기사 선택", key=f"w_chk_{idx}", value=True)
            st.markdown(f"[🔗 원문 링크]({art['url']})")
            st.caption(f"{art['datetime'].strftime('%Y-%m-%d %H:%M')} | **일치 키워드:** {', '.join(matched) if matched else '없음'}")
            
            highlighted = format_highlighted_content(art['content'], matched)
            st.markdown(f'<div style="line-height: 1.8;">{highlighted}</div>', unsafe_allow_html=True)
            
            if checked:
                selected_wires.append(art)
else:
    st.caption("수집된 통신기사가 없습니다.")

st.divider()
st.subheader(f"◆ 타사 단독기사 ({len(st.session_state.naver_articles)}건)")
if st.session_state.naver_articles:
    for idx, art in enumerate(st.session_state.naver_articles):
        matched = art.get('matched_kw', [])
        with st.expander(f"[{art['media']}] {art['title']}"):
            checked = st.checkbox("이 기사 선택", key=f"n_chk_{idx}", value=True)
            st.markdown(f"[🔗 원문 링크]({art['url']})")
            st.caption(f"{art['datetime'].strftime('%Y-%m-%d %H:%M')} | **일치 키워드:** {', '.join(matched) if matched else '없음'}")
            
            highlighted = format_highlighted_content(art['content'], matched)
            st.markdown(f'<div style="line-height: 1.8;">{highlighted}</div>', unsafe_allow_html=True)
            
            if checked:
                selected_navers.append(art)
else:
    st.caption("수집된 단독기사가 없습니다.")

# === LLM 전달용 Raw 취합본 빌더 ===
def build_raw_report_for_llm(wires, navers):
    chunks = []
    if wires:
        chunks.append("=== 통신기사 ===")
        for w in wires:
            chunks.append(f"[{w['source']}] {w['title']}\n{w['content'].strip()}\n")
            
    if navers:
        chunks.append("=== 타사 단독기사 ===")
        for n in navers:
            chunks.append(f"[{n['media']}] {n['title']}\n{n['content'].strip()}\n")
            
    return "\n".join(chunks).strip()

raw_report_text = build_raw_report_for_llm(selected_wires, selected_navers)

# === 최종 보고서 생성창 (좌우 2열 분할) ===
st.divider()
st.subheader("📋 최종 보고서 생성 및 복사")

col_t1, col_t2 = st.columns([1, 1])

with col_t1:
    st.markdown("**1️⃣ 선택 기사 원문 취합본**")
    display_raw = raw_report_text if (selected_wires or selected_navers) else "선택된 기사가 없습니다."
    st.code(display_raw, language="markdown")
    st.caption("↗️ 박스 우측 상단의 복사 아이콘을 눌러 전체 복사할 수 있습니다.")

with col_t2:
    st.markdown("**2️⃣ Gemini 정제 보고서**")
    if st.button("🤖 보고서 생성 실행 (Gemini 요약)", type="primary", use_container_width=True):
        if not (selected_wires or selected_navers):
            st.warning("요약할 기사를 먼저 체크박스로 선택해주세요.")
        else:
            with st.spinner("지침에 맞춰 보고서를 작성 중입니다..."):
                try:
                    summary_result = summarize_with_gemini(
                        raw_report_text, 
                        report_type=st.session_state.report_slot, 
                        api_keys=GEMINI_API_KEYS
                    )
                    st.session_state.gemini_summary = summary_result
                except Exception as e:
                    st.error(f"요약 중 오류가 발생했습니다: {e}")
                
    display_sum = st.session_state.gemini_summary if st.session_state.gemini_summary else "보고서 생성 실행 버튼을 누르면 정제된 결과가 여기에 표시됩니다."
    st.code(display_sum, language="markdown")
    if st.session_state.gemini_summary:
        st.caption("↗️ 박스 우측 상단의 복사 아이콘을 누르면 전체 복사됩니다.")
