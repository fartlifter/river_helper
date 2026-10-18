import html
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
from bs4 import BeautifulSoup

# 지정 출입처 키워드 목록
CITY_KEYWORDS = [
    "서울시", "행정안전부", "인사혁신처", "소방청", "개인정보보호위원회",
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "금천구", "구로구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구",
    "성동구", "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구",
    "종로구", "중구", "중랑구", "서울교통공사", "서울교통공사노조", "버스노조"
]

# 보고 시간대 프리셋 계산 함수
def get_report_timerange(report_type: str, target_date: datetime.date = None):
    tz = ZoneInfo("Asia/Seoul")
    today = target_date or datetime.now(tz).date()

    ranges = {
        "오전보고": (time(0, 0), time(9, 30)),
        "오후보고": (time(9, 0), time(13, 20)),
        "저녁보고1": (time(13, 0), time(17, 0)),
        "저녁보고2": (time(16, 30), time(19, 0)),
    }

    if report_type not in ranges:
        raise ValueError(f"지원하지 않는 보고 유형입니다: {report_type}")

    t_start, t_end = ranges[report_type]
    start_dt = datetime.combine(today, t_start).replace(tzinfo=tz)
    end_dt = datetime.combine(today, t_end).replace(tzinfo=tz)
    return start_dt, end_dt

MEDIA_MAPPING = {
    "chosun": "조선", "joongang": "중앙", "donga": "동아", "hani": "한겨레",
    "khan": "경향", "hankookilbo": "한국", "segye": "세계", "seoul": "서울",
    "kmib": "국민", "munhwa": "문화", "kbs": "KBS", "sbs": "SBS", "mbn.co": "MBN",
    "imnews": "MBC", "jtbc": "JTBC", "ichannela": "채널A", "tvchosun": "TV조선",
    "mk": "매경", "sedaily": "서경", "hankyung": "한경", "news1": "뉴스1",
    "newsis": "뉴시스", "yna": "연합", "mt": "머투", "fnnews": "파뉴",
    "etoday.co": "이투데이", "edaily.co": "이데일리", "tf.co": "더팩트",
    "yonhapnewstv.co": "연뉴TV", "ytn.co": "YTN", "nocutnews.co": "노컷",
    "asiae.co": "아경", "biz.heraldcorp": "헤경", "kukinews": "쿠키"
}

EXCLUSIVE_PATTERN = re.compile(r"(\[|\(|\【|\<|\xdb|\ⓧ)?\s*단\s*독\s*(\]|\)|\】|\>|\=|\:|\s|$|\])", re.IGNORECASE)

def is_exclusive_title(title_text: str) -> bool:
    return bool(EXCLUSIVE_PATTERN.search(title_text))

def get_content(client: httpx.Client, url: str, selector: str) -> str:
    try:
        res = client.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}, timeout=6.0)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, "html.parser")
        content = soup.select_one(selector)
        return content.get_text(separator="\n", strip=True) if content else ""
    except:
        return ""

def fetch_articles_concurrently(article_list, selector, selected_keywords=None, progress_callback=None, source_name=""):
    keywords = selected_keywords if selected_keywords is not None else CITY_KEYWORDS
    results = []
    total = len(article_list)
    if total == 0:
        return results

    limits = httpx.Limits(max_keepalive_connections=35, max_connections=40)
    with httpx.Client(timeout=6.0, limits=limits) as shared_client:
        def worker(art):
            content = get_content(shared_client, art['url'], selector)
            if not content:
                return None
            matched = [kw for kw in keywords if kw in content or kw in art.get('title', '')]
            if keywords and not matched:
                return None
            art['content'] = content
            art['matched_kw'] = matched
            return art

        with ThreadPoolExecutor(max_workers=25) as executor:
            futures = {executor.submit(worker, art): art for art in article_list}
            for i, future in enumerate(as_completed(futures)):
                try:
                    res = future.result()
                    if res:
                        results.append(res)
                except:
                    pass
                if progress_callback:
                    progress_callback((i + 1) / total, f"[{source_name}] 키워드 대조 중... ({i+1}/{total}건)")

    results.sort(key=lambda x: x["datetime"], reverse=True)
    return results

