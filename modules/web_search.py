import concurrent.futures
import html
import ipaddress
import random
import re
import socket
import time
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
    "duckduckgo_lite",
    "duckduckgo_html",
    "bing_html",
]

DUCKDUCKGO_LITE_URL = "https://lite.duckduckgo.com/lite/?q={query}"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/?q={query}"
BING_HTML_URL = "https://www.bing.com/search?q={query}"

DEFAULT_SEARCH_TIMEOUT = 10
DEFAULT_DOWNLOAD_TIMEOUT = 10
DEFAULT_MAX_WORKERS = 5
DEFAULT_NUM_PAGES = 3
MAX_NUM_PAGES = 10
MAX_REDIRECTS = 5

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]

REQUEST_RETRY_COUNT = 2
REQUEST_RETRY_BACKOFF_SECONDS = 0.75

MAX_SEARCH_RESPONSE_LOG_CHARS = 800
MAX_DOWNLOAD_CONTENT_CHARS = 0  # 0 = unlimited before token truncation
MAX_ATTACHMENT_TOKENS = 8192

MIN_EXTRACTED_CONTENT_CHARS = 200
ALLOW_EMPTY_CONTENT_ATTACHMENTS = False
DEDUPE_BY_DOMAIN = False

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
    "bing.com/images",
    "r.bing.com",
)

BLOCKED_EXACT_PATHS = (
    "/html/",
    "/lite/",
)

BLOCKED_RESPONSE_HINTS = (
    "captcha",
    "unusual traffic",
    "enable javascript",
    "verify",
    "blocked",
    "bot",
)

TRAFILATURA_INCLUDE_LINKS = False
TRAFILATURA_OUTPUT_FORMAT = "markdown"
INCLUDE_SIMPLE_HTML_FALLBACK = True
# ============================================================================


class _AnchorExtractor(HTMLParser):
    """Extract links and visible anchor text from HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._current_href = None
        self._text_chunks = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        self._current_href = attrs_dict.get("href", "")
        self._text_chunks = []

    def handle_data(self, data):
        if self._current_href is not None and data:
            self._text_chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._current_href is None:
            return
        text = " ".join(chunk.strip() for chunk in self._text_chunks if chunk.strip()).strip()
        self.anchors.append((self._current_href, text))
        self._current_href = None
        self._text_chunks = []


def _debug_log_response_preview(text):
    if not DEBUG_WEB_SEARCH:
        return
    preview = re.sub(r"\s+", " ", text or "").strip()[:MAX_SEARCH_RESPONSE_LOG_CHARS]
    logger.info(f"[web_search] Response preview: {preview}")


def _looks_like_blocked_response(text):
    lowered = (text or "").lower()
    return any(hint in lowered for hint in BLOCKED_RESPONSE_HINTS)


def _extract_domain(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_blocked_url(url):
    parsed = urlparse(url)
    domain = _extract_domain(url)
    if not domain:
        return True

    if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in BLOCKED_DOMAINS):
        return True

    if parsed.path in BLOCKED_EXACT_PATHS:
        return True

    lowered_url = url.lower()
    if any(keyword in lowered_url for keyword in SKIP_LINK_KEYWORDS):
        return True

    return False


def _validate_url(url):
    """Validate that a URL is safe to fetch (not targeting private/internal networks)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("No hostname in URL")

    # Resolve hostname and check all returned addresses
    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                raise ValueError(f"Access to non-public address {ip} is blocked")
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {hostname}")


def _normalize_search_url(href, base_url):
    if not href:
        return ""

    href = html.unescape(href).strip()
    if not href:
        return ""

    lower_href = href.lower()
    if lower_href.startswith("javascript:") or lower_href.startswith("mailto:"):
        return ""

    resolved = urljoin(base_url, href)
    parsed = urlparse(resolved)

    if "uddg" in parse_qs(parsed.query):
        uddg_value = parse_qs(parsed.query).get("uddg", [""])[0]
        resolved = html.unescape(unquote(uddg_value)).strip() or resolved

    resolved = html.unescape(unquote(resolved)).strip()
    parsed_final = urlparse(resolved)
    if parsed_final.scheme not in ("http", "https"):
        return ""

    if _is_blocked_url(resolved):
        return ""

    return resolved


def _dedupe_results(results):
    deduped = []
    seen_urls = set()
    seen_domains = set()

    for result in results:
        url = result.get("url", "")
        domain = _extract_domain(url)
        if not url or url in seen_urls:
            continue
        if DEDUPE_BY_DOMAIN and domain in seen_domains:
            continue
        seen_urls.add(url)
        if domain:
            seen_domains.add(domain)
        deduped.append(result)

    return deduped


