import concurrent.futures
import ipaddress
import socket
from concurrent.futures import as_completed
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests

from modules import shared
from modules.logging_colors import logger


def _validate_url(url):
    """Validate that a URL is safe to fetch (not targeting private/internal networks)."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("No hostname in URL")

    # Resolve hostname and check all returned addresses
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                raise ValueError(f"Access to non-public address {ip} is blocked")
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {hostname}")


def get_current_timestamp():
    """Returns the current time in 24-hour format"""
    return datetime.now().strftime('%b %d, %Y %H:%M')


def download_web_page(url, timeout=10, include_links=False):
    """
    Download a web page and extract its main content as Markdown text.
    """
    import trafilatura

    try:
        _validate_url(url)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        max_redirects = 5
        for _ in range(max_redirects):
            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
            if response.is_redirect and 'Location' in response.headers:
                url = urljoin(url, response.headers['Location'])
                _validate_url(url)
            else:
                break

        response.raise_for_status()

        result = trafilatura.extract(
            response.text,
            include_links=include_links,
            output_format='markdown',
            url=url
        )
        return result or ""
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading {url}: {e}")
        return ""
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return ""


SEARCH_MAX_RESULTS_DEFAULT = 10
PAGE_FETCH_TIMEOUT = 10
PAGE_EXCERPT_CHARS = 4000


def _get_ddgs_client():
    try:
        from ddgs import DDGS
        return DDGS
    except Exception:
        try:
            from duckduckgo_search import DDGS
            return DDGS
        except Exception as exc:
            raise RuntimeError(
                "DuckDuckGo search package is not installed. Install `ddgs` or `duckduckgo_search`."
            ) from exc


def duckduckgo_search(query, max_results=SEARCH_MAX_RESULTS_DEFAULT):
    query = (query or '').strip()
    if not query:
        return []

    DDGS = _get_ddgs_client()
    results = []
    with DDGS() as ddgs:
        for item in ddgs.text(
            query,
            max_results=max_results,
            safesearch='moderate',
            region='wt-wt',
        ):
            title = str(item.get('title') or '').strip()
            url = str(item.get('href') or item.get('url') or '').strip()
            snippet = str(item.get('body') or item.get('snippet') or '').strip()
            if not url:
                continue

            results.append({
                'title': title,
                'url': url,
                'snippet': snippet,
                'source': 'duckduckgo',
                'rank': len(results) + 1,
            })

    return results


def perform_web_search(query, num_pages=3, max_workers=5, timeout=PAGE_FETCH_TIMEOUT, fetch_content=True, max_results=SEARCH_MAX_RESULTS_DEFAULT):
    query = (query or '').strip()
    if not query:
        return {'query': query, 'provider': 'duckduckgo', 'results': [], 'pages': []}

    search_results = duckduckgo_search(query, max_results=max_results)
    if not fetch_content or num_pages <= 0:
        return {'query': query, 'provider': 'duckduckgo', 'results': search_results, 'pages': []}

    top_results = search_results[:num_pages]
    pages = [None] * len(top_results)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(download_web_page, item['url'], timeout=timeout): (idx, item)
            for idx, item in enumerate(top_results)
        }

        for future in as_completed(future_to_task):
            idx, item = future_to_task[future]
            try:
                content = (future.result() or '').strip()
                if content:
                    pages[idx] = {
                        'url': item['url'],
                        'title': item['title'],
                        'excerpt': content[:PAGE_EXCERPT_CHARS],
                        'ok': True,
                    }
                else:
                    pages[idx] = {
                        'url': item['url'],
                        'title': item['title'],
                        'error': 'No extractable content',
                        'ok': False,
                    }
            except Exception as exc:
                pages[idx] = {
                    'url': item['url'],
                    'title': item['title'],
                    'error': str(exc),
                    'ok': False,
                }

    return {'query': query, 'provider': 'duckduckgo', 'results': search_results, 'pages': [p for p in pages if p is not None]}


def truncate_content_by_tokens(content, max_tokens=8192):
    """Truncate content to fit within token limit using binary search"""
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
    """Perform web search and add results as attachments"""
    if not search_query:
        logger.warning('No search query provided')
        return

    logger.info(f'Using search query: {search_query}')

    try:
        num_pages = max(0, int(state.get('web_search_pages', 3)))
        search_data = perform_web_search(
            search_query,
            num_pages=num_pages,
            timeout=PAGE_FETCH_TIMEOUT,
            fetch_content=num_pages > 0,
            max_results=SEARCH_MAX_RESULTS_DEFAULT,
        )
    except Exception as exc:
        logger.exception(f'web_search backend failed for query: {search_query}')
        key = f'user_{row_idx}'
        history.setdefault('metadata', {})
        if key not in history['metadata']:
            history['metadata'][key] = {'timestamp': get_current_timestamp()}
        history['metadata'][key].setdefault('attachments', []).append({
            'name': 'WEB SEARCH ERROR',
            'type': 'text/plain',
            'url': '',
            'content': (
                f'WEB SEARCH ERROR\nQuery: {search_query}\nProvider: DuckDuckGo\n'
                f'Error: DuckDuckGo backend failed: {exc}\n\n'
                'Do not retry automatically with a broader query unless the user asks.'
            ),
        })
        return

    results = search_data['results']
    if not results:
        logger.warning(f'DuckDuckGo returned no results for query: {search_query}')
        return

    lines = [
        'WEB SEARCH RESULTS',
        f'Query: {search_query}',
        'Provider: DuckDuckGo',
        '',
    ]
    for result in results:
        lines.extend([
            f"[{result['rank']}] {result['title'] or '(Untitled)'}",
            f"URL: {result['url']}",
            f"Snippet: {result['snippet']}",
            '',
        ])

    pages = search_data['pages']
    if pages:
        lines.extend(['FETCHED PAGE EXCERPTS', ''])
        for idx, page in enumerate(pages, start=1):
            lines.append(f"[{idx}] {page.get('title') or '(Untitled)'}")
            lines.append(f"URL: {page.get('url', '')}")
            if page.get('ok'):
                lines.append('Excerpt:')
                lines.append(page.get('excerpt', ''))
            else:
                lines.append(f"Error: {page.get('error', 'unknown error')}")
            lines.append('')

    key = f'user_{row_idx}'
    history.setdefault('metadata', {})
    if key not in history['metadata']:
        history['metadata'][key] = {'timestamp': get_current_timestamp()}
    history['metadata'][key].setdefault('attachments', []).append({
        'name': f'web_search_{search_query[:60]}',
        'type': 'text/plain',
        'url': '',
        'content': truncate_content_by_tokens('\n'.join(lines)),
    })

    for page in pages:
        if page.get('ok'):
            history['metadata'][key]['attachments'].append({
                'name': page.get('title') or page.get('url'),
                'type': 'text/html',
                'url': page.get('url', ''),
                'content': truncate_content_by_tokens(page.get('excerpt', '')),
            })

    logger.info(f"Added web search summary with {len(results)} results and {len(pages)} fetched pages.")