def parse_yonhap(start_dt, end_dt, selected_keywords=None, progress_callback=None):
    collected = []
    page = 1
    past_streak = 0
    MAX_PAST_STREAK = 5

    if progress_callback:
        progress_callback(0.0, "🔍 [연합뉴스] 기사 목록 탐색 중...")

    with httpx.Client(headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}, timeout=8.0) as client:
        while True:
            url = f"https://www.yna.co.kr/society/all/{page}"
            try:
                res = client.get(url)
                if res.status_code != 200:
                    break
            except:
                break

            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select("ul.list01 > li[data-cid]")
            if not items:
                break

            for item in items:
                cid = item.get("data-cid")
                title_tag = item.select_one(".title01")
                time_tag = item.select_one(".txt-time")
                if not (cid and title_tag and time_tag):
                    continue

                try:
                    time_str = time_tag.text.strip()
                    dt = datetime.strptime(f"{start_dt.year}-{time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Seoul"))
                except:
                    continue

                if dt < start_dt:
                    past_streak += 1
                    if past_streak >= MAX_PAST_STREAK:
                        return fetch_articles_concurrently(collected, "div.story-news.article", selected_keywords, progress_callback, "연합뉴스")
                    continue
                else:
                    past_streak = 0

                if start_dt <= dt <= end_dt:
                    collected.append({
                        "source": "연합뉴스",
                        "datetime": dt,
                        "title": title_tag.text.strip(),
                        "url": f"https://www.yna.co.kr/view/{cid}"
                    })

            page += 1

    return fetch_articles_concurrently(collected, "div.story-news.article", selected_keywords, progress_callback, "연합뉴스")

def parse_newsis(start_dt, end_dt, selected_keywords=None, progress_callback=None):
    collected = []
    page = 1
    past_streak = 0
    MAX_PAST_STREAK = 5

    if progress_callback:
        progress_callback(0.0, "🔍 [뉴시스] 기사 목록 탐색 중...")

    with httpx.Client(headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}, timeout=8.0) as client:
        while True:
            url = f"https://www.newsis.com/society/list/?cid=10200&scid=10201&page={page}"
            try:
                res = client.get(url)
                if res.status_code != 200:
                    break
            except:
                break

            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select("ul.articleList2 > li")
            if not items:
                break

            for item in items:
                title_tag = item.select_one("p.tit > a")
                time_tag = item.select_one("p.time")
                if not (title_tag and time_tag):
                    continue

                match = re.search(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", time_tag.text)
                if not match:
                    continue

                dt = datetime.strptime(match.group(), "%Y.%m.%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Seoul"))

                if dt < start_dt:
                    past_streak += 1
                    if past_streak >= MAX_PAST_STREAK:
                        return fetch_articles_concurrently(collected, "div.viewer", selected_keywords, progress_callback, "뉴시스")
                    continue
                else:
                    past_streak = 0

                if start_dt <= dt <= end_dt:
                    collected.append({
                        "source": "뉴시스",
                        "datetime": dt,
                        "title": title_tag.get_text(strip=True),
                        "url": "https://www.newsis.com" + title_tag.get("href", "")
                    })

            page += 1

    return fetch_articles_concurrently(collected, "div.viewer", selected_keywords, progress_callback, "뉴시스")

def naver_extract_title_and_body_fast(client: httpx.Client, url: str):
    try:
        res = client.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}, timeout=4.5)
        if res.status_code != 200:
            return None, None
        soup = BeautifulSoup(res.text, "html.parser")
        if "n.news.naver.com" in url:
            title_tag = soup.find("div", class_="media_end_head_title")
            content_div = soup.find("div", id="newsct_article")
        else:
            return None, None
        title = title_tag.get_text(strip=True) if title_tag else None
        body = content_div.get_text(separator="\n", strip=True) if content_div else None
        return title, body
    except:
        return None, None

