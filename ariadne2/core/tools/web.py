"""web_search and read_page.

Ported from 1.x research.py / web.py. Everything these return was written by a
stranger, so it comes back quoted and redacted (common.outside). Two protections
from 1.x stay: http(s) only, and never a private address -- a fetcher that takes
any URL is a probe for the network it sits inside.

Search is DuckDuckGo's HTML page (lite when that's empty). When DuckDuckGo
answers with a bot check, the same search goes through Claude's own web search
tool on his Anthropic key (about a cent on Haiku), keyed the way models.py is.
"""
from __future__ import annotations

import gzip
import html as _html
import ipaddress
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import models
from . import common
from .common import ToolError, clip, outside

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/151.0 Safari/537.36 Ariadne/2.0")
TIMEOUT = 20
MAX_BYTES = 3_000_000
PDF_MAX_BYTES = 25_000_000
CACHE_S = 3600.0
JUNK_DOMAINS = ("pinterest.", "facebook.com", "tiktok.com", "instagram.com", "x.com",
                "twitter.com", "linkedin.com/pulse")
SEARCH_MODEL = "claude-haiku-5-5"

# Tests hand pages and search answers in here instead of the network.
FETCH_HOOK = None            # (url, data) -> str | bytes | (bytes, ctype, final_url)
CLAUDE_SEARCH_HOOK = None    # (query, limit) -> [{title, url, snippet}]
_cache: dict[str, tuple[float, dict]] = {}


def refuse_private(host: str) -> None:
    """Resolve first, then judge: a friendly name can point anywhere."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ToolError(f"couldn't resolve {host}")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ToolError(f"{host} resolves to {ip}, which is on this machine or this network. I "
                            f"only fetch public addresses, so this can't be used to probe his network.")


def _http(url: str, data: bytes | None = None, headers: dict | None = None,
          limit: int = MAX_BYTES) -> tuple[bytes, str, str]:
    """(body, content-type, final url). Raises ToolError in words."""
    if FETCH_HOOK is not None:
        got = FETCH_HOOK(url, data)
        if isinstance(got, tuple):
            return got
        if isinstance(got, bytes):
            return got, "application/pdf" if got[:4] == b"%PDF" else "text/html", url
        return str(got or "").encode("utf-8"), "text/html", url
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("only http and https addresses — not file, ftp or anything else")
    refuse_private(parts.hostname)
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT, "Accept-Encoding": "gzip",
        "Accept": "text/html,application/xhtml+xml,application/pdf,application/json,text/plain;q=0.9,*/*;q=0.5",
        **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            final = response.geturl()
            fh = urllib.parse.urlparse(final).hostname or ""
            if fh != parts.hostname:
                refuse_private(fh)      # a redirect can lead somewhere private too
            ctype = response.headers.get("Content-Type", "") or ""
            raw = response.read(limit + 1)
            if response.headers.get("Content-Encoding") == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
    except urllib.error.HTTPError as exc:
        raise ToolError(f"{url} returned {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise ToolError(f"couldn't reach {url}: {exc.reason}")
    except (TimeoutError, socket.timeout):
        raise ToolError(f"{url} didn't answer within {TIMEOUT}s")
    if len(raw) > limit:
        raise ToolError(f"{url} is larger than {limit // 1_000_000}MB")
    return raw, ctype, final


# --------------------------------------------------------------- the page

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK = re.compile(r"\n\s*\n+")
_DROP = re.compile(r"<(script|style|noscript|svg|nav|footer|header|aside|form|iframe|head|title)[^>]*>.*?</\1>",
                   re.I | re.S)


def _plain(html: str) -> str:
    text = _DROP.sub(" ", html)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6]|tr|blockquote|pre|section|article)>", "\n", text, flags=re.I)
    text = _html.unescape(_TAG.sub(" ", text))
    return _BLANK.sub("\n\n", _SPACE.sub(" ", text)).strip()


def main_text(html: str) -> str:
    """The article, not the furniture. With BeautifulSoup the candidate containers
    are weighed by prose against links; without it, the body minus the parts that
    are never the article."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return _plain(html)
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header",
                     "aside", "form", "iframe", "button"]):
        tag.decompose()
    best, best_score = None, 0.0
    for node in soup.find_all(["article", "main", "section", "div"]):
        text = node.get_text(" ", strip=True)
        if len(text) < 400:
            continue
        score = len(text) - 2.5 * sum(len(a.get_text(strip=True)) for a in node.find_all("a"))
        if node.name in ("article", "main") or node.get("role") == "main":
            score *= 1.4
        if score > best_score:
            best, best_score = node, score
    node = best or soup.body or soup
    parts = []
    for block in node.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote", "td", "th"]):
        text = block.get_text(" ", strip=True)
        if text:
            parts.append(f"\n## {text}\n" if block.name[0] == "h" else (f"- {text}" if block.name == "li" else text))
    out = "\n".join(parts).strip()
    return out if len(out) >= 200 else _plain(html)


