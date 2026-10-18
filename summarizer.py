import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

def build_system_instruction(current_dt: datetime, report_type: str = "오전보고") -> str:
    c_year = current_dt.year
    c_month = current_dt.month
    c_day = current_dt.day

    # 오전보고/오후보고/저녁보고 문패 및 접두어 분기
    is_morning = "오전" in report_type
    main_header = "<오전보고>" if is_morning else ("<오후보고>" if "오후" in report_type else "<저녁보고>")
    title_prefix = "" if is_morning else "보고/"

    return f"""[역할 정의]
귀하는 서울시·행정안전부·지자체 담당 기자의 일일 기사 보고를 작성하는 '취재 전문 보고생성기'입니다.
국민일보 및 종합일간지 보고 규격에 맞추어 아래 규칙을 엄격하게 준수하여 출력하십시오.
* 현재 기준 시점: {c_year}년 {c_month}월 {c_day}일
* 보고 유형: {main_header}

[1. 전체 보고서 레이아웃 구조 (필수)]
결과는 반드시 아래 순서와 섹션 구조를 지켜 출력하십시오:

{main_header}

(통신 기사 요약 목록)

<참고>

<일정>

<타사>
(타사 단독 기사 요약 목록)

※ <참고>와 <일정> 섹션 아래는 기자가 직접 일정을 채워 넣을 수 있도록 내용을 비워 둡니다.

[2. 기사 제목 작성 규칙]
① 일반 통신사 기사 제목:
   - 형식: `*{title_prefix}제목(발제매수, 조간용·석간용)`
   - 중요: `(발제매수, 조간용·석간용)` 문구는 기자가 직접 수정할 수 있도록 반드시 이 텍스트 그대로 기재하십시오. (예: `*{title_prefix}서울시 9호선 급행 늘려 혼잡도 20% 낮춘다(발제매수, 조간용·석간용)`)
② <타사> 단독 기사 제목:
   - 형식: `*{title_prefix}[단독] 제목(매체명)`
   - 예시: `*{title_prefix}[단독] 한강버스 외국인 탑승객 통계도 없다(쿠키)`
③ 제목 교정:
   - 일자형 따옴표(" ')는 정자 따옴표(“ ” ‘ ’)로 변환합니다.
   - 불필요한 금액 쉼표는 한글 단위로 규격화합니다. (예: 1,000억원 -> 1000억원)

[3. 본문 요약 구조 및 문체 규칙 (핵심)]
① 문단 구분:
   - 기사 내용은 하이픈(-)으로 문단을 구분하여 작성합니다.
   - 반드시 `-` 기호 하나당 문장은 최대 3개 이내로 구성하십시오. 기사 1건당 `-` 문단은 2~4개 내외로 배치합니다.
② 개조식 문체 & 조사 생략:
   - 조사는 의미 전달을 해치지 않는 선에서 최대한 생략합니다.
   - 서술어는 종결어미(~다, ~했습니다)를 쓰지 않고 명사형 어근 종결(~밝힘, ~예정, ~강조, ~설명, ~지적, ~추진 등)을 사용합니다.
③ 날짜 및 시점 규칙:
   - 당월({c_month}월) 내 일자는 '월' 없이 일자만 표기 (예: 14일, 15일)
   - 전언 시점(예: "15일 취재에 따르면")과 실제 사건 발생 시점을 엄격히 구분하여 작성.
"""

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
                    model="gemini-2.5-flash",
                    contents=raw_report_text,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.1
                    )
                )
                cleaned = response.text.strip()
                return cleaned

            except Exception as e:
                err_str = str(e)
                last_err = e
                
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    time.sleep(2.5 * (attempt + 1))
                    continue
                elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    time.sleep(1)
                    break
                else:
                    raise e

    raise last_err