def naver_extract_media_name(url):
    try:
        domain = url.split("//")[-1].split("/")[0]
        parts = domain.split(".")
        composite_key = f"{parts[-3]}.{parts[-2]}" if len(parts) >= 3 else parts[0]
        if composite_key in MEDIA_MAPPING:
            return MEDIA_MAPPING[composite_key]
        for part in reversed(parts):
            if part in MEDIA_MAPPING:
                return MEDIA_MAPPING[part]
        return composite_key.upper()
    except:
        return "기타"

def parse_naver_exclusive(start_dt, end_dt, selected_keywords=None, client_id="", client_secret="", progress_callback=None):
    keywords = selected_keywords if selected_keywords is not None else CITY_KEYWORDS
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    seen_links = set()
    candidate_items = []
    past_articles_streak = 0
    MAX_PAST_STREAK = 20
    should_stop = False

    steps = list(range(1, 1001, 100))
    total_steps = len(steps)

    with httpx.Client(timeout=5.0) as api_client:
        for idx, start_index in enumerate(steps):
            if should_stop:
                break
            if progress_callback:
                progress_callback(idx / total_steps, f"🔍 [단독기사] 네이버 API 탐색 중... (후보 {len(candidate_items)}건 발견)")

            params = {"query": "[단독]", "sort": "date", "display": 100, "start": start_index}
            try:
                res = api_client.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params=params)
                if res.status_code != 200:
                    break
                items = res.json().get("items", [])
                if not items:
                    break
            except:
                break

            for item in items:
                link = item.get("link")
                if link in seen_links:
                    continue

                pub_date_str = item.get("pubDate")
                try:
                    pub_dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z")
                except:
                    continue

                if pub_dt < start_dt:
                    past_articles_streak += 1
                    if past_articles_streak >= MAX_PAST_STREAK:
                        should_stop = True
                        break
                    continue
                else:
                    past_articles_streak = 0

                if pub_dt > end_dt:
                    continue

                raw_api_title = html.unescape(re.sub(r"<.*?>", "", item.get("title", "")))
                if not is_exclusive_title(raw_api_title):
                    continue

                seen_links.add(link)
                candidate_items.append((item, pub_dt))

    all_articles = []
    total_candidates = len(candidate_items)

    limits = httpx.Limits(max_keepalive_connections=35, max_connections=40)
    with httpx.Client(timeout=4.5, limits=limits) as shared_fetch_client:
        def process_candidate(candidate):
            item, pub_dt = candidate
            link = item.get("link")
            title, body = naver_extract_title_and_body_fast(shared_fetch_client, link)

            if not title or not body:
                return None

            # 본문 또는 제목 키워드 매칭
            matched_kw = [kw for kw in keywords if kw in body or kw in title]
            if keywords and not matched_kw:
                return None

            media = naver_extract_media_name(item.get("originallink", ""))
            clean_title = re.sub(r"\[단독\]|\(단독\)|【단독】|ⓧ단독|^단독\s*[:-]?", "", title).strip()

            return {
                "source": "단독",
                "media": media,
                "title": clean_title,
                "datetime": pub_dt,
                "content": body,
                "url": link,
                "matched_kw": matched_kw
            }

        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = {executor.submit(process_candidate, c): c for c in candidate_items}
            for i, future in enumerate(as_completed(futures)):
                res = future.result()
                if res:
                    all_articles.append(res)
                if progress_callback and total_candidates > 0:
                    progress_callback((i + 1) / total_candidates, f"📄 [단독기사] 본문 키워드 매칭 중... ({i+1}/{total_candidates}건)")

    all_articles.sort(key=lambda x: x["datetime"], reverse=True)
    return all_articles