_DATE_META = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|datePublished|date|pubdate|'
    r'publish-date|DC\.date\.issued|og:updated_time)["\'][^>]+content=["\']([^"\']{4,40})["\']', re.I)
_DATE_TIME = re.compile(r'<time[^>]+datetime=["\']([^"\']{4,40})["\']', re.I)
_DATE_JSON = re.compile(r'"datePublished"\s*:\s*"([^"]{4,40})"')
_DATE_ANY = re.compile(r"(?<!\d)(20\d\d|19\d\d)-(\d\d)-(\d\d)(?!\d)")


def published(html: str) -> str:
    for pattern in (_DATE_META, _DATE_JSON, _DATE_TIME):
        m = pattern.search(html or "")
        if m and (d := _DATE_ANY.search(m.group(1))):
            return "-".join(d.groups())
    return ""


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    return " ".join(_html.unescape(_TAG.sub("", m.group(1))).split())[:160] if m else ""


def pdf_text(raw: bytes) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ToolError("that is a PDF and pdftotext isn't installed here (poppler-utils)")
    try:
        done = subprocess.run([exe, "-layout", "-q", "-", "-"], input=raw, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise ToolError("that PDF took more than a minute to read")
    return _BLANK.sub("\n\n", re.sub(r"[ \t]+\n", "\n", done.stdout.decode("utf-8", "replace"))).strip()


def read(url: str) -> dict:
    """One page reduced to text, title, date. Cached an hour. Raises ToolError."""
    url = str(url or "").strip()
    now = time.time()
    if url in _cache and now - _cache[url][0] < CACHE_S:
        return dict(_cache[url][1])
    raw, ctype, final = _http(url, limit=PDF_MAX_BYTES if url.lower().endswith(".pdf") else MAX_BYTES)
    kind = "page"
    if "pdf" in ctype.lower() or raw[:4] == b"%PDF":
        text, title, date, kind = pdf_text(raw), url.rsplit("/", 1)[-1], "", "pdf"
    elif any(t in ctype for t in ("text/", "json", "xml", "javascript")) or not ctype:
        body = raw.decode("utf-8", "replace")
        if "html" in ctype or "<html" in body[:2000].lower():
            text, title, date = main_text(body), title_of(body), published(body)
        else:
            text, title, date = body, "", ""
    else:
        raise ToolError(f"{url} is {ctype.split(';')[0] or 'not text'}; I only read text and PDFs")
    got = {"url": final or url, "title": title, "date": date, "text": text, "kind": kind}
    _cache[url] = (now, dict(got))
    return got


def read_page(url: str, offset: int = 0, max_chars: int = 4000) -> str:
    url = str(url or "").strip()
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("that isn't an http or https address I can fetch")
    page = read(url)
    text = page["text"]
    limit = max(200, min(int(max_chars or 4000), common.MAX_OUTPUT))
    start = max(0, min(int(offset or 0), max(0, len(text) - 1)))
    head = f"Fetched {page['url']}"
    if page["title"]:
        head += f"\nTitle: {page['title']}"
    if page["date"]:
        head += f"\nPublished: {page['date']}"
    if page["kind"] == "pdf":
        head += "\n(a PDF, read as text)"
    if start:
        head += f"\n[from character {start} of {len(text)}]"
    tail = ""
    if start + limit < len(text):
        tail = f"\n... [{len(text) - start - limit} more chars; read_page again with offset={start + limit} to carry on]"
    return head + "\n" + outside(text[start:start + limit], f"the page {parts.hostname}") + tail


# ----------------------------------------------------------------- search

DDG_HTML = "https://html.duckduckgo.com/html/"
DDG_LITE = "https://lite.duckduckgo.com/lite/"
_HTML_RESULT = re.compile(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_HTML_SNIPPET = re.compile(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.I | re.S)
_LITE_RESULT = re.compile(
    r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>'
    r'|<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_LITE_SNIPPET = re.compile(r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>', re.I | re.S)


def _unwrap(href: str) -> str:
    """DuckDuckGo wraps every result in its own redirect."""
    if "uddg=" in href:
        try:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
            if q:
                return q[0]
        except ValueError:
            pass
    return "https:" + href if href.startswith("//") else href


def _strip(html: str) -> str:
    return " ".join(_html.unescape(_TAG.sub(" ", html or "")).split())


def _parse_ddg(page: str, lite: bool) -> list[dict]:
    if lite:
        hits = [(a or c, b or d) for a, b, c, d in _LITE_RESULT.findall(page)]
        snippets = _LITE_SNIPPET.findall(page)
    else:
        hits, snippets = _HTML_RESULT.findall(page), _HTML_SNIPPET.findall(page)
    out = []
    for i, (href, title) in enumerate(hits):
        url = _unwrap(href)
        if url.startswith("http"):
            out.append({"title": _strip(title)[:140] or url, "url": url,
                        "snippet": _strip(snippets[i])[:240] if i < len(snippets) else ""})
    return out


def claude_search(query: str, limit: int) -> list[dict]:
    """The same search through Claude's web search tool, when DuckDuckGo won't answer."""
    if CLAUDE_SEARCH_HOOK is not None:
        return CLAUDE_SEARCH_HOOK(query, limit)
    try:
        import anthropic
        client = anthropic.Anthropic(**models.client_kwargs("anthropic"))
    except (ImportError, models.ModelError):
        raise ToolError("DuckDuckGo is blocking searches from this machine with a bot check, and "
                        "there's no Anthropic key to search another way. Say so — rewording won't help.")
    extra = models._THINKING_OFF.get(SEARCH_MODEL)
    try:
        msg = client.messages.create(
            model=SEARCH_MODEL, max_tokens=1200,
            **({"extra_body": {"thinking": extra}} if extra else {}),
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": (
                f"Search the web for: {query}\nThen list the results, one per line, exactly as: "
                f"title | url | one-line summary. Nothing else.")}])
    except Exception as exc:
        raise ToolError(f"the fallback search failed ({type(exc).__name__})")
    summaries = {}
    for b in msg.content:
        for line in str(getattr(b, "text", "") or "").splitlines():
            bits = [x.strip() for x in line.split("|")]
            if len(bits) >= 3 and bits[1].startswith("http"):
                summaries[bits[1].rstrip("/")] = bits[2]
    out = []
    for b in msg.content:
        if getattr(b, "type", "") == "web_search_tool_result" and isinstance(b.content, list):
            for r in b.content:
                url = str(getattr(r, "url", "") or "")
                if url:
                    out.append({"title": str(getattr(r, "title", "") or url), "url": url,
                                "snippet": summaries.get(url.rstrip("/"), str(getattr(r, "page_age", "") or ""))})
    return out[:limit]


