import concurrent.futures
import html
import ipaddress
import os
import random
import re
import socket
import time
import xml.etree.ElementTree as ET
from concurrent.futures import as_completed
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests

from modules import shared
from modules.logging_colors import logger


# ============================================================================
# WEB SEARCH HYPERPARAMETERS
# ============================================================================

WEB_SEARCH_ENABLED_DEFAULT = True
DEBUG_WEB_SEARCH = True

SEARCH_BACKENDS = [
    "tavily",
    "gdelt",
    "google_news_rss",
    "duckduckgo_lite",
    "duckduckgo_html",
]

# Optional API-backed provider
ENABLE_TAVILY = True
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_TOPIC_DEFAULT = "general"
TAVILY_TOPIC_NEWS = "news"
TAVILY_SEARCH_DEPTH = "basic"
TAVILY_INCLUDE_RAW_CONTENT = False
TAVILY_INCLUDE_ANSWER = False
TAVILY_MAX_RESULTS = 8
TAVILY_TIMEOUT = 15

# No-key news provider
ENABLE_GDELT = True
GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MODE = "ArtList"
GDELT_FORMAT = "json"
GDELT_MAX_RECORDS = 10
GDELT_SORT = "datedesc"
GDELT_TIMEOUT = 15

# RSS fallback
ENABLE_GOOGLE_NEWS_RSS = True
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
GOOGLE_NEWS_RSS_TIMEOUT = 15
GOOGLE_NEWS_RSS_MAX_RESULTS = 10

# DuckDuckGo last-resort fallback
ENABLE_DUCKDUCKGO = True
DUCKDUCKGO_LITE_URL = "https://lite.duckduckgo.com/lite/?q={query}&kl=us-en&kp=-2"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/?q={query}&kl=us-en&kp=-2"

DEFAULT_SEARCH_TIMEOUT = 15
DEFAULT_DOWNLOAD_TIMEOUT = 15
DEFAULT_MAX_WORKERS = 5
DEFAULT_NUM_PAGES = 5
MAX_NUM_PAGES = 10
MAX_REDIRECTS = 5

REQUEST_RETRY_COUNT = 3
REQUEST_RETRY_BACKOFF_SECONDS = 1.25

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

MAX_SEARCH_RESPONSE_LOG_CHARS = 1200
MAX_DOWNLOAD_CONTENT_CHARS = 0
MAX_ATTACHMENT_TOKENS = 8192

MIN_EXTRACTED_CONTENT_CHARS = 80
ALLOW_EMPTY_CONTENT_ATTACHMENTS = False
DEDUPE_BY_DOMAIN = False

REQUIRE_SEARCH_STATUS_200 = True
REJECT_BLOCKED_LIKE_SEARCH_PAGES = True

BLOCKED_RESPONSE_HINTS = (
    "captcha",
    "unusual traffic",
    "please prove you are human",
    "verify you are human",
    "automated requests",
    "too many requests",
    "access denied",
    "403 forbidden",
    "429 too many requests",
)

TRAFILATURA_INCLUDE_LINKS = False
TRAFILATURA_OUTPUT_FORMAT = "markdown"
INCLUDE_SIMPLE_HTML_FALLBACK = True

NEWS_QUERY_HINTS = (
    "news",
    "latest",
    "breaking",
    "today",
    "yesterday",
    "this morning",
    "this afternoon",
    "last night",
    "what happened",
    "recent",
    "update",
    "white house",
    "correspondents dinner",
)

WEB_FAILURE_ATTACH_STATUS = True

SKIP_LINK_KEYWORDS = (
    "duckduckgo.com/y.js",
    "duckduckgo.com/i.js",
    "duckduckgo.com/params",
    "javascript:",
    "mailto:",
    "#",
)

BLOCKED_DOMAINS = (
    "duckduckgo.com",
    "lite.duckduckgo.com",
    "html.duckduckgo.com",
)

BLOCKED_EXACT_PATHS = (
    "/html/",
    "/lite/",
)

# ============================================================================


_LAST_WEB_SEARCH_STATUS = {
    "query": "",
    "provider": "",
    "providers_attempted": [],
    "results_found": 0,
    "pages_downloaded": 0,
    "failed": False,
}


