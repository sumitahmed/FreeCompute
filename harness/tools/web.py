"""
harness/tools/web.py — Real-time Web Search and URL Fetching Tools.
Provides DuckDuckGo web search and lightweight HTML page extraction without external API keys.
"""

import html
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Search the web using DuckDuckGo HTML search.
    Returns titles, snippets, and target URLs.
    """
    clean_query = query.strip()
    if not clean_query:
        return {"error": "Query cannot be empty.", "results": []}

    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(clean_query)}"
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return {"query": clean_query, "error": f"Search request failed: {exc}", "results": []}

    # Match search result blocks: link + snippet
    # DuckDuckGo HTML structure: <a class="result__snippet" ...>...</a> and <a class="result__url" ...>...</a>
    results: List[Dict[str, str]] = []

    # Extract snippets
    snippets = re.findall(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', raw_html, re.DOTALL)
    # Extract titles and links
    titles_links = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw_html, re.DOTALL
    )

    for i in range(min(len(snippets), len(titles_links), max_results)):
        link, title_raw = titles_links[i]
        snippet_raw = snippets[i]

        title = re.sub(r"<[^>]+>", "", title_raw).strip()
        title = html.unescape(title)

        snippet = re.sub(r"<[^>]+>", "", snippet_raw).strip()
        snippet = html.unescape(snippet)

        # Unquote DuckDuckGo redirect link /l/?kh=-1&uddg=...
        actual_url = link
        if "uddg=" in link:
            match = re.search(r"uddg=([^&]+)", link)
            if match:
                actual_url = urllib.parse.unquote(match.group(1))

        results.append({
            "title": title,
            "snippet": snippet,
            "url": actual_url,
        })

    return {
        "query": clean_query,
        "count": len(results),
        "results": results,
    }


def fetch_url(url: str, max_chars: int = 5000) -> Dict[str, Any]:
    """
    Fetch a web page and extract clean readable text.
    Strips scripts, styling, navigation, and excessive markup.
    """
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    req = urllib.request.Request(clean_url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return {
                    "url": clean_url,
                    "error": f"Unsupported Content-Type: {content_type}. Only text/html is supported.",
                }
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return {"url": clean_url, "error": f"Failed to fetch page: {exc}"}

    # Strip script and style blocks
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<nav[\s\S]*?</nav>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<header[\s\S]*?</header>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<footer[\s\S]*?</footer>", " ", cleaned, flags=re.IGNORECASE)

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", cleaned)
    text = html.unescape(text)

    # Collapse multiple spaces and newlines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    condensed = "\n".join(lines)

    truncated = condensed[:max_chars]
    return {
        "url": clean_url,
        "chars_extracted": len(condensed),
        "content": truncated,
        "truncated": len(condensed) > max_chars,
    }
