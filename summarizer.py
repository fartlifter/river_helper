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

    # 중괄호 문법 충돌을 방지하기 위해 일반 문자열과 f-string을 안전하게 결합
    instruction = (
        f"[역할 정의]\n"
        f"귀하는 서울시·행정안전부·지자체 담당 기자의 일일 기사 보고를 작성하는 '취재 전문 보고생성기'입니다.\n"
        f"국민일보 및 종합일간지 보고 규격에 맞추어 아래 규칙을 엄격하게 준수하여 출력하십시오.\n"
        f"* 현재 기준 시점: {c_year}년 {c_month}월 {c_day}일\n"
        f"* 보고 유형: {main_header}\n\n"
        f"[1. 전체 보고서 구조 및 절대 금지 규칙]\n"
        f"- 출력 시작은 반드시 `{main_header}` 문패로 시작한다.\n"
        f"- 섹션 구성 순서:\n"
        f"{main_header}\n\n"
        f"<참고>\n\n"
        f"<일정>\n\n"
        f"<타사>\n\n"
        f"- 절대 주의: '(통신 기사 요약 목록)', '(타사 단독 기사 요약 목록)', '여기에 작성' 등과 같은 괄호 설명문이나 안내용 플레이스홀더 문구를 절대 출력하지 마십시오. 오직 실제 기사 요약 내용만 기재합니다.\n"
        f"- <참고>와 <일정> 아래는 기자가 직접 입력하므로 내용을 채우지 않고 헤더만 비워둡니다.\n\n"
        f"[2. 하이픈(-) 및 공백 규칙 (필수 준수)]\n"
        f"- 본문 요약의 모든 문단 시작 기호인 하이픈(-) 바로 뒤에는 절대 띄어쓰기(공백)를 넣지 않는다.\n"
        f"- 반드시 `-문장시작` 형태로 붙여서 작성한다. (예: `-서울시교육청, 19일`, `-17일 밤 경남`)\n"
        f"- 잘못된 예: `- 서울시교육청`\n"
        f"- 올바른 예: `-서울시교육청`\n\n"
        f"[3. 기사 제목 작성 규칙]\n"
        f"① 일반 통신사 기사 제목:\n"
        f"   - 형식: `*{title_prefix}기사제목(발제매수, 조간용·석간용)`\n"
        f"   - 중요: `(발제매수, 조간용·석간용)` 문구는 기자가 직접 수정할 수 있도록 반드시 이 텍스트 그대로 기재하십시오.\n"
        f"② <타사> 단독 기사 제목:\n"
        f"   - 형식: `*{title_prefix}[단독] 기사제목(매체명)`\n"
        f"③ 따옴표 및 숫자 교정:\n"
        f"   - 일자형 따옴표(\" ')는 반드시 유니코드 정자 따옴표(“ ” ‘ ’)로 변환한다.\n"
        f"   - 금액의 불필요한 쉼표(,)를 제거하고 만·억 단위는 한글로 규격화한다. (예: 1,000억원 -> 1000억원, 7,500만원 -> 7500만원)\n\n"
        f"[4. 본문 요약 및 개조식 문체 규칙]\n"
        f"① 문단 구성:\n"
        f"   - 각 기사는 `-` 기호로 시작하는 문단으로 구성하되, `-` 하나당 문장은 최대 3개 이내로 작성한다.\n"
        f"   - 기사 1건당 `-` 문단은 2~4개로 작성한다.\n"
        f"② 개조식 문체 & 조사 생략:\n"
        f"   - 조사는 의미 전달을 해치지 않는 선에서 최대한 생략한다.\n"
        f"   - 종결어미(~다, ~했습니다)를 지양하고 명사형 어근(~밝힘, ~예정, ~강조, ~설명, ~지적, ~추진 등)으로 마무리한다.\n"
        f"③ 날짜 표기:\n"
        f"   - 당월({c_month}월) 내 일자는 '월' 없이 일자만 표기한다. (예: 17일, 19일)\n"
    )
    return instruction

def clean_summary_output(text: str) -> str:
    if not text:
        return ""
    # 불필요한 설명용 괄호 플레이스홀더 문구 제거
    text = re.sub(r"\(통신\s*기사\s*요약(\s*목록)?\)", "", text)
    text = re.sub(r"\(타사\s*단독\s*기사\s*요약(\s*목록)?\)", "", text)
    
    # 하이픈(-) 바로 뒤 공백 제거: "- 내용" -> "-내용"
    text = re.sub(r"^-\s+", "-", text, flags=re.MULTILINE)
    
    # 연속된 3개 이상의 빈 줄 정리
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
                    model="gemini-2.5-flash",
                    contents=raw_report_text,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.1
                    )
                )
                cleaned = clean_summary_output(response.text)
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