class _AnchorExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._current_href = None
        self._text_chunks = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._current_href = dict(attrs).get("href", "")
            self._text_chunks = []

    def handle_data(self, data):
        if self._current_href is not None and data:
            self._text_chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._current_href is not None:
            text = " ".join(chunk.strip() for chunk in self._text_chunks if chunk.strip()).strip()
            self.anchors.append((self._current_href, text))
            self._current_href = None
            self._text_chunks = []


def get_current_timestamp():
    return datetime.now().strftime("%b %d, %Y %H:%M")


def _debug_log_response_preview(text):
    if DEBUG_WEB_SEARCH:
        preview = re.sub(r"\s+", " ", text or "").strip()[:MAX_SEARCH_RESPONSE_LOG_CHARS]
        logger.info(f"[web_search] Response preview: {preview}")


def _looks_like_news_query(query):
    lowered = (query or "").lower()
    return any(hint in lowered for hint in NEWS_QUERY_HINTS)


def _looks_like_blocked_response(text):
    lowered = (text or "").lower()
    return any(hint in lowered for hint in BLOCKED_RESPONSE_HINTS)


def _extract_domain(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("No hostname in URL")
    for _, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise ValueError(f"Access to non-public address {ip} is blocked")


def _request_get(url, timeout, headers=None, allow_redirects=True, params=None):
    request_headers = headers or {"User-Agent": random.choice(USER_AGENTS)}
    last_exception = None
    for attempt in range(REQUEST_RETRY_COUNT + 1):
        try:
            return requests.get(url, headers=request_headers, timeout=timeout, allow_redirects=allow_redirects, params=params)
        except requests.RequestException as exc:
            last_exception = exc
            if attempt < REQUEST_RETRY_COUNT:
                time.sleep(REQUEST_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_exception


def _request_post(url, timeout, headers=None, json=None):
    request_headers = headers or {"User-Agent": random.choice(USER_AGENTS)}
    last_exception = None
    for attempt in range(REQUEST_RETRY_COUNT + 1):
        try:
            return requests.post(url, headers=request_headers, timeout=timeout, json=json)
        except requests.RequestException as exc:
            last_exception = exc
            if attempt < REQUEST_RETRY_COUNT:
                time.sleep(REQUEST_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_exception


def _normalize_search_url(href, base_url):
    href = html.unescape((href or "").strip())
    if not href:
        return ""
    if href.lower().startswith(("javascript:", "mailto:")):
        return ""
    resolved = urljoin(base_url, href)
    parsed = urlparse(resolved)
    if "uddg" in parse_qs(parsed.query):
        resolved = html.unescape(unquote(parse_qs(parsed.query).get("uddg", [""])[0])).strip() or resolved
    resolved = html.unescape(unquote(resolved)).strip()
    parsed_final = urlparse(resolved)
    if parsed_final.scheme not in ("http", "https"):
        return ""
    return resolved


def _dedupe_results(results):
    deduped = []
    seen_urls = set()
    seen_domains = set()
    for result in results:
        url = result.get("url", "")
        if not url or url in seen_urls:
            continue
        domain = _extract_domain(url)
        if DEDUPE_BY_DOMAIN and domain in seen_domains:
            continue
        seen_urls.add(url)
        if domain:
            seen_domains.add(domain)
        deduped.append(result)
    return deduped


def _normalize_result(title="", url="", content="", published="", source="", provider="", downloaded=False):
    return {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "content": (content or "").strip(),
        "published": (published or "").strip(),
        "source": (source or "").strip(),
        "provider": (provider or "").strip(),
        "downloaded": bool(downloaded),
    }


def _search_tavily(query, num_pages, timeout, *, news_mode=False):
    if not ENABLE_TAVILY:
        return []
    api_key = (os.getenv(TAVILY_API_KEY_ENV) or "").strip()
    if not api_key:
        logger.info(f"[web_search] Tavily unavailable: missing {TAVILY_API_KEY_ENV}")
        return []

    payload = {
        "query": query,
        "topic": TAVILY_TOPIC_NEWS if news_mode else TAVILY_TOPIC_DEFAULT,
        "search_depth": TAVILY_SEARCH_DEPTH,
        "include_raw_content": TAVILY_INCLUDE_RAW_CONTENT,
        "include_answer": TAVILY_INCLUDE_ANSWER,
        "max_results": min(num_pages, TAVILY_MAX_RESULTS),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": random.choice(USER_AGENTS),
    }
    try:
        response = _request_post(TAVILY_SEARCH_URL, timeout=timeout or TAVILY_TIMEOUT, headers=headers, json=payload)
        if REQUIRE_SEARCH_STATUS_200 and response.status_code != 200:
            logger.warning(f"[web_search] Tavily HTTP {response.status_code}")
            _debug_log_response_preview(response.text)
            return []
        data = response.json() if response.content else {}
    except Exception as exc:
        logger.warning(f"[web_search] Tavily failed: {exc}")
        return []

    out = []
    for item in data.get("results", [])[: min(num_pages, TAVILY_MAX_RESULTS)]:
        url = item.get("url", "")
        if not url:
            continue
        out.append(_normalize_result(
            title=item.get("title") or url,
            url=url,
            content=item.get("content") or item.get("raw_content") or "",
            published=item.get("published_date") or item.get("published") or "",
            source=item.get("source") or _extract_domain(url),
            provider="tavily",
            downloaded=False,
        ))
    return _dedupe_results(out)


def _search_gdelt(query, num_pages, timeout):
    if not ENABLE_GDELT:
        return []
    params = {
        "query": query,
        "mode": GDELT_MODE,
        "format": GDELT_FORMAT,
        "maxrecords": min(num_pages, GDELT_MAX_RECORDS),
        "sort": GDELT_SORT,
    }
    try:
        response = _request_get(GDELT_DOC_API_URL, timeout=timeout or GDELT_TIMEOUT, params=params)
        if REQUIRE_SEARCH_STATUS_200 and response.status_code != 200:
            logger.warning(f"[web_search] GDELT HTTP {response.status_code}")
            _debug_log_response_preview(response.text)
            return []
        data = response.json() if response.content else {}
    except Exception as exc:
        logger.warning(f"[web_search] GDELT failed: {exc}")
        return []

    out = []
    for item in data.get("articles", [])[: min(num_pages, GDELT_MAX_RECORDS)]:
        url = item.get("url", "")
        if not url:
            continue
        out.append(_normalize_result(
            title=item.get("title") or url,
            url=url,
            content=item.get("seendate") or item.get("socialimage") or item.get("title") or "",
            published=item.get("seendate") or item.get("date") or "",
            source=item.get("sourcecountry") or item.get("domain") or _extract_domain(url),
            provider="gdelt",
            downloaded=False,
        ))
    return _dedupe_results(out)


def _search_google_news_rss(query, num_pages, timeout):
    if not ENABLE_GOOGLE_NEWS_RSS:
        return []
    url = GOOGLE_NEWS_RSS_URL.format(query=quote_plus(query))
    try:
        response = _request_get(url, timeout=timeout or GOOGLE_NEWS_RSS_TIMEOUT)
        if REQUIRE_SEARCH_STATUS_200 and response.status_code != 200:
            logger.warning(f"[web_search] Google News RSS HTTP {response.status_code}")
            _debug_log_response_preview(response.text)
            return []
        root = ET.fromstring(response.text)
    except Exception as exc:
        logger.warning(f"[web_search] Google News RSS failed: {exc}")
        return []

    out = []
    for item in root.findall(".//item")[: min(num_pages, GOOGLE_NEWS_RSS_MAX_RESULTS)]:
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        pub_date = item.findtext("pubDate", default="")
        description = item.findtext("description", default="")
        source = item.find("source")
        source_text = source.text.strip() if source is not None and source.text else _extract_domain(link)
        if not link:
            continue
        out.append(_normalize_result(
            title=title or link,
            url=link,
            content=description or title,
            published=pub_date,
            source=source_text,
            provider="google_news_rss",
            downloaded=False,
        ))
    return _dedupe_results(out)


def _is_generic_duckduckgo_failure_page(text, candidate_links, usable_links):
    lowered = (text or "").lower()
    return (
        "<title>duckduckgo</title>" in lowered
        and 'canonical" href="https://duckduckgo.com/' in lowered
        and candidate_links <= 2
        and usable_links == 0
    )


def _extract_links_from_html(response_text, base_url, num_pages, provider):
    parser = _AnchorExtractor()
    parser.feed(response_text or "")
    candidate_count = len(parser.anchors)
    usable = []
    seen_urls = set()

    for href, title in parser.anchors:
        normalized_url = _normalize_search_url(href, base_url)
        if not normalized_url or normalized_url in seen_urls:
            continue
        lowered_url = normalized_url.lower()
        if any(keyword in lowered_url for keyword in SKIP_LINK_KEYWORDS):
            continue
        if any(_extract_domain(normalized_url) == blocked for blocked in BLOCKED_DOMAINS):
            continue
        try:
            _validate_url(normalized_url)
        except Exception:
            continue
        seen_urls.add(normalized_url)
        usable.append(_normalize_result(
            title=re.sub(r"\s+", " ", title or "").strip() or normalized_url,
            url=normalized_url,
            content="",
            provider=provider,
            downloaded=False,
        ))
        if len(usable) >= num_pages:
            break

    return candidate_count, _dedupe_results(usable)


def _search_backend(name, url_template, query, num_pages, timeout):
    search_url = url_template.format(query=quote_plus(query))
    try:
        response = _request_get(search_url, timeout=timeout)
    except Exception as exc:
        logger.warning(f"[web_search] Backend {name} request failed: {exc}")
        return []

    response_text = response.text or ""
    if REQUIRE_SEARCH_STATUS_200 and response.status_code != 200:
        logger.warning(f"[web_search] Backend {name} failed: HTTP {response.status_code}")
        _debug_log_response_preview(response_text)
        return []

    blocked = _looks_like_blocked_response(response_text)
    candidate_count, results = _extract_links_from_html(response_text, search_url, num_pages, name)
    generic_failure = _is_generic_duckduckgo_failure_page(response_text, candidate_count, len(results))

    logger.info(
        f"[web_search] {name} status={response.status_code}, response_len={len(response_text)}, "
        f"candidate_links={candidate_count}, usable_links={len(results)}, blocked_like={blocked}, generic_failure={generic_failure}"
    )

    if REJECT_BLOCKED_LIKE_SEARCH_PAGES and (blocked or generic_failure):
        logger.warning(f"[web_search] Backend {name} treated as provider failure due to blocked/generic page")
        _debug_log_response_preview(response_text)
        return []

    if not results:
        _debug_log_response_preview(response_text)
    return results


def _search_duckduckgo_lite(query, num_pages, timeout):
    if not ENABLE_DUCKDUCKGO:
        return []
    return _search_backend("duckduckgo_lite", DUCKDUCKGO_LITE_URL, query, num_pages, timeout)


def _search_duckduckgo_html(query, num_pages, timeout):
    if not ENABLE_DUCKDUCKGO:
        return []
    return _search_backend("duckduckgo_html", DUCKDUCKGO_HTML_URL, query, num_pages, timeout)


def _simple_html_to_text(content):
    text = re.sub(r"<script.*?>.*?</script>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_search_query(query):
    query = re.sub(r"\s+", " ", (query or "").strip())
    if not query:
        return ""
    query = re.sub(r"\b(reply only with|nothing else|only answer with|respond only with)\b.*$", "", query, flags=re.IGNORECASE).strip(" ,.;")
    return query


def download_web_page(url, timeout=10, include_links=False):
    import trafilatura

    timeout = timeout or DEFAULT_DOWNLOAD_TIMEOUT
    try:
        _validate_url(url)
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        current_url = url
        response = None
        for _ in range(MAX_REDIRECTS):
            response = _request_get(current_url, timeout=timeout, headers=headers, allow_redirects=False)
            if response.is_redirect and "Location" in response.headers:
                current_url = urljoin(current_url, response.headers["Location"])
                _validate_url(current_url)
                continue
            break

        if response is None:
            return ""

        response.raise_for_status()
        extracted = trafilatura.extract(
            response.text,
            include_links=include_links if include_links is not None else TRAFILATURA_INCLUDE_LINKS,
            output_format=TRAFILATURA_OUTPUT_FORMAT,
            url=current_url,
        )

        if not extracted and INCLUDE_SIMPLE_HTML_FALLBACK:
            extracted = _simple_html_to_text(response.text)

        if MAX_DOWNLOAD_CONTENT_CHARS and extracted:
            extracted = extracted[:MAX_DOWNLOAD_CONTENT_CHARS]
        return extracted or ""
    except Exception as exc:
        logger.warning(f"[web_search] Error downloading {url}: {exc}")
        return ""


def _download_and_enrich(results, max_workers, timeout):
    if not results:
        return results, 0

    enriched = [None] * len(results)
    downloaded_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(download_web_page, result.get("url", ""), timeout): (idx, result)
            for idx, result in enumerate(results)
            if result.get("url")
        }
        for future in as_completed(future_map):
            idx, result = future_map[future]
            content = ""
            try:
                content = future.result() or ""
            except Exception as exc:
                logger.warning(f"[web_search] Download task failed for {result.get('url')}: {exc}")
            merged = dict(result)
            if content.strip():
                merged["content"] = content
                merged["downloaded"] = True
                downloaded_count += 1
            enriched[idx] = merged

    for idx, item in enumerate(enriched):
        if item is None:
            enriched[idx] = dict(results[idx])
    return enriched, downloaded_count


def perform_web_search(query, num_pages=3, max_workers=5, timeout=10, fetch_content=True):
    global _LAST_WEB_SEARCH_STATUS
    normalized_query = normalize_search_query(query)
    if not normalized_query:
        logger.warning("[web_search] Empty query after normalization")
        return []

    num_pages = max(1, min(int(num_pages or DEFAULT_NUM_PAGES), MAX_NUM_PAGES))
    max_workers = max(1, int(max_workers or DEFAULT_MAX_WORKERS))
    timeout = timeout or DEFAULT_SEARCH_TIMEOUT

    provider_map = {
        "tavily": lambda q, n, t: _search_tavily(q, n, t, news_mode=_looks_like_news_query(q)),
        "gdelt": _search_gdelt,
        "google_news_rss": _search_google_news_rss,
        "duckduckgo_lite": _search_duckduckgo_lite,
        "duckduckgo_html": _search_duckduckgo_html,
    }

    attempted = []
    for backend_name in SEARCH_BACKENDS:
        search_fn = provider_map.get(backend_name)
        if not search_fn:
            continue

        logger.info(f"[web_search] Trying provider {backend_name}...")
        attempted.append(backend_name)
        try:
            provider_results = search_fn(normalized_query, num_pages, timeout)
        except Exception as exc:
            logger.warning(f"[web_search] Provider {backend_name} failed: {exc}")
            continue

        if not provider_results:
            logger.info(f"[web_search] Provider {backend_name} returned no usable results")
            continue

        logger.info(f"[web_search] Provider {backend_name} returned {len(provider_results)} article candidates")
        downloaded_count = 0
        if fetch_content:
            provider_results, downloaded_count = _download_and_enrich(provider_results, max_workers, timeout)
            logger.info(f"[web_search] Downloaded {downloaded_count}/{len(provider_results)} article pages")

        _LAST_WEB_SEARCH_STATUS = {
            "query": normalized_query,
            "provider": backend_name,
            "providers_attempted": attempted,
            "results_found": len(provider_results),
            "pages_downloaded": downloaded_count,
            "failed": False,
        }
        return provider_results

    logger.warning(f"[web_search] All providers failed for query: {normalized_query}")
    _LAST_WEB_SEARCH_STATUS = {
        "query": normalized_query,
        "provider": "",
        "providers_attempted": attempted,
        "results_found": 0,
        "pages_downloaded": 0,
        "failed": True,
    }
    return []


def truncate_content_by_tokens(content, max_tokens=8192):
    if not content:
        return ""
    tokenizer = getattr(shared, "tokenizer", None)
    if tokenizer is None:
        return content
    if len(tokenizer.encode(content)) <= max_tokens:
        return content
    left, right = 0, len(content)
    while left < right:
        mid = (left + right + 1) // 2
        if len(tokenizer.encode(content[:mid])) <= max_tokens:
            left = mid
        else:
            right = mid - 1
    return content[:left]


def _build_metadata_only_content(result):
    return (
        f"Title: {result.get('title', '')}\n"
        f"Source: {result.get('source', '')}\n"
        f"Published: {result.get('published', '')}\n"
        f"URL: {result.get('url', '')}\n"
        f"Snippet: {result.get('content', '')}\n"
        f"Provider: {result.get('provider', '')}"
    ).strip()


def _build_success_status_block(status):
    return (
        "[WEB SEARCH STATUS]\n"
        f"Query: {status.get('query', '')}\n"
        f"Provider: {status.get('provider', '')}\n"
        f"Results found: {status.get('results_found', 0)}\n"
        f"Pages downloaded: {status.get('pages_downloaded', 0)}\n"
        "Use the attached web results as current external context.\n"
        "[END WEB SEARCH STATUS]"
    )


def _build_failure_status_block(query):
    return (
        "[WEB SEARCH STATUS]\n"
        f"A live web search was attempted for: \"{query}\"\n"
        "No usable results were retrieved. This is a retrieval/backend failure, not evidence that the event does not exist.\n"
        "Do not claim the event did not happen. Tell the user the web retrieval failed and suggest checking backend logs or trying again.\n"
        "Never infer that an event did not happen solely because web retrieval returned no results.\n"
        "[END WEB SEARCH STATUS]"
    )


def add_web_search_attachments(history, row_idx, user_message, search_query, state):
    if not search_query:
        logger.warning("[web_search] No search query provided")
        return

    queries = search_query if isinstance(search_query, list) else [search_query]
    queries = [normalize_search_query(q) for q in queries if normalize_search_query(q)]
    if not queries:
        return

    num_pages = int(state.get("web_search_pages", DEFAULT_NUM_PAGES))
    key = f"user_{row_idx}"
    history.setdefault("metadata", {}).setdefault(key, {"timestamp": get_current_timestamp()})
    history["metadata"][key].setdefault("attachments", [])

    best_results = []
    last_query = ""
    for query in queries:
        last_query = query
        results = perform_web_search(query, num_pages=num_pages, max_workers=DEFAULT_MAX_WORKERS, timeout=DEFAULT_SEARCH_TIMEOUT, fetch_content=True)
        if results:
            best_results = results
            break

    status = _LAST_WEB_SEARCH_STATUS
    if not best_results:
        if WEB_FAILURE_ATTACH_STATUS:
            history["metadata"][key]["attachments"].append({
                "name": "web_search_status.txt",
                "type": "text/plain",
                "url": "",
                "content": _build_failure_status_block(last_query or user_message),
            })
        return

    attachments = []
    downloaded_count = 0
    for result in best_results:
        content = (result.get("content") or "").strip()
        if result.get("downloaded") and content:
            if len(content) < MIN_EXTRACTED_CONTENT_CHARS and not ALLOW_EMPTY_CONTENT_ATTACHMENTS:
                continue
            attachment_content = truncate_content_by_tokens(content, max_tokens=MAX_ATTACHMENT_TOKENS)
            downloaded_count += 1
        else:
            metadata_content = _build_metadata_only_content(result)
            if not metadata_content.strip():
                continue
            attachment_content = truncate_content_by_tokens(metadata_content, max_tokens=MAX_ATTACHMENT_TOKENS)

        attachments.append({
            "name": result.get("title") or result.get("url") or "web_result",
            "type": "text/html",
            "url": result.get("url", ""),
            "content": attachment_content,
        })

    status_block = _build_success_status_block(status)
    history["metadata"][key]["attachments"].append({
        "name": "web_search_status.txt",
        "type": "text/plain",
        "url": "",
        "content": status_block,
    })
    history["metadata"][key]["attachments"].extend(attachments)
    logger.info(f"[web_search] Added {len(attachments)} web context attachments")


def self_test_web_search():
    queries = [
        "White House Correspondents Dinner yesterday news",
        "White House Correspondents Dinner recent news 2026",
        "latest Reuters world news",
        "OpenAI latest news",
    ]

    for query in queries:
        logger.info(f"[web_search][self-test] Query: {query}")
        results = perform_web_search(query, num_pages=DEFAULT_NUM_PAGES, max_workers=DEFAULT_MAX_WORKERS, timeout=DEFAULT_SEARCH_TIMEOUT, fetch_content=True)
        status = _LAST_WEB_SEARCH_STATUS
        logger.info(f"[web_search][self-test] providers_attempted={status.get('providers_attempted', [])}")
        logger.info(f"[web_search][self-test] provider_used={status.get('provider', '')}")
        logger.info(f"[web_search][self-test] results_found={status.get('results_found', 0)}")
        logger.info(f"[web_search][self-test] downloads_succeeded={status.get('pages_downloaded', 0)}")

        metadata_only_count = 0
        for item in results[:5]:
            if not item.get("downloaded"):
                metadata_only_count += 1
            logger.info(f"[web_search][self-test] - {item.get('title')} | {item.get('url')}")
        logger.info(f"[web_search][self-test] metadata_fallback_used={metadata_only_count > 0}")