def _simple_html_to_text(content):
    text = re.sub(r"<script.*?>.*?</script>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _request_get(url, timeout, headers=None):
    request_headers = headers or {"User-Agent": random.choice(USER_AGENTS)}
    last_exception = None
    for attempt in range(REQUEST_RETRY_COUNT + 1):
        try:
            response = requests.get(url, headers=request_headers, timeout=timeout)
            return response
        except requests.RequestException as exc:
            last_exception = exc
            if attempt < REQUEST_RETRY_COUNT:
                sleep_seconds = REQUEST_RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(f"[web_search] Request failed (attempt {attempt + 1}), retrying in {sleep_seconds:.2f}s: {exc}")
                time.sleep(sleep_seconds)
    raise last_exception


def _extract_links_from_html(response_text, base_url, num_pages):
    parser = _AnchorExtractor()
    parser.feed(response_text or "")

    candidate_count = len(parser.anchors)
    usable = []

    for href, title in parser.anchors:
        normalized_url = _normalize_search_url(href, base_url)
        if not normalized_url:
            continue
        if _is_blocked_url(normalized_url):
            continue
        try:
            _validate_url(normalized_url)
        except Exception:
            continue

        cleaned_title = re.sub(r"\s+", " ", title or "").strip() or normalized_url
        usable.append({"title": cleaned_title, "url": normalized_url, "content": ""})

        if len(usable) >= num_pages:
            break

    return candidate_count, _dedupe_results(usable)


def _search_backend(name, url_template, query, num_pages, timeout):
    encoded_query = quote_plus(query)
    search_url = url_template.format(query=encoded_query)
    logger.info(f"[web_search] Trying backend {name} for query: {query}")

    try:
        response = _request_get(search_url, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning(f"[web_search] Backend {name} request failed: {exc}")
        return [], name

    response_text = response.text or ""
    blocked = _looks_like_blocked_response(response_text)
    candidate_count, results = _extract_links_from_html(response_text, search_url, num_pages)

    logger.info(
        f"[web_search] {name} status={response.status_code}, response_len={len(response_text)}, "
        f"candidate_links={candidate_count}, usable_links={len(results)}, blocked_like={blocked}"
    )

    if not results:
        _debug_log_response_preview(response_text)

    return results, name


def _search_duckduckgo_lite(query, num_pages, timeout):
    return _search_backend("duckduckgo_lite", DUCKDUCKGO_LITE_URL, query, num_pages, timeout)


def _search_duckduckgo_html(query, num_pages, timeout):
    return _search_backend("duckduckgo_html", DUCKDUCKGO_HTML_URL, query, num_pages, timeout)


def _search_bing_html(query, num_pages, timeout):
    return _search_backend("bing_html", BING_HTML_URL, query, num_pages, timeout)


def get_current_timestamp():
    """Returns the current time in 24-hour format."""
    return datetime.now().strftime("%b %d, %Y %H:%M")


def normalize_search_query(query):
    query = re.sub(r"\s+", " ", (query or "").strip())
    if not query:
        return ""

    instruction_tails = (
        r"\b(reply only with|nothing else|only answer with|respond only with)\b.*$",
    )
    for pattern in instruction_tails:
        query = re.sub(pattern, "", query, flags=re.IGNORECASE).strip(" ,.;")

    return query


def download_web_page(url, timeout=10, include_links=False):
    """Download a web page and extract its main content as Markdown text."""
    import trafilatura

    timeout = timeout or DEFAULT_DOWNLOAD_TIMEOUT

    try:
        _validate_url(url)
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        current_url = url
        response = None
        for _ in range(MAX_REDIRECTS):
            response = requests.get(current_url, headers=headers, timeout=timeout, allow_redirects=False)
            if response.is_redirect and "Location" in response.headers:
                current_url = urljoin(current_url, response.headers["Location"])
                _validate_url(current_url)
                continue
            break

        if response is None:
            logger.warning(f"[web_search] Empty response for {url}")
            return ""

        response.raise_for_status()
        _validate_url(current_url)

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
    except requests.exceptions.RequestException as exc:
        logger.error(f"[web_search] Error downloading {url}: {exc}")
        return ""
    except Exception as exc:
        logger.error(f"[web_search] Unexpected error downloading {url}: {exc}")
        return ""


def perform_web_search(query, num_pages=3, max_workers=5, timeout=10, fetch_content=True):
    """Perform web search and return results, optionally with page content."""
    try:
        normalized_query = normalize_search_query(query)
        if not normalized_query:
            logger.warning("[web_search] Empty query after normalization")
            return []

        num_pages = max(1, min(int(num_pages or DEFAULT_NUM_PAGES), MAX_NUM_PAGES))
        max_workers = max(1, int(max_workers or DEFAULT_MAX_WORKERS))
        timeout = timeout or DEFAULT_SEARCH_TIMEOUT

        logger.info(f"[web_search] Using search query: {normalized_query}")

        backend_results = []
        backend_used = ""
        backend_map = {
            "duckduckgo_lite": _search_duckduckgo_lite,
            "duckduckgo_html": _search_duckduckgo_html,
            "bing_html": _search_bing_html,
        }

        for backend_name in SEARCH_BACKENDS:
            search_fn = backend_map.get(backend_name)
            if not search_fn:
                logger.warning(f"[web_search] Unknown backend configured: {backend_name}")
                continue

            backend_results, backend_used = search_fn(normalized_query, num_pages, timeout)
            logger.info(f"[web_search] {backend_name} returned {len(backend_results)} usable links")
            if backend_results:
                break

        if not backend_results:
            logger.warning("[web_search] No search results found from any backend")
            return []

        if not fetch_content:
            return backend_results

        search_results = [None] * len(backend_results)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(download_web_page, result["url"], timeout): (index, result)
                for index, result in enumerate(backend_results)
            }

            for future in as_completed(future_to_task):
                index, result = future_to_task[future]
                try:
                    content = future.result()
                except Exception as exc:
                    logger.warning(f"[web_search] Download task failed for {result['url']}: {exc}")
                    content = ""

                merged = dict(result)
                merged["content"] = content or ""
                merged["backend"] = backend_used
                search_results[index] = merged

        return [result for result in search_results if result]

    except Exception as exc:
        logger.error(f"Error performing web search: {exc}")
        return []


def truncate_content_by_tokens(content, max_tokens=8192):
    """Truncate content to fit within token limit using binary search."""
    if len(shared.tokenizer.encode(content)) <= max_tokens:
        return content

    left, right = 0, len(content)
    while left < right:
        mid = (left + right + 1) // 2
        if len(shared.tokenizer.encode(content[:mid])) <= max_tokens:
            left = mid
        else:
            right = mid - 1

    return content[:left]


def add_web_search_attachments(history, row_idx, user_message, search_query, state):
    """Perform web search and add results as attachments."""
    if not search_query:
        logger.warning("No search query provided")
        return

    try:
        logger.info(f"Using search query: {search_query}")

        num_pages = int(state.get("web_search_pages", DEFAULT_NUM_PAGES))
        search_results = perform_web_search(search_query, num_pages=num_pages)

        if not search_results:
            logger.warning("No search results found")
            return

        successful_results = [
            result for result in search_results
            if (result.get("content") or "").strip() or ALLOW_EMPTY_CONTENT_ATTACHMENTS
        ]

        if not successful_results:
            logger.warning(
                f"Found {len(search_results)} search result links but 0 pages downloaded successfully."
            )
            return

        key = f"user_{row_idx}"
        if key not in history["metadata"]:
            history["metadata"][key] = {"timestamp": get_current_timestamp()}
        if "attachments" not in history["metadata"][key]:
            history["metadata"][key]["attachments"] = []

        added_count = 0
        for result in successful_results:
            content = result.get("content", "")
            if content and len(content) < MIN_EXTRACTED_CONTENT_CHARS and not ALLOW_EMPTY_CONTENT_ATTACHMENTS:
                continue
            attachment = {
                "name": result.get("title") or result.get("url"),
                "type": "text/html",
                "url": result.get("url", ""),
                "content": truncate_content_by_tokens(content or "", max_tokens=MAX_ATTACHMENT_TOKENS),
            }
            history["metadata"][key]["attachments"].append(attachment)
            added_count += 1

        logger.info(f"Added {added_count} successful web search results as attachments.")

    except Exception as exc:
        logger.error(f"Error in web search: {exc}")


def self_test_web_search():
    queries = [
        "White House Correspondents Dinner yesterday news",
        "latest Reuters world news",
        "OpenAI latest news",
    ]

    for query in queries:
        logger.info(f"[web_search][self-test] Query: {query}")
        links = perform_web_search(query, num_pages=DEFAULT_NUM_PAGES, fetch_content=False)
        logger.info(f"[web_search][self-test] links_found={len(links)}")

        downloaded = perform_web_search(query, num_pages=min(2, DEFAULT_NUM_PAGES), fetch_content=True)
        downloaded_ok = [item for item in downloaded if (item.get("content") or "").strip()]
        logger.info(f"[web_search][self-test] pages_downloaded={len(downloaded_ok)}")

        for item in links[:3]:
            logger.info(f"[web_search][self-test] - {item.get('title')} | {item.get('url')}")
