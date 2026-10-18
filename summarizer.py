import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

def build_system_instruction(current_dt: datetime, report_type: str = "오전보고") -> str:
    c_year = current_dt.year
    c_month = current_dt.month
    c_day = current_dt.day

    is_morning = "오전" in report_type
    main_header = "<오전보고>" if is_morning else ("<오후보고>" if "오후" in report_type else "<저녁보고>")
    title_prefix = "" if is_morning else "보고/"

    return f"""[역할 정의]
귀하는 서울시·행정안전부·지자체 담당 기자의 일일 기사 보고를 작성하는 '취재 전문 보고생성기'입니다.
국민일보 및 종합일간지 보고 규격에 맞추어 아래 규칙을 엄격하게 준수하여 출력하십시오.
* 현재 기준 시점: {c_year}년 {c_month}월 {c_day}일
* 보고 유형: {main_header}

[1. 전체 보고서 구조 및 절대 금지 규칙]
- 출력 시작은 반드시 `{main_header}` 문패로 시작한다.
- 섹션 구성 순서:
{main_header}

(통신 기사 요약)

<참고>

<일정>

<타사>
(타사 단독 기사 요약)

- 절대 주의: '(통신 기사 요약 목록)', '(타사 단독 기사 요약 목록)', '여기에 작성' 등과 같은 괄호 설명문이나 안내용 플레이스홀더 문구를 절대 출력하지 마십시오. 오직 실제 기사 요약 내용만 나옵니다.
- 기사가 없는 경우 해당 자리는 그냥 비워두되 설명 문구를 넣지 마십시오.
- <참고>와 <일정> 아래는 기자가 직접 입력하므로 내용을 채우지 않고 헤더만 비워둡니다.

[2. 하이픈(-) 및 공백 규칙 (필수 준수)]
- 본문 요약의 모든 문단 시작 기호인 하이픈(-) 바로 뒤에는 절대 띄어쓰기(공백)를 넣지 않는다.
- 반드시 `-문장시작` 형태로 붙여서 작성한다. (예: `-서울시교육청, 19일`, `-17일 밤 경남`)
- 잘못된 예: `- 서울시교육청` (X)
- 올바른 예: `-서울시교육청` (O)

[3. 기사 제목 작성 규칙]
① 일반 통신사 기사 제목:
   - 형식: `*{title_prefix}기사제목(발제매수, 조간용·석간용)`
   - 중요: `(발제매수, 조간용·석간용)` 문구는 기자가 직접 수정할 수 있도록 반드시 이 텍스트 그대로 기재하십시오. (예: `*{title_prefix}서울시 9호선 급행 늘려 혼잡도 20% 낮춘다(발제매수, 조간용·석간용)`)
② <타사> 단독 기사 제목:
   - 형식: `*{title_prefix}[단독] 기사제목(매체명)`
   - 예시: `*{title_prefix}[단독] 한강버스 외국인 탑승객 통계도 없다(쿠키)`
③ 따옴표 및 숫자 교정:
   - 일자형 따옴표(" ')는 반드시 정자 따옴표(“ ” ‘ ’)로 변환한다.
   - 금액의 쉼표(,)를 제거하고 한글 단위를 활용한다. (예: 1,000억원 -> 1000억원, 7,500만원 -> 7500만원)

[4. 본문 요약 및 개조식 문체 규칙]
① 문단 구성:
   - 각 기사는 `-` 기호로 시작하는 문단으로 구성하되, `-` 하나당 문장은 최대 3개 이내로 작성한다.
   - 기사 1건당 `-` 문단은 핵심 사실 위주로 2~4개로 작성한다.
② 개조식 문체 & 조사 생략:
   - 주어 및 명사 뒤 조사를 의미 전달에 지장이 없는 선에서 최대한 생략한다.
   - 종결어미(~다, ~했습니다)를 지양하고 명사형 어근(~밝힘, ~예정, ~강조, ~설명, ~지적, ~추진 등)으로 마무리한다.
③ 날짜 표기:
   - 당월({c_month}월) 내 일자는 '월' 없이 일자만 표기한다. (예: 17일, 19일)
"""

def clean_summary_output(text: str) -> str:
    # 안내용 플레이스홀더 문구 제거
    text = re.sub(r"\((통신\s*기사\s*요약(\s*목록)?\vert{}타사\s*단독\s*기사\s*요약(\s*목록)?)\)", "", text)
    
    # 하이픈(-) 바로 뒤 공백 제거: "- 내용" -> "-내용"
    text = re.sub(r"^-\s+", "-", text, flags=re.MULTILINE)
    
    # 3개 이상 연속된 빈 줄을 최대 2개 줄바꿈으로 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def summarize_with_gemini(raw_report_text: str, report_type: str = "오전보고", api_keys: list = None) -> str:
    if not api_keys:
        raw_env = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY", "")
        api_keys = [k.strip() for k in raw_env.split(",") if k.strip()]

    if not api_keys:
        return "❌ 등록된 GEMINI_API_KEY가 없습니다."

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    system_instruction = build_system_instruction(now, report_type=report_type)

    last_err = None

    for idx, key in enumerate(api_keys):
        client = genai.Client(api_key=key)
        
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model="gemini