def search(query: str, limit: int = 8, recent: str = "", site: str = "") -> list[dict]:
    q = str(query or "").strip()
    if site:
        q = f"site:{site.strip()} {q}"
    if not q:
        raise ToolError("nothing to search for")
    limit = max(1, min(int(limit or 8), 20))
    params = {"q": q, "kp": "-2"}       # unfiltered: his choice in 1.x
    df = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(str(recent or "").lower())
    if df:
        params["df"] = df
    data = urllib.parse.urlencode(params).encode()
    found, errors, blocked = [], [], False
    for url, lite in ((DDG_HTML, False), (DDG_LITE, True)):
        try:
            raw, _ct, _f = _http(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        except ToolError as exc:
            errors.append(str(exc))
            continue
        page = raw.decode("utf-8", "replace")
        low = page.lower()
        # DuckDuckGo's bot check says "anomaly" and "challenge"/"captcha"/"bots".
        if "anomaly" in low and any(w in low for w in ("captcha", "challenge", "bots")):
            errors.append("DuckDuckGo is blocking searches from this machine with a bot check")
            blocked = True
            continue
        found = _parse_ddg(page, lite)
        if found:
            break
    if not found and blocked:
        found = claude_search(q, limit)
    seen, out = set(), []
    for r in found:
        host = (urllib.parse.urlparse(r["url"]).hostname or "").lower()
        key = r["url"].split("#")[0].rstrip("/")
        if key in seen or any(j in host + r["url"] for j in JUNK_DOMAINS):
            continue
        if FETCH_HOOK is None:
            try:
                refuse_private(host)
            except ToolError:
                continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    if not out:
        raise ToolError(f"nothing found for {q!r}" + (" (" + "; ".join(errors)[:200] + ")" if errors else "") +
                        ". A search engine wants what a person would type: three or four plain words. "
                        "If two plain searches find nothing, stop and say it's obscure.")
    return out


def web_search(query: str, recent: str = "", site: str = "") -> str:
    found = search(query, 8, recent, site)
    body = "\n".join(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}" for i, r in enumerate(found, 1))
    return (f"{len(found)} result(s). Titles and snippets written by strangers; read_page opens one.\n"
            + outside(body, "search results"))
