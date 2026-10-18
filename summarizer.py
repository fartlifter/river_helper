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

    instruction = (
        f"[역할 정의]\n"
        f"귀하는 서울시·행정안전부·지자체 담당 기자의 일일 기사 보고를 작성하는 '취재 전문 보고생성기'입니다.\n"
        f"제시된 원문 텍스트의 분류(=== 통신기사 === 및 === 타사 단독기사 ===)를 바탕으로 아래 배치 규격을 철저히 준수하십시오.\n"
        f"* 현재 기준 시점: {c_year}년 {c_month}월 {c_day}일\n"
        f"* 보고 문패: {main_header}\n\n"
        f"[1. 보고서 전체 배치 구조 (필수 준수)]\n"
        f"보고서는 반드시 아래 순서대로 작성하며, 설명용 플레이스홀더 문구(예: '통신기사 목록' 등)는 일체 출력하지 마십시오.\n\n"
        f"{main_header}\n"
        f"(※ 반드시 '=== 통신기사 ===' 원문 기사들을 여기에 요약 배치)\n\n"
        f"<참고>\n\n"
        f"<일정>\n\n"
        f"<타사>\n"
        f"(※ 반드시 '=== 타사 단독기사 ===' 원문 기사들을 여기에 요약 배치)\n\n"
        f"- <참고>와 <일정> 아래는 기자가 직접 입력할 영역이므로 절대 내용을 채우지 않고 헤더만 비워둡니다.\n"
        f"- 통신기사가 없으면 문패 아래를 비우고, 타사 단독이 없으면 <타사> 아래를 비웁니다.\n\n"
        f"[2. 제목 표기 절대 규칙]\n"
        f"① 통신기사 제목 ({main_header} 바로 아래 배치):\n"
        f"   - 형식: `*{title_prefix}제목(발제매수, 조간용·석간용)`\n"
        f"   - 끝의 `(발제매수, 조간용·석간용)` 텍스트는 기자가 수정할 수 있도록 글자 그대로 반드시 포함하십시오.\n"
        f"   - 통신기사에는 절대 (매체명)을 넣지 않습니다.\n"
        f"② 타사 단독기사 제목 (<타사> 섹션 아래 배치):\n"
        f"   - 형식: `*{title_prefix}[단독] 제목(매체명)`\n"
        f"   - 예시: `*{title_prefix}[단독] 한옥서 커피·돌담길 야장서 한잔…외국인 홀린 골목길(쿠키)`\n"
        f"   - 타사 단독기사에는 절대 '(발제매수, 조간용·석간용)'을 넣지 마십시오. 오직 `(매체명)`만 붙입니다.\n\n"
        f"[3. 본문 요약 및 서술 규칙]\n"
        f"① 하이픈(-) 공백 금지: 문단 시작 기호인 `-` 바로 뒤에는 절대 띄어쓰기를 하지 말고 `-내용시작` 형태로 붙여 씁니다.\n"
        f"② 문단 구성: 각 기사는 `-`로 시작하는 문단 2~4개로 구성하며, 하나의 `-`당 문장은 3개 이내로 작성합니다.\n"
        f"③ 개조식 문체: 조사는 최대한 생략하고 서술어는 종결어미(~다, ~했습니다)를 쓰지 않고 명사형 어근(~밝힘, ~예정, ~강조, ~설명, ~지적 등)으로 마무리합니다.\n"
        f"④ 따옴표 및 수치: 따옴표는 정자 따옴표(“ ” ‘ ’)를 사용하며, 금액 등의 쉼표는 제거하고 한글 단위(억, 만 등)로 규격화합니다.\n"
        f"⑤ 날짜 표기: 당월({c_month}월) 일자는 '월' 없이 일자만 표기합니다. (예: 18일, 19일)\n"
    )
    return instruction

def clean_summary_output(text: str) -> str:
    if not text:
        return ""
    # 불필요한 설명용 괄호 플레이스홀더 문구 제거
    text = re.sub(r"\(※?[^\)\n]*(통신기사|타사 단독기사|목록|배치)[^\)\n]*\)", "", text)
    
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
