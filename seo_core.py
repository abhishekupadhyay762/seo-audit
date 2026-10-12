"""
SEO Audit Toolkit - engine (no screen code in this file)

Used by both tools:
  page_sitemap.py   Sitemap audit
  page_bulk.py      Bulk URL check

What is in here
  1. Settings you can safely change (limits and thresholds)
  2. Columns and groups
  3. Fetching pages (redirects followed one hop at a time)
  4. Reading a page (title, meta, headings, schema, links ...)
  5. robots.txt rules (Google-style matching)
  6. Issue rules with severity
  7. Sitemap discovery, sitemap reading and the URL inventory
  8. CSV / Excel export
"""

import gzip
import html
import io
import json
import re
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

import pandas as pd
import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree as SafeET
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from requests.adapters import HTTPAdapter

# --------------------------------------------------------------------------
# Settings you can safely change
# --------------------------------------------------------------------------
TITLE_MIN_CHARS = 30       # shorter than this -> "Title too short"
TITLE_MAX_PX = 600         # wider than this (estimated) -> "Title too long"
META_MIN_CHARS = 70        # shorter than this -> "Meta description too short"
META_MAX_CHARS = 160       # longer than this -> "Meta description too long"
THIN_CONTENT_WORDS = 300   # fewer main-content words than this -> "Thin content"
MAX_REDIRECTS = 10         # stop following a redirect chain after this many hops
MAX_HTML_BYTES = 3_000_000 # read at most ~3 MB of HTML per page
MAX_SITEMAP_BYTES = 60_000_000   # a sitemap file may be 50 MB uncompressed by the standard
MAX_SITEMAP_FILES = 1000         # stop after this many sitemap files (safety limit)
MAX_INVENTORY_URLS = 200_000     # stop listing sitemap URLs after this many
SITEMAP_URL_LIMIT = 50_000       # the standard allows 50,000 URLs per sitemap file
SITEMAP_SIZE_LIMIT_MB = 50       # ... and 50 MB per file, uncompressed
ROBOTS_AGENT = "googlebot"       # robots.txt rules are read the way this crawler reads them

USER_AGENTS = {
    "Tool default": "Mozilla/5.0 (compatible; SEOMetaChecker/3.0)",
    "Chrome (desktop)": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Googlebot Smartphone": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "Googlebot Desktop": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html) Chrome/141.0.0.0 Safari/537.36"
    ),
}
BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# --------------------------------------------------------------------------
# Columns, grouped the way the results are shown and exported
# --------------------------------------------------------------------------
GROUPS = {
    "URL & Status": [
        "Status Code", "Redirect Type", "Redirect Hops", "Final URL", "Final Status Code",
        "Redirect Chain", "Response Time (ms)", "Total Time (ms)", "HTML Size (KB)",
        "Content Type", "Fetch Error",
    ],
    "Indexability": [
        "Indexable", "Indexability Reason", "Robots.txt", "Meta Robots", "X-Robots-Tag",
        "Canonical URL", "Canonical Status", "Canonical Count", "Canonical Target Status", "Canonical Target Note",
    ],
    "Title & Meta": [
        "Title", "Title Length", "Title Pixels", "Duplicate Title",
        "Meta Description", "Meta Length", "Duplicate Meta", "Title = H1",
    ],
    "Headings": ["H1", "H1 Count", "All H1s", "H2 Count", "H2 List", "H3 Count", "Heading Structure"],
    "Content": ["Word Count", "Word Count (Full Page)", "Published", "Updated", "JS Rendered"],
    "Images": ["Images", "Alt Missing", "Alt Empty", "No Dimensions"],
    "Schema": ["Schema", "Schema Types", "Schema Formats", "Invalid JSON-LD"],
    "Social & Tags": ["OG Title", "OG Description", "OG Image", "Twitter Card", "Lang", "Viewport"],
    "Hreflang": ["Hreflang Count", "Hreflang Tags", "Hreflang Problems"],
    "Links": ["Internal Links", "External Links", "Nofollow Links", "Empty Anchor Links",
              "Broken Links", "Links To Redirects"],
    "Issues": ["Severity", "Issue Count", "Critical", "Warnings", "Notices"],
}
# Extra group shown first in the Sitemap audit (filled from the sitemap, not from the page)
SITEMAP_GROUP = {
    "Sitemap": ["Section", "Depth", "Sitemap File", "Lastmod", "Times Listed",
                "Images in Sitemap", "Hreflang in Sitemap"],
}
SITEMAP_GROUPS = {**SITEMAP_GROUP, **GROUPS}
# Extra group shown first in the Site crawl
CRAWL_GROUP = {"Crawl": ["Crawl Depth", "Inlinks", "Linked From", "In Sitemap"]}
CRAWL_GROUPS = {**CRAWL_GROUP, **GROUPS}
# Extra group shown first in the Keyword check
KEYWORD_GROUP = {
    "Keyword": ["Target Keyword", "Keyword Score", "In Title", "In H1", "In Meta Description", "In URL",
                "In First 100 Words", "In H2s", "Keyword Count", "Keyword Density (%)"],
}
KEYWORD_GROUPS = {**KEYWORD_GROUP, **GROUPS}


def all_cols(groups: dict) -> list:
    return ["URL"] + [c for cols in groups.values() for c in cols]


ALL_COLS = all_cols(GROUPS)
OVERVIEW_COLS = [
    "URL", "Status Code", "Indexable", "Indexability Reason", "Title", "Title Length",
    "Meta Length", "H1 Count", "Word Count", "Severity", "Issue Count",
]
SITEMAP_OVERVIEW_COLS = [
    "URL", "Section", "Status Code", "Indexable", "Indexability Reason", "Title", "Title Length",
    "Meta Length", "H1 Count", "Severity", "Issue Count",
]
CRAWL_OVERVIEW_COLS = [
    "URL", "Crawl Depth", "Inlinks", "In Sitemap", "Status Code", "Indexable", "Indexability Reason",
    "Title", "Title Length", "H1 Count", "Severity", "Issue Count",
]
KEYWORD_OVERVIEW_COLS = [
    "URL", "Target Keyword", "Keyword Score", "In Title", "In H1", "In Meta Description", "In URL",
    "In First 100 Words", "Keyword Count", "Severity", "Issue Count",
]
INT_COLS = [
    "Status Code", "Redirect Hops", "Final Status Code", "Response Time (ms)", "Total Time (ms)",
    "Canonical Count", "Title Length", "Title Pixels", "Meta Length", "H1 Count", "H2 Count",
    "H3 Count", "Word Count", "Word Count (Full Page)", "Images", "Alt Missing", "Alt Empty",
    "No Dimensions", "Invalid JSON-LD", "Hreflang Count", "Internal Links", "External Links",
    "Nofollow Links", "Empty Anchor Links", "Issue Count",
    "Depth", "Times Listed", "Images in Sitemap", "Hreflang in Sitemap",
    "Canonical Target Status", "Broken Links", "Links To Redirects", "Crawl Depth", "Inlinks", "Keyword Count",
]
FLOAT_COLS = ["HTML Size (KB)", "Keyword Density (%)"]
NUM_COLS = set(INT_COLS) | set(FLOAT_COLS)

CRITICAL, WARNING, NOTICE = "Critical", "Warning", "Notice"
SEV_RANK = {CRITICAL: 0, WARNING: 1, NOTICE: 2, "OK": 3}
SEV_ICON = {CRITICAL: "🔴 Critical", WARNING: "🟠 Warning", NOTICE: "🔵 Notice", "OK": "✅ OK"}
SEV_FILL = {CRITICAL: "F8CBAD", WARNING: "FFE699", NOTICE: "DDEBF7", "OK": "E2EFDA"}

REDIRECT_CODES = {301, 302, 303, 307, 308}
REDIRECT_LABEL = {
    301: "301 Permanent", 302: "302 Temporary", 303: "303 See Other",
    307: "307 Temporary", 308: "308 Permanent",
}

# Character widths (per 1000 units, Arial metrics) used to estimate the title width in Google
_WIDTHS = {
    191: "'", 222: "ijl’‘", 260: "|", 278: " !,./:;I[\\]ft·", 333: "()-`r“”", 334: "{}", 355: '"',
    389: "*", 469: "^", 500: "Jcksvxyz", 556: "#$0123456789?L_abdeghnopqu–€£₹«»", 584: "+<=>~",
    611: "FTZ", 667: "&ABEKPSVXY", 722: "CDHNRUw", 737: "©®", 778: "GOQ", 833: "Mm", 889: "%",
    944: "W", 1000: "—…™", 1015: "@",
}
CHAR_W = {ch: w for w, chars in _WIDTHS.items() for ch in chars}


def pixel_width(text: str, font_px: int = 20) -> int:
    """Estimated rendered width of a title in Google's desktop results (Arial, 20px)."""
    units = 0
    for ch in text:
        w = CHAR_W.get(ch)
        if w is None:
            w = 1000 if ord(ch) > 0x2E7F else 556  # CJK = full width, anything else = average
        units += w
    return round(units * font_px / 1000)


# --------------------------------------------------------------------------
# Input handling
# --------------------------------------------------------------------------
def looks_like_url(s: str) -> bool:
    s = s.strip()
    return bool(s) and " " not in s and "." in s


def normalize_url(raw: str) -> str:
    u = raw.strip().strip('"\'')
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    try:
        return u if urlsplit(u).netloc else ""
    except ValueError:
        return ""


def parse_uploaded(file) -> list:
    """First column of a CSV / XLSX, or one URL per line for TXT."""
    name = file.name.lower()
    raw = file.getvalue()
    if name.endswith(".txt"):
        vals = raw.decode("utf-8-sig", "replace").splitlines()
    elif name.endswith((".xlsx", ".xls")):
        vals = pd.read_excel(io.BytesIO(raw), header=None).iloc[:, 0].dropna().astype(str).tolist()
    else:
        vals = (
            pd.read_csv(io.BytesIO(raw), header=None, encoding="utf-8-sig", usecols=[0])
            .iloc[:, 0].dropna().astype(str).tolist()
        )
    return [v.strip() for v in vals if looks_like_url(v)]


def collect_inputs(text: str, file) -> list:
    items = [l.strip() for l in text.splitlines() if l.strip()]
    if file is not None:
        items += parse_uploaded(file)
    seen, out = set(), []
    for it in items:
        u = normalize_url(it)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# --------------------------------------------------------------------------
# Fetching - redirects are followed one hop at a time so every hop is recorded
# --------------------------------------------------------------------------
def make_session(pool_size: int, user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    s.headers["User-Agent"] = user_agent
    ad = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    s.mount("http://", ad)
    s.mount("https://", ad)
    return s


def error_label(e: Exception) -> str:
    if isinstance(e, requests.exceptions.SSLError):
        return "SSL certificate error"
    if isinstance(e, requests.exceptions.Timeout):
        return "Timeout"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "Connection failed"
    if isinstance(e, (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
                      requests.exceptions.InvalidSchema)):
        return "Invalid URL"
    return e.__class__.__name__


def get_once(session, url, timeout, retries=2):
    """One request, no redirect following. Returns (response, error_text)."""
    err = ""
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=timeout, stream=True, allow_redirects=False)
        except requests.RequestException as e:
            err = error_label(e)
            if err == "Invalid URL" or (err == "Timeout" and attempt >= 1):
                break  # a second timeout is enough - do not wait a third time
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
            continue
        except Exception as e:  # malformed URLs can raise outside requests' own errors
            return None, f"Invalid URL ({e.__class__.__name__})"
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            r.close()
            time.sleep(1.5 * (attempt + 1))
            continue
        return r, ""
    return None, err or "Failed"


def is_html(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return (not ct) or "html" in ct


def fetch_chain(session, url, timeout, read_body=True):
    """Requests `url` and follows redirects manually.

    Returns a dict:
      hops        [(url, status), ...] one entry per redirect hop
      final_url   last URL requested
      status      final status code (None if the request failed)
      headers     final response headers
      body        HTML bytes (only read for a 200 HTML response)
      truncated   True when the HTML was larger than MAX_HTML_BYTES
      first_ms    server response time of the first request
      total_ms    whole chain + HTML download
      error       text when the fetch failed
    """
    out = {"hops": [], "final_url": url, "status": None, "headers": {}, "body": b"",
           "truncated": False, "first_ms": None, "total_ms": None, "error": ""}
    started = time.perf_counter()
    current, seen = url, {url}
    for _ in range(MAX_REDIRECTS + 1):
        r, err = get_once(session, current, timeout)
        out["final_url"] = current
        if r is None:
            out["error"] = err
            break
        try:
            if out["first_ms"] is None:
                out["first_ms"] = int(r.elapsed.total_seconds() * 1000)
            status = r.status_code
            location = (r.headers.get("Location") or "").strip()
            if status in REDIRECT_CODES and location:
                out["hops"].append((current, status))
                try:
                    nxt = urljoin(current, location)
                    scheme = urlsplit(nxt).scheme.lower()
                except ValueError:
                    out["error"] = "Redirects to an invalid URL"
                    break
                if scheme not in ("http", "https"):
                    out["final_url"] = nxt
                    out["error"] = "Redirects to a non-web URL"
                    break
                if nxt in seen:
                    out["final_url"] = nxt
                    out["error"] = "Redirect loop"
                    break
                seen.add(nxt)
                current = nxt
                continue
            # final response
            out["status"] = status
            out["headers"] = r.headers
            if read_body and status == 200 and is_html(r.headers.get("Content-Type", "")):
                chunks, size = [], 0
                deadline = time.perf_counter() + max(timeout * 2, 20)
                try:
                    for chunk in r.iter_content(65536):
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= MAX_HTML_BYTES or time.perf_counter() > deadline:
                            out["truncated"] = True
                            break
                except requests.RequestException as e:
                    if not chunks:
                        out["status"] = None
                        out["error"] = error_label(e)
                    else:
                        out["truncated"] = True
                out["body"] = b"".join(chunks)
            break
        finally:
            r.close()
    else:
        out["error"] = f"Too many redirects (more than {MAX_REDIRECTS})"
    out["total_ms"] = int((time.perf_counter() - started) * 1000)
    return out


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(t) -> str:
    return re.sub(r"\s+", " ", _CTRL.sub(" ", t or "")).strip()


def uniq(seq) -> list:
    return list(dict.fromkeys(seq))


def norm_url(u: str) -> str:
    """Normalised form used only to compare two URLs (case of host, default port, fragment)."""
    try:
        p = urlsplit(u.strip())
        host = (p.hostname or "").lower()
        port = p.port
    except ValueError:
        return u.strip()
    if port and not ((p.scheme == "http" and port == 80) or (p.scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return urlunsplit((p.scheme.lower(), host, p.path or "/", p.query, ""))


def host_key(u: str) -> str:
    """The site a URL belongs to: host name without www., plus the port when it is not the usual one."""
    try:
        p = urlsplit(u)
        h = (p.hostname or "").lower()
        port = p.port
    except ValueError:
        return ""
    h = h[4:] if h.startswith("www.") else h
    if port and not ((p.scheme.lower() == "http" and port == 80) or (p.scheme.lower() == "https" and port == 443)):
        h = f"{h}:{port}"
    return h


def meta_map(soup) -> dict:
    """{'description': [...], 'og:title': [...], 'robots': [...]} for every <meta> tag."""
    out = {}
    for m in soup.find_all("meta"):
        key = m.get("name") or m.get("property") or m.get("http-equiv")
        content = m.get("content")
        if key and content is not None:
            out.setdefault(key.strip().lower(), []).append(clean(content))
    return out


def first(values) -> str:
    for v in values or []:
        if v:
            return v
    return ""


_VALUE_DIRECTIVES = ("max-snippet", "max-image-preview", "max-video-preview", "unavailable_after")


def has_noindex(value: str) -> bool:
    """True for 'noindex' or 'none'. Handles 'googlebot: noindex' and ignores 'max-image-preview:none'."""
    for token in (value or "").lower().split(","):
        token = token.strip()
        if ":" in token:
            name, rest = token.split(":", 1)
            if name.strip() in _VALUE_DIRECTIVES:
                continue
            token = rest.strip()  # "googlebot: noindex" -> "noindex"
        if token in ("noindex", "none"):
            return True
    return False


def fmt_date(s: str) -> str:
    if not s:
        return ""
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return s.strip()[:10]


def jsonld_scripts(soup) -> list:
    return [
        (s.string or s.get_text() or "").strip()
        for s in soup.find_all("script", attrs={"type": re.compile(r"^\s*application/ld\+json\s*$", re.I)})
    ]


def jsonld_date(texts, key: str) -> str:
    for txt in texts:
        m = re.search(r'"%s"\s*:\s*"([^"]+)"' % key, txt)
        if m:
            return m.group(1)
    return ""


def _walk_types(node, out, depth=0):
    if depth > 12:
        return
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend(x for x in t if isinstance(x, str))
        for v in node.values():
            _walk_types(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_types(v, out, depth + 1)


def _short_type(t: str) -> str:
    t = t.strip().rstrip("/")
    t = t.rsplit("/", 1)[-1]
    return t.split(":", 1)[-1] if t.lower().startswith("schema:") else t


def schema_info(soup, texts):
    """Returns (types, formats, invalid_jsonld_count)."""
    types, formats, invalid = [], [], 0
    blocks = [t for t in texts if t]
    for txt in blocks:
        txt = re.sub(r"^\s*(<!--|//\s*<!\[CDATA\[|<!\[CDATA\[)", "", txt)
        txt = re.sub(r"(-->|//\s*\]\]>|\]\]>)\s*$", "", txt).strip()
        try:
            _walk_types(json.loads(txt, strict=False), types)
        except ValueError:
            invalid += 1
            types += re.findall(r'"@type"\s*:\s*"([^"]+)"', txt)
    if blocks:
        formats.append("JSON-LD")
    micro = soup.find_all(attrs={"itemtype": True})
    for el in micro:
        types += str(el.get("itemtype")).split()
    if micro:
        formats.append("Microdata")
    rdfa = [el for el in soup.find_all(attrs={"typeof": True}) if str(el.get("typeof")).strip()]
    for el in rdfa:
        types += str(el.get("typeof")).split()
    if rdfa:
        formats.append("RDFa")
    return uniq(_short_type(t) for t in types if t.strip()), formats, invalid


def canonical_info(soup, headers, final_url, base_url):
    """Returns (canonical_url, status, count, is_relative)."""
    raw = []
    for l in soup.find_all("link"):
        rel = l.get("rel") or []
        rel = [rel] if isinstance(rel, str) else rel
        if "canonical" in [x.lower() for x in rel] and (l.get("href") or "").strip():
            raw.append(l.get("href").strip())
    for m in re.finditer(r"<([^>]+)>\s*;[^,]*rel\s*=\s*\"?canonical\"?", headers.get("Link", "") or "", re.I):
        raw.append(m.group(1).strip())
    if not raw:
        return "", "Missing", 0, False
    resolved = []
    for h in raw:
        try:
            resolved.append(urljoin(base_url, h))
        except ValueError:
            resolved.append(h)
    relative = not re.match(r"^https?://", raw[0], re.I)
    distinct = uniq(norm_url(u) for u in resolved)
    if len(distinct) > 1:
        status = "Multiple (conflicting)"
    elif distinct[0] == norm_url(final_url):
        status = "Self"
    else:
        status = "Different"
    return resolved[0], status, len(raw), relative


def heading_structure(levels) -> str:
    if not levels:
        return "No headings"
    notes = []
    if levels[0] != 1:
        notes.append(f"First heading is H{levels[0]}")
    for prev, cur in zip(levels, levels[1:]):
        if cur - prev > 1:
            notes.append(f"Skipped level (H{prev} → H{cur})")
            break
    return "; ".join(notes) or "OK"


def node_text(el) -> str:
    """Visible text of a heading/link; falls back to the alt text of an image inside it."""
    t = clean(el.get_text(" "))
    if t:
        return t
    img = el.find("img", alt=True)
    return clean(img.get("alt")) if img else ""


def link_counts(soup, base_url, final_url, collect=False):
    """Counts the links on a page. With collect=True also returns [(url, anchor text, is_nofollow), ...]."""
    internal = external = nofollow = empty = 0
    links = []
    page_host = host_key(final_url)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        try:
            p = urlsplit(urljoin(base_url, href))
        except ValueError:
            continue
        if p.scheme.lower() not in ("http", "https"):
            continue  # mailto:, tel:, javascript: ...
        if host_key(p.geturl()) == page_host:
            internal += 1
        else:
            external += 1
        rel = a.get("rel") or []
        rel = rel.split() if isinstance(rel, str) else rel
        is_nofollow = "nofollow" in [x.lower() for x in rel]
        if is_nofollow:
            nofollow += 1
        anchor = node_text(a) or clean(a.get("aria-label")) or clean(a.get("title"))
        if not anchor:
            empty += 1
        if collect:
            links.append((urlunsplit((p.scheme.lower(), p.netloc, p.path or "/", p.query, "")), anchor[:200], is_nofollow))
    return internal, external, nofollow, empty, links


_CHROME_IDS = {"header", "footer", "nav", "navbar", "navigation", "menu", "sidebar",
               "masthead", "colophon", "site-header", "site-footer"}
_CHROME_ROLES = {"banner", "navigation", "contentinfo", "complementary", "search"}


def _words(el) -> int:
    return len(el.get_text(" ").split())


def word_counts(soup):
    """Returns (main_content_words, full_page_words, main_text). Changes the soup - call it last."""
    body = soup.body
    if body is None:
        return 0, 0, ""
    for t in body(["script", "style", "noscript", "template", "svg", "iframe"]):
        t.decompose()
    full = _words(body)
    scope = body.find("main") or body.find(attrs={"role": "main"})
    if scope is None:
        articles = body.find_all("article")
        scope = articles[0] if len(articles) == 1 else None
    if scope is not None and _words(scope) < 30 and full > 200:
        scope = None  # an empty/misused <main>: fall back to the whole body
    if scope is None:
        scope = body
    # Remove site chrome (menus, header, footer, sidebars) so only the page content is counted.
    # A tag nested inside one that was already removed is skipped (el.decomposed).
    for el in scope.find_all(["nav", "aside"]):
        if not el.decomposed:
            el.decompose()
    for el in scope.find_all(["header", "footer"]):
        # only the site header/footer - an article's own <header> holds its H1 and intro
        if not el.decomposed and el.find_parent(["article", "section", "main"]) is None:
            el.decompose()
    for el in scope.find_all(attrs={"role": True}):
        if not el.decomposed and str(el.get("role")).lower() in _CHROME_ROLES:
            el.decompose()
    for el in scope.find_all(id=True):
        if not el.decomposed and str(el.get("id")).lower() in _CHROME_IDS:
            el.decompose()
    text = clean(scope.get_text(" "))
    return len(text.split()), full, text


def js_shell_markers(soup) -> bool:
    """True when the HTML looks like an empty shell that JavaScript fills in later."""
    if soup.find(id=re.compile(r"^(root|app|__next|__nuxt|___gatsby|svelte)$")):
        return True
    if soup.find("app-root") or soup.find(attrs={"ng-version": True}) or soup.find(attrs={"data-reactroot": True}):
        return True
    for ns in soup.find_all("noscript"):
        if "javascript" in ns.get_text(" ").lower():
            return True
    return len(soup.find_all("script", src=True)) >= 5


# --------------------------------------------------------------------------
# One URL -> one row
# --------------------------------------------------------------------------
def blank_row(url: str) -> dict:
    row = {c: (None if c in NUM_COLS else "") for c in ALL_COLS}
    row["URL"] = url
    row["_x"] = {}  # internal flags for the issue engine (not shown / exported)
    return row


def extract(body: bytes, headers, final_url: str, row: dict, opts: dict = None):
    """Reads one HTML page into `row`.

    opts  {"links": True} keeps every link (for the crawl and the link check),
          {"text": True} keeps the main text and H2s (for the keyword check)
    """
    opts = opts or {}
    x = row["_x"]
    charset = None
    m = re.search(r"charset=([\w\-]+)", headers.get("Content-Type", "") or "", re.I)
    if m:
        charset = m.group(1)
    soup = BeautifulSoup(body, "lxml", from_encoding=charset)
    metas = meta_map(soup)

    base_tag = soup.find("base", href=True)
    try:
        base_url = urljoin(final_url, base_tag["href"].strip()) if base_tag else final_url
    except ValueError:
        base_url = final_url

    # --- Title & meta
    scope = soup.head if soup.head else soup
    titles = [clean(t.get_text()) for t in scope.find_all("title") if not t.find_parent("svg")]
    if not titles:
        titles = [clean(t.get_text()) for t in soup.find_all("title") if not t.find_parent("svg")]
    title = first(titles)
    descs = metas.get("description", [])
    desc = first(descs)
    x["multi_title"] = len(titles) > 1
    x["multi_meta"] = len(descs) > 1

    # --- Indexability
    robots = ", ".join(v for v in metas.get("robots", []) if v)
    googlebot = ", ".join(v for v in metas.get("googlebot", []) if v)
    meta_robots = robots + (f" | googlebot: {googlebot}" if googlebot else "")
    x_robots = clean(headers.get("X-Robots-Tag", ""))
    x["noindex_meta"] = has_noindex(robots) or has_noindex(googlebot)
    x["nofollow_meta"] = bool(re.search(r"\b(nofollow|none)\b", f"{robots}, {googlebot}".lower()))
    x["noindex_header"] = has_noindex(x_robots)
    canonical, can_status, can_count, can_relative = canonical_info(soup, headers, final_url, base_url)
    x["relative_canonical"] = can_relative
    x["meta_refresh"] = any("url=" in v.lower() for v in metas.get("refresh", []))

    # --- Headings
    heads = soup.find_all(re.compile(r"^h[1-6]$"))
    levels = [int(h.name[1]) for h in heads]
    h1s = [node_text(h) for h in heads if h.name == "h1"]
    h2s = [t for t in (node_text(h) for h in heads if h.name == "h2") if t]
    h1_text = first(h1s)

    # --- Images (fallback copies inside <noscript> are ignored)
    imgs = [i for i in soup.find_all("img") if i.find_parent("noscript") is None]
    alt_missing = sum(1 for i in imgs if i.get("alt") is None)
    alt_empty = sum(1 for i in imgs if i.get("alt") is not None and not i.get("alt").strip())
    no_dims = sum(1 for i in imgs if not (i.get("width") and i.get("height")))

    # --- Schema & dates
    ld_texts = jsonld_scripts(soup)
    types, formats, invalid = schema_info(soup, ld_texts)
    pub = first(metas.get("article:published_time")) or jsonld_date(ld_texts, "datePublished")
    mod = first(metas.get("article:modified_time")) or jsonld_date(ld_texts, "dateModified")

    # --- Social & tags
    html_tag = soup.find("html")
    lang = clean((html_tag.get("lang") or html_tag.get("xml:lang") or "") if html_tag else "")
    alternates = []  # [(hreflang code, absolute URL)] from <link> tags and the HTTP Link header
    for l in soup.find_all("link", hreflang=True):
        rel = l.get("rel") or []
        rel = [rel] if isinstance(rel, str) else rel
        if "alternate" in [r.lower() for r in rel] and (l.get("href") or "").strip():
            try:
                alternates.append((l.get("hreflang").strip(), urljoin(base_url, l.get("href").strip())))
            except ValueError:
                continue
    for m in re.finditer(r'<([^>]+)>\s*;([^,]*hreflang\s*=\s*"?([\w-]+)"?[^,]*)', headers.get("Link", "") or "", re.I):
        if "alternate" in m.group(2).lower():
            alternates.append((m.group(3), urljoin(final_url, m.group(1).strip())))
    x["hreflang"] = alternates

    # --- Links
    internal, external, nofollow, empty_anchor, links = link_counts(soup, base_url, final_url, bool(opts.get("links")))
    if opts.get("links"):
        x["links"] = links

    # --- Opening text for the keyword check: the first paragraphs of the main content, without headings
    if opts.get("text"):
        area = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup.body or soup
        paras = " ".join(t for t in (clean(p.get_text(" ")) for p in area.find_all("p")) if t)
        x["intro_text"] = " ".join(paras.split()[:100])

    # --- Content (last: this step removes tags from the parsed page)
    shell = js_shell_markers(soup)
    words_main, words_full, main_text = word_counts(soup)
    js_rendered = "Likely" if (words_full < 60 and shell) else "No"
    if opts.get("text"):
        x["main_text"] = main_text
        x["h2s"] = h2s

    row.update({
        "Meta Robots": meta_robots, "X-Robots-Tag": x_robots,
        "Canonical URL": canonical, "Canonical Status": can_status, "Canonical Count": can_count,
        "Title": title, "Title Length": len(title), "Title Pixels": pixel_width(title),
        "Meta Description": desc, "Meta Length": len(desc),
        "Title = H1": ("Yes" if title.lower() == h1_text.lower() else "No") if (title and h1_text) else "",
        "H1": h1_text, "H1 Count": len(h1s), "All H1s": " || ".join(t for t in h1s if t) if len(h1s) > 1 else "",
        "H2 Count": len(h2s), "H2 List": " || ".join(h2s), "H3 Count": levels.count(3),
        "Heading Structure": heading_structure(levels),
        "Word Count": words_main, "Word Count (Full Page)": words_full,
        "Published": fmt_date(pub), "Updated": fmt_date(mod), "JS Rendered": js_rendered,
        "Images": len(imgs), "Alt Missing": alt_missing, "Alt Empty": alt_empty, "No Dimensions": no_dims,
        "Schema": "Yes" if formats else "No", "Schema Types": ", ".join(types[:30]),
        "Schema Formats": ", ".join(formats), "Invalid JSON-LD": invalid,
        "OG Title": first(metas.get("og:title")), "OG Description": first(metas.get("og:description")),
        "OG Image": first(metas.get("og:image")), "Twitter Card": first(metas.get("twitter:card")),
        "Lang": lang, "Viewport": first(metas.get("viewport")), "Hreflang Count": len(alternates),
        "Hreflang Tags": " | ".join(f"{code}: {href}" for code, href in alternates[:60]),
        "Internal Links": internal, "External Links": external,
        "Nofollow Links": nofollow, "Empty Anchor Links": empty_anchor,
    })
    x["parsed"] = True


def indexability(row: dict):
    """Reads status, robots directives and canonical together. Returns (Yes/No, reason)."""
    x = row["_x"]
    fs = row["Final Status Code"]
    if fs is None:
        if row["Redirect Hops"]:
            return "No", row["Fetch Error"]  # redirect loop, too many redirects ...
        return "No", f"Fetch failed ({row['Fetch Error']})"
    if row["Redirect Hops"]:
        first_code = row["Status Code"]
        if fs >= 400:
            return "No", f"Redirects ({first_code}) to an error page ({fs})"
        return "No", f"Redirected ({first_code})"
    if fs >= 500:
        return "No", f"Server error ({fs})"
    if fs >= 400:
        return "No", f"Client error ({fs})"
    if fs != 200:
        return "No", f"Status {fs}"
    if row["Robots.txt"] == "Blocked":
        return "No", "Blocked by robots.txt"
    if x.get("noindex_header"):
        return "No", "Noindex (X-Robots-Tag)"
    if x.get("non_html"):
        return "Yes", "Non-HTML file"
    if x.get("noindex_meta"):
        return "No", "Noindex (meta robots)"
    if row["Canonical Status"] == "Different":
        return "No", "Canonicalised to another URL"
    return "Yes", ""


def audit_url(session, url, timeout, delay, robots=None, opts=None):
    if delay:
        time.sleep(delay)
    row = blank_row(url)
    x = row["_x"]
    if robots is not None:
        try:
            row["Robots.txt"] = robots.verdict(session, url, timeout)
        except Exception:
            row["Robots.txt"] = ""
    try:
        res = fetch_chain(session, url, timeout)
    except Exception as e:  # never let one bad URL stop the whole run
        res = {"hops": [], "final_url": url, "status": None, "headers": {}, "body": b"",
               "truncated": False, "first_ms": None, "total_ms": None,
               "error": f"Unexpected error ({e.__class__.__name__})"}
    hops, fs, headers = res["hops"], res["status"], res["headers"]
    ctype = (headers.get("Content-Type", "") or "").split(";")[0].strip().lower()

    row["Redirect Hops"] = len(hops)
    row["Status Code"] = hops[0][1] if hops else fs
    row["Final URL"] = res["final_url"]
    row["Final Status Code"] = fs
    row["Fetch Error"] = res["error"]
    row["Response Time (ms)"] = res["first_ms"]
    row["Total Time (ms)"] = res["total_ms"]
    row["Content Type"] = ctype
    if hops:
        codes = [c for _, c in hops]
        row["Redirect Type"] = REDIRECT_LABEL.get(codes[0], str(codes[0])) if len(codes) == 1 else " → ".join(map(str, codes))
        end = f"{res['final_url']} ({fs if fs is not None else res['error']})"
        row["Redirect Chain"] = " → ".join([f"{u} ({c})" for u, c in hops] + [end])
    x["hop_codes"] = [c for _, c in hops]
    x["truncated"] = res["truncated"]

    if fs == 200:
        if not is_html(headers.get("Content-Type", "")):
            x["non_html"] = True
            x["noindex_header"] = has_noindex(headers.get("X-Robots-Tag", ""))
            row["X-Robots-Tag"] = clean(headers.get("X-Robots-Tag", ""))
        else:
            row["HTML Size (KB)"] = round(len(res["body"]) / 1024, 1)
            try:
                extract(res["body"], headers, res["final_url"], row, opts)
            except Exception as e:
                row["Fetch Error"] = f"Could not read the HTML ({e.__class__.__name__})"
    row["Indexable"], row["Indexability Reason"] = indexability(row)
    return row


def run_audit(urls, workers, timeout, delay, user_agent, results, on_progress, robots=None, opts=None, session=None):
    """Checks every URL in parallel. `results` ({index: row}) fills as pages finish."""
    session = session or make_session(workers, user_agent)
    if robots is None:
        robots = RobotsCache()
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = {ex.submit(audit_url, session, u, timeout, delay, robots, opts): i for i, u in enumerate(urls)}
        for n, f in enumerate(as_completed(futs), 1):
            results[futs[f]] = f.result()
            if n % 3 == 0 or n == len(urls):
                on_progress(n, len(urls))
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


# --------------------------------------------------------------------------
# Issue engine - every issue has a severity
# --------------------------------------------------------------------------
def row_issues(r: dict, dup_title: bool, dup_meta: bool) -> list:
    """Returns [(severity, issue_name, text_shown_on_the_row), ...]."""
    x = r["_x"]
    out = []

    def add(sev, name, text=None):
        out.append((sev, name, text or name))

    fs, err = r["Final Status Code"], r["Fetch Error"]
    codes = x.get("hop_codes", [])
    if r["Robots.txt"] == "Blocked":
        add(CRITICAL, "Blocked by robots.txt")
    elif r["Robots.txt"].startswith("Unreachable"):
        add(WARNING, "robots.txt could not be read", f"robots.txt could not be read ({r['Robots.txt']})")
    if x.get("not_crawled"):
        return out
    if fs is None:
        if "loop" in err.lower() or "too many redirects" in err.lower():
            add(CRITICAL, "Redirect loop / too many redirects", err)
        elif codes:
            add(CRITICAL, "Redirect to an invalid target", err)
        else:
            add(CRITICAL, "Fetch failed", f"Fetch failed ({err})")
        return out
    if codes:
        if len(codes) >= 2:
            add(WARNING, "Redirect chain (2+ hops)", f"Redirect chain ({len(codes)} hops)")
        if any(c in (302, 303, 307) for c in codes):
            add(WARNING, "Temporary redirect (302/307)")
        elif len(codes) == 1:
            add(WARNING, "URL redirects (301/308)", f"URL redirects ({codes[0]})")
        if fs >= 400:
            add(CRITICAL, "Redirects to an error page", f"Redirects to an error page ({fs})")
            return out
    elif fs >= 500:
        add(CRITICAL, "5xx server error", f"Server error ({fs})")
        return out
    elif fs >= 400:
        add(CRITICAL, "4xx client error", f"Client error ({fs})")
        return out
    if fs != 200:
        add(WARNING, "Unexpected status code", f"Status {fs}")
        return out

    if x.get("noindex_header"):
        add(CRITICAL, "Noindex", "Noindex (X-Robots-Tag)")
    if x.get("non_html"):
        add(NOTICE, "Non-HTML file", f"Non-HTML file ({r['Content Type'] or 'unknown type'})")
        return out
    if not x.get("parsed"):
        add(CRITICAL, "HTML could not be read", err or "HTML could not be read")
        return out

    # Indexability
    if x.get("noindex_meta") and not x.get("noindex_header"):
        add(CRITICAL, "Noindex", "Noindex (meta robots)")
    cs = r["Canonical Status"]
    if cs == "Missing":
        add(WARNING, "Canonical missing")
    elif cs == "Different":
        add(WARNING, "Canonicalised to another URL")
    elif cs.startswith("Multiple"):
        add(WARNING, "Multiple canonical tags (conflicting)")
    if x.get("relative_canonical"):
        add(NOTICE, "Relative canonical URL")
    if r["Final URL"].lower().startswith("http://"):
        add(WARNING, "Not HTTPS")
    if x.get("meta_refresh"):
        add(WARNING, "Meta refresh redirect")

    js = r["JS Rendered"] == "Likely"
    if js:
        add(WARNING, "Possibly JS-rendered (content checks unreliable)")

    # Title & meta
    if not r["Title"]:
        add(CRITICAL, "Title missing")
    else:
        if r["Title Pixels"] > TITLE_MAX_PX:
            add(NOTICE, "Title too long", f"Title too long (~{r['Title Pixels']}px)")
        elif r["Title Length"] < TITLE_MIN_CHARS:
            add(NOTICE, "Title too short", f"Title too short ({r['Title Length']} chars)")
        if dup_title:
            add(WARNING, "Duplicate title")
    if x.get("multi_title"):
        add(WARNING, "Multiple title tags")
    if not r["Meta Description"]:
        add(WARNING, "Meta description missing")
    else:
        if r["Meta Length"] > META_MAX_CHARS:
            add(NOTICE, "Meta description too long", f"Meta description too long ({r['Meta Length']} chars)")
        elif r["Meta Length"] < META_MIN_CHARS:
            add(NOTICE, "Meta description too short", f"Meta description too short ({r['Meta Length']} chars)")
        if dup_meta:
            add(WARNING, "Duplicate meta description")
    if x.get("multi_meta"):
        add(WARNING, "Multiple meta descriptions")

    # Headings & content (skipped when the page is probably built by JavaScript)
    if not js:
        if r["H1 Count"] == 0:
            add(WARNING, "H1 missing")
        elif not r["H1"]:
            add(WARNING, "H1 empty")
        if r["H1 Count"] > 1:
            add(WARNING, "Multiple H1", f"Multiple H1 ({r['H1 Count']})")
        if "Skipped" in r["Heading Structure"]:
            add(NOTICE, "Heading levels skipped", r["Heading Structure"].split("; ")[-1])
        if r["Word Count"] < THIN_CONTENT_WORDS:
            add(NOTICE, f"Thin content (under {THIN_CONTENT_WORDS} words)", f"Thin content ({r['Word Count']} words)")

    # Images
    if r["Alt Missing"]:
        add(WARNING, "Images missing alt attribute", f"Images missing alt ({r['Alt Missing']})")
    if r["No Dimensions"]:
        add(NOTICE, "Images without width/height", f"Images without width/height ({r['No Dimensions']})")

    # Schema, social, links
    if r["Invalid JSON-LD"]:
        add(WARNING, "Invalid JSON-LD schema", f"Invalid JSON-LD ({r['Invalid JSON-LD']} block)")
    if r["Schema"] == "No":
        add(NOTICE, "No schema markup")
    if not r["Viewport"]:
        add(WARNING, "Viewport tag missing")
    if not r["Lang"]:
        add(NOTICE, "Lang attribute missing")
    if not (r["OG Title"] and r["OG Image"]):
        add(NOTICE, "Open Graph tags incomplete")
    if r["Empty Anchor Links"]:
        add(NOTICE, "Links with empty anchor text", f"Links with empty anchor text ({r['Empty Anchor Links']})")
    if x.get("truncated"):
        add(NOTICE, "Very large HTML (only partly read)")
    return out


def finalize(rows: list, groups: dict = None, extra=None) -> pd.DataFrame:
    """Adds batch-wide checks (duplicates) and the issue columns, returns the results table.

    groups  which column groups the table has (default: the Bulk URL check groups)
    extra   optional function(row) -> (dict of extra column values, list of extra issues);
            the Sitemap audit uses it to add what the sitemap says about each URL
    """
    cols = all_cols(groups or GROUPS)
    def page_id(r):
        # URLs that canonicalise to the same page (e.g. ?utm= versions) count as one page
        if r["Canonical Status"] in ("Self", "Different") and r["Canonical URL"]:
            return norm_url(r["Canonical URL"])
        return norm_url(r["Final URL"])

    title_urls, meta_urls = {}, {}
    for r in rows:
        if r["_x"].get("parsed"):
            page = page_id(r)
            if r["Title"]:
                title_urls.setdefault(r["Title"].lower(), set()).add(page)
            if r["Meta Description"]:
                meta_urls.setdefault(r["Meta Description"].lower(), set()).add(page)

    records, names = [], []
    for r in rows:
        dup_t = dup_m = False
        if r["_x"].get("parsed"):
            dup_t = bool(r["Title"]) and len(title_urls[r["Title"].lower()]) > 1
            dup_m = bool(r["Meta Description"]) and len(meta_urls[r["Meta Description"].lower()]) > 1
            r["Duplicate Title"] = ("Yes" if dup_t else "No") if r["Title"] else ""
            r["Duplicate Meta"] = ("Yes" if dup_m else "No") if r["Meta Description"] else ""
        # issues added by later checks (crawl, links, canonical, hreflang) may come without a separate row text
        later = [(i[0], i[1], i[2] if len(i) > 2 else i[1]) for i in r["_x"].get("more_issues", [])]
        issues = row_issues(r, dup_t, dup_m) + later
        more = {}
        if extra is not None:
            more, extra_issues = extra(r)
            issues = issues + list(extra_issues)
        by_sev = {CRITICAL: [], WARNING: [], NOTICE: []}
        for sev, _, text in issues:
            by_sev[sev].append(text)
        r["Critical"] = "; ".join(by_sev[CRITICAL])
        r["Warnings"] = "; ".join(by_sev[WARNING])
        r["Notices"] = "; ".join(by_sev[NOTICE])
        r["Issue Count"] = len(issues)
        r["Severity"] = min((s for s, _, _ in issues), key=SEV_RANK.get, default="OK")
        record = {c: r.get(c, None if c in NUM_COLS else "") for c in cols}
        record.update(more)
        records.append(record)
        names.append([(sev, name) for sev, name, _ in issues])

    df = pd.DataFrame(records, columns=cols)
    for c in cols:
        if c in INT_COLS:
            df[c] = pd.array(df[c].tolist(), dtype="Int64")
        elif c in FLOAT_COLS:
            df[c] = pd.array(df[c].tolist(), dtype="Float64")
    df["_issues"] = names
    return df


def issue_summary(df: pd.DataFrame) -> pd.DataFrame:
    counts = {}
    for row in df["_issues"]:
        for key in set(row):
            counts[key] = counts.get(key, 0) + 1
    data = [
        {"Issue": name, "Severity": sev, "URLs": n, "% of URLs": round(100 * n / max(len(df), 1), 1)}
        for (sev, name), n in counts.items()
    ]
    data.sort(key=lambda d: (SEV_RANK[d["Severity"]], -d["URLs"], d["Issue"]))
    return pd.DataFrame(data, columns=["Issue", "Severity", "URLs", "% of URLs"])


def headline_numbers(df: pd.DataFrame) -> dict:
    return {
        "URLs checked": len(df),
        "Indexable": int((df["Indexable"] == "Yes").sum()),
        "Non-indexable": int((df["Indexable"] == "No").sum()),
        "With critical issues": int((df["Severity"] == CRITICAL).sum()),
        "With warnings": int((df["Severity"] == WARNING).sum()),
    }


def status_split(df: pd.DataFrame) -> dict:
    """How the checked URLs answered on the first request. The parts add up to the total."""
    first_code, hops, final = df["Status Code"], df["Redirect Hops"], df["Final Status Code"]
    no_hop = hops == 0
    parts = {
        "200 OK": int((no_hop & (first_code == 200)).sum()),
        "Redirect": int((hops > 0).sum()),
        "4xx": int((no_hop & (final >= 400) & (final < 500)).sum()),
        "5xx or failed": int((no_hop & (final.isna() | (final >= 500))).sum()),
    }
    parts["Other"] = len(df) - sum(parts.values())
    return parts


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FORMULA_START = ("=", "+", "-", "@")
COL_WIDTHS = {
    "URL": 55, "Final URL": 45, "Redirect Chain": 70, "Redirect Type": 16, "Content Type": 18,
    "Fetch Error": 26, "Indexability Reason": 34, "Meta Robots": 24, "X-Robots-Tag": 22,
    "Canonical URL": 45, "Canonical Status": 20, "Title": 50, "Meta Description": 70, "H1": 45,
    "All H1s": 50, "H2 List": 70, "Heading Structure": 30, "Schema Types": 45, "Schema Formats": 18,
    "OG Title": 45, "OG Description": 60, "OG Image": 45, "Viewport": 34, "Critical": 45,
    "Warnings": 60, "Notices": 60, "Word Count (Full Page)": 20, "Robots.txt": 18,
    "Section": 22, "Sitemap File": 50, "Lastmod": 24, "Found Via": 34, "Problems": 60,
    "Type": 14, "Issues": 60, "Issue": 52, "Applies To": 16, "Images in Sitemap": 18,
    "Hreflang in Sitemap": 20, "Share of URLs (%)": 18,
}


def to_csv_bytes(df: pd.DataFrame, cols: list = None) -> bytes:
    out = df[cols or [c for c in df.columns if not c.startswith("_")]].copy()
    for c in out.columns:
        if c not in NUM_COLS:
            # stop spreadsheet apps from running page text that starts with = + - @ as a formula
            out[c] = out[c].map(lambda v: "'" + v if isinstance(v, str) and v.startswith(_FORMULA_START) else v)
    return out.to_csv(index=False).encode("utf-8-sig")


def _text_cell(ws, value, **style):
    cell = WriteOnlyCell(ws, value=value)
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"  # keep it as text, never as a formula
    for k, v in style.items():
        setattr(cell, k, v)
    return cell


def _plain_rows(df: pd.DataFrame, cols: list) -> list:
    """The table as plain Python values (None for blanks, long text trimmed to Excel's cell limit)."""
    obj = df[cols].astype(object)
    obj = obj.where(obj.notna(), None)
    return [
        [v[:32000] if type(v) is str and len(v) > 32000 else v for v in row]
        for row in obj.values.tolist()
    ]


def _write_table(ws, rows: list, cols: list, source_cols: list):
    """Writes one sheet. `rows` hold values in `source_cols` order; `cols` are the ones to show."""
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", start_color="1F4E78")
    head_align = Alignment(vertical="center", wrap_text=True)
    fills = {sev: PatternFill("solid", start_color=color) for sev, color in SEV_FILL.items()}
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = COL_WIDTHS.get(c, 15)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"
    ws.append([_text_cell(ws, c, font=head_font, fill=head_fill, alignment=head_align) for c in cols])
    idx = [source_cols.index(c) for c in cols]
    sev_pos = cols.index("Severity") if "Severity" in cols else -1
    for row in rows:
        line = [row[i] for i in idx]
        for pos, v in enumerate(line):
            if type(v) is str and v[:1] == "=":
                line[pos] = _text_cell(ws, v)
        if sev_pos >= 0 and line[sev_pos] in fills:
            line[sev_pos] = _text_cell(ws, line[sev_pos], fill=fills[line[sev_pos]])
        ws.append(line)


def _summary_sheet(wb, title: str, info: dict, numbers: dict, summary: pd.DataFrame):
    bold = Font(bold=True)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", start_color="1F4E78")
    ws = wb.create_sheet("Summary")
    ws.column_dimensions["A"].width = 52
    for col in "BCD":
        ws.column_dimensions[col].width = 18
    ws.append([_text_cell(ws, title, font=Font(bold=True, size=14))])
    for k, v in info.items():
        ws.append([_text_cell(ws, k, font=bold), v])
    ws.append([])
    for k, v in numbers.items():
        ws.append([_text_cell(ws, k, font=bold), v])
    ws.append([])
    if summary is not None:
        ws.append([_text_cell(ws, c, font=head_font, fill=head_fill) for c in summary.columns])
        sev_pos = list(summary.columns).index("Severity")
        for values in summary.itertuples(index=False, name=None):
            line = [v.item() if hasattr(v, "item") else v for v in values]
            sev = line[sev_pos]
            line[sev_pos] = _text_cell(ws, sev, fill=PatternFill("solid", start_color=SEV_FILL.get(sev, "FFFFFF")))
            ws.append(line)
        if summary.empty:
            ws.append(["No issues found"])
    return ws


def _plain_sheet(wb, name: str, df: pd.DataFrame):
    """A simple table sheet (used for the sitemap file list, sections and the URL inventory)."""
    cols = [c for c in df.columns if not c.startswith("_")]
    _write_table(wb.create_sheet(name), _plain_rows(df, cols), cols, cols)


def to_excel_bytes(df: pd.DataFrame, summary: pd.DataFrame, info: dict, groups: dict = None,
                   title: str = "Bulk URL SEO Check", extra_sheets: list = None) -> bytes:
    """Summary sheet + one sheet per group + All Data. Plain .xlsx that opens in Excel and Google Sheets.

    extra_sheets  optional [(sheet name, table), ...] placed straight after the Summary sheet
    """
    groups = groups or GROUPS
    cols = all_cols(groups)
    wb = Workbook(write_only=True)
    _summary_sheet(wb, title, info, headline_numbers(df), summary)
    for name, table in extra_sheets or []:
        _plain_sheet(wb, name, table)
    rows = _plain_rows(df, cols)
    for n, (group, group_cols) in enumerate(groups.items(), 1):
        _write_table(wb.create_sheet(f"{n} {group}"), rows, ["URL"] + group_cols, cols)
    _write_table(wb.create_sheet("All Data"), rows, cols, cols)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def inventory_excel_bytes(inv: dict, info: dict) -> bytes:
    """Excel file for the sitemap itself: Summary, Sitemap files, Sections, URL inventory."""
    wb = Workbook(write_only=True)
    _summary_sheet(wb, "Sitemap inventory", info, inventory_numbers(inv), inv["issues"])
    _plain_sheet(wb, "Sitemap files", inv["files"])
    _plain_sheet(wb, "Sections", inv["sections"])
    _plain_sheet(wb, "URL inventory", inv["urls"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Simple downloads (robots.txt, sitemap files, feeds)
# --------------------------------------------------------------------------
def fetch_raw(session, url, timeout, max_bytes=2_000_000, retries=1) -> dict:
    """GET with redirects followed. Returns status, body, ctype, final_url, error, truncated."""
    out = {"status": None, "body": b"", "ctype": "", "final_url": url, "error": "", "truncated": False}
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=timeout, stream=True, allow_redirects=True)
        except requests.RequestException as e:
            out["error"] = error_label(e)
            if attempt < retries and out["error"] != "Invalid URL":
                time.sleep(1.0)
                continue
            return out
        except Exception as e:
            out["error"] = f"Invalid URL ({e.__class__.__name__})"
            return out
        try:
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5)
                continue
            out.update(status=r.status_code, ctype=r.headers.get("Content-Type", ""), final_url=r.url, error="")
            chunks, size = [], 0
            try:
                for chunk in r.iter_content(65536):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= max_bytes:
                        out["truncated"] = True
                        break
            except requests.RequestException as e:
                if not chunks:
                    out["status"], out["error"] = None, error_label(e)
                else:
                    out["truncated"] = True
            out["body"] = b"".join(chunks)
            return out
        finally:
            r.close()
    return out


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme.lower()}://{p.netloc.lower()}"


# --------------------------------------------------------------------------
# robots.txt - read the way Google reads it
# --------------------------------------------------------------------------
class RobotsRules:
    """Longest matching rule wins, Allow wins a tie, * matches anything, $ marks the end of the URL."""

    def __init__(self, text: str):
        self.groups = []     # [(set of user-agent names, [(is_allow, pattern), ...]), ...]
        self.sitemaps = []
        self._compiled = {}
        agents, rules, in_rules = [], [], False
        for line in (text or "").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if in_rules:  # rules were listed, so this line starts a new group
                    self.groups.append((set(agents), rules))
                    agents, rules, in_rules = [], [], False
                agents.append(value.lower())
            elif key in ("allow", "disallow"):
                in_rules = True
                if agents and value:  # an empty Disallow means "nothing is blocked"
                    rules.append((key == "allow", value))
            elif key == "sitemap" and value:
                self.sitemaps.append(value)
        if agents:
            self.groups.append((set(agents), rules))

    def rules_for(self, agent: str) -> list:
        own = [rules for agents, rules in self.groups if agent in agents]
        chosen = own if own else [rules for agents, rules in self.groups if "*" in agents]
        return [rule for rules in chosen for rule in rules]

    def _regex(self, pattern: str):
        rx = self._compiled.get(pattern)
        if rx is None:
            anchored = pattern.endswith("$")
            core = pattern[:-1] if anchored else pattern
            rx = re.compile(".*".join(re.escape(part) for part in core.split("*")) + ("$" if anchored else ""))
            self._compiled[pattern] = rx
        return rx

    def allowed(self, url: str, agent: str = ROBOTS_AGENT) -> bool:
        try:
            p = urlsplit(url)
        except ValueError:
            return True
        target = (p.path or "/") + (f"?{p.query}" if p.query else "")
        if target == "/robots.txt":
            return True
        best = None  # (pattern length, is_allow): the longest rule wins and Allow wins a tie
        for is_allow, pattern in self.rules_for(agent):
            if self._regex(pattern).match(target):
                key = (len(pattern), is_allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


class RobotsCache:
    """Downloads each site's robots.txt once and answers Allowed / Blocked for any of its URLs."""

    def __init__(self, agent: str = ROBOTS_AGENT):
        self.agent = agent
        self._data = {}     # origin -> (kind, rules, label)
        self._locks = {}
        self._guard = threading.Lock()

    def store(self, origin: str, status, text: str = "", error: str = ""):
        if status == 200:
            self._data[origin] = ("ok", RobotsRules(text), "")
        elif status is None or status == 429 or status >= 500:
            self._data[origin] = ("unreachable", None, f"Unreachable ({status or error or 'no answer'})")
        else:
            self._data[origin] = ("none", None, "")  # 4xx: Google treats it as "no restrictions"

    def rules(self, origin: str):
        entry = self._data.get(origin)
        return entry[1] if entry else None

    def verdict(self, session, url: str, timeout) -> str:
        try:
            origin = origin_of(url)
        except ValueError:
            return ""
        with self._guard:
            lock = self._locks.setdefault(origin, threading.Lock())
        with lock:
            if origin not in self._data:
                res = fetch_raw(session, origin + "/robots.txt", min(timeout, 15), max_bytes=500_000)
                self.store(origin, res["status"], res["body"].decode("utf-8", "replace"), res["error"])
        kind, rules, label = self._data[origin]
        if kind == "ok":
            return "Allowed" if rules.allowed(url, self.agent) else "Blocked"
        return "No robots.txt" if kind == "none" else label


# --------------------------------------------------------------------------
# Sitemap reading
# --------------------------------------------------------------------------
SITEMAP_PATHS = (
    "/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml", "/sitemap.xml.gz",
    "/sitemaps.xml", "/sitemap/sitemap.xml", "/sitemap/index.xml", "/sitemap1.xml", "/post-sitemap.xml",
    "/page-sitemap.xml", "/sitemap.php", "/sitemap.txt", "/news-sitemap.xml",
)
FEED_PATHS = ("/feed/", "/rss.xml", "/feed.xml", "/atom.xml", "/rss/", "/index.xml")
HTML_SITEMAP_PATHS = ("/sitemap/", "/sitemap.html", "/site-map/", "/html-sitemap/", "/sitemap.htm")
VIA_ENTERED, VIA_ROBOTS, VIA_COMMON, VIA_INDEX = "Entered by you", "robots.txt", "Common location", "Sitemap index"
VIA_FEED, VIA_HTML, VIA_HOME = "RSS / Atom feed", "HTML sitemap page", "Homepage links"
_SKIP_LINK_EXT = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".avif", ".css", ".js", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".zip", ".rar", ".mp4", ".mp3", ".webm", ".exe", ".dmg",
)
_LASTMOD = re.compile(r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?)?)?$")


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def gunzip(content: bytes, limit: int = MAX_SITEMAP_BYTES):
    """Returns (bytes, was_gzip). Stops at `limit` bytes so a tiny file cannot expand without end."""
    if content[:2] != b"\x1f\x8b":
        return content, False
    try:
        return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(content, limit), True
    except zlib.error:
        try:
            return gzip.decompress(content), True
        except Exception:
            return b"", True


def lastmod_state(value: str) -> str:
    """'' when fine, otherwise 'missing', 'invalid' or 'future'."""
    if not value:
        return "missing"
    if not _LASTMOD.match(value):
        return "invalid"
    try:
        d = date(int(value[:4]), int(value[5:7] or 1), int(value[8:10] or 1))
    except ValueError:
        return "invalid"
    return "future" if d > date.today() + timedelta(days=1) else ""


def parse_sitemap(content: bytes) -> dict:
    """Reads one sitemap file.

    Returns kind ('index', 'urlset', 'rss', 'atom', 'text', 'html', 'unknown'), entries and error.
    An index entry is {'loc', 'lastmod'}; a URL entry is {'loc', 'lastmod', 'images', 'hreflang'}.
    """
    out = {"kind": "unknown", "entries": [], "error": ""}
    if content[:3] == b"\xef\xbb\xbf":
        content = content[3:]
    content = content.lstrip()
    head = content[:3000].lower()
    if not content:
        return out
    if head.startswith((b"<!doctype html", b"<html")) or (
        b"<html" in head and b"<urlset" not in head and b"<sitemapindex" not in head
    ):
        out["kind"] = "html"
        return out
    if not content.startswith(b"<"):
        lines = [l.strip() for l in content.decode("utf-8", "replace").splitlines()]
        urls = [l for l in lines if l.lower().startswith(("http://", "https://"))]
        if urls:
            out["kind"] = "text"
            out["entries"] = [{"loc": u, "lastmod": "", "images": 0, "hreflang": 0} for u in urls]
        return out

    kinds = {"sitemapindex": "index", "urlset": "urlset", "rss": "rss", "feed": "atom"}
    depth, root = 0, None
    try:
        for event, el in SafeET.iterparse(io.BytesIO(content), events=("start", "end")):
            tag = _local(el.tag)
            if event == "start":
                depth += 1
                if root is None:
                    root = tag
                    out["kind"] = kinds.get(tag, "unknown")
                continue
            level, depth = depth, depth - 1
            kind = out["kind"]
            if kind in ("urlset", "index") and level == 2 and tag in ("url", "sitemap"):
                entry = {"loc": "", "lastmod": "", "images": 0, "hreflang": 0}
                for ch in el:
                    t = _local(ch.tag)
                    if t == "loc":
                        entry["loc"] = (ch.text or "").strip()
                    elif t == "lastmod":
                        entry["lastmod"] = (ch.text or "").strip()
                    elif t == "image":
                        entry["images"] += 1
                    elif t == "link" and ch.get("hreflang"):
                        entry["hreflang"] += 1
                if entry["loc"]:
                    out["entries"].append(entry)
                el.clear()
            elif kind == "rss" and tag == "item":
                texts = ((ch.text or "").strip() for ch in el if _local(ch.tag) == "link")
                link = next((t for t in texts if t), "")
                if link:
                    out["entries"].append({"loc": link, "lastmod": "", "images": 0, "hreflang": 0})
                el.clear()
            elif kind == "atom" and tag == "entry":
                link = ""
                for ch in el:
                    if _local(ch.tag) == "link" and ch.get("href") and ch.get("rel", "alternate") == "alternate":
                        link = ch.get("href").strip()
                        break
                if link:
                    out["entries"].append({"loc": link, "lastmod": "", "images": 0, "hreflang": 0})
                el.clear()
    except Exception as e:
        out["error"] = clean(str(e))[:140] or e.__class__.__name__
        if out["kind"] == "unknown":
            out["kind"] = "index" if b"<sitemapindex" in head else "urlset"
        if not out["entries"]:  # broken XML: still pick up whatever <loc> values can be read
            found = re.findall(rb"<loc[^>]*>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", content, re.S | re.I)
            out["entries"] = [
                {"loc": html.unescape(v.decode("utf-8", "replace")).strip(), "lastmod": "", "images": 0, "hreflang": 0}
                for v in found if v.strip()
            ]
    return out


def page_links(body: bytes, page_url: str) -> list:
    """Internal links on an HTML page (same site, no files, no #fragments), in page order."""
    soup = BeautifulSoup(body, "lxml")
    base_tag = soup.find("base", href=True)
    try:
        base_url = urljoin(page_url, base_tag["href"].strip()) if base_tag else page_url
    except ValueError:
        base_url = page_url
    site, out = host_key(page_url), []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        try:
            p = urlsplit(urljoin(base_url, href))
        except ValueError:
            continue
        if p.scheme.lower() not in ("http", "https") or host_key(p.geturl()) != site:
            continue
        if p.path.lower().endswith(_SKIP_LINK_EXT):
            continue
        out.append(urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, "")))
    return uniq(out)


def _looks_like_sitemap(res: dict, path: str) -> bool:
    if res["status"] != 200 or not res["body"]:
        return False
    body = res["body"]
    if body[:2] == b"\x1f\x8b":
        return True
    head = body[:3000].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if b"<urlset" in head or b"<sitemapindex" in head:
        return True
    return path.endswith(".txt") and head.startswith((b"http://", b"https://"))


def _probe(session, origin, paths, timeout, accept):
    """Requests several paths at once and returns the first one (in list order) that `accept`s."""
    def one(path):
        return path, fetch_raw(session, origin + path, min(timeout, 10), max_bytes=400_000, retries=0)
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = dict(ex.map(one, paths))
    for path in paths:
        if accept(results[path], path):
            return origin + path, results[path]
    return None, None


def discover_sitemaps(session, raw: str, timeout) -> dict:
    """Finds the sitemap(s) for what the user typed: a sitemap URL, a domain or a homepage URL.

    Order tried for a domain: robots.txt, common sitemap locations, RSS/Atom feed,
    HTML sitemap page, and last the links on the homepage.
    Returns origin, sources [(url, found_via), ...], notes, fallback, error and the robots.txt result.
    """
    out = {"entered": raw.strip(), "origin": "", "sources": [], "notes": [], "fallback": "", "error": "",
           "robots_status": None, "robots_text": "", "robots_error": "", "robots_sitemaps": []}
    raw = raw.strip().strip('"\'')
    if not raw:
        out["error"] = "Enter a sitemap URL or a domain."
        return out
    typed_scheme = bool(re.match(r"^https?://", raw, re.I))
    if not typed_scheme:
        raw = "https://" + raw
    try:
        p = urlsplit(raw)
        if not p.netloc or "." not in p.netloc and not p.netloc.startswith("localhost") and ":" not in p.netloc:
            raise ValueError
    except ValueError:
        out["error"] = "That does not look like a URL or a domain."
        return out
    path = p.path.lower()
    is_sitemap_url = path.endswith((".xml", ".gz", ".txt")) or "sitemap" in path
    origin = origin_of(raw)
    home = None

    if not is_sitemap_url:
        # Load the homepage first: it tells us the real address (www or not, http or https)
        home = fetch_raw(session, origin + "/", timeout, max_bytes=MAX_HTML_BYTES)
        if home["status"] is None and not typed_scheme:
            alt = fetch_raw(session, "http://" + p.netloc + "/", timeout, max_bytes=MAX_HTML_BYTES)
            if alt["status"] is not None:
                out["notes"].append(f"{origin} could not be reached ({home['error']}), so the http:// address is used.")
                home, origin = alt, "http://" + p.netloc.lower()
        if home["status"] is None:
            out["error"] = f"Could not reach {p.netloc} ({home['error']}). Check the address, or paste the sitemap URL."
            return out
        try:
            landed = origin_of(home["final_url"])
        except ValueError:
            landed = origin
        if landed != origin and host_key(landed) == host_key(origin):
            out["notes"].append(f"{origin} redirects to {landed}, so {landed} is used.")
            origin = landed
    out["origin"] = origin

    rb = fetch_raw(session, origin + "/robots.txt", min(timeout, 15), max_bytes=500_000)
    out["robots_status"], out["robots_error"] = rb["status"], rb["error"]
    if rb["status"] == 200:
        out["robots_text"] = rb["body"].decode("utf-8", "replace")
        out["robots_sitemaps"] = uniq(RobotsRules(out["robots_text"]).sitemaps)

    if is_sitemap_url:
        out["sources"] = [(raw, VIA_ENTERED)]
        return out
    if out["robots_sitemaps"]:
        out["sources"] = [(u, VIA_ROBOTS) for u in out["robots_sitemaps"]]
        n = len(out["sources"])
        out["notes"].append(f"{n} sitemap{'s' if n != 1 else ''} listed in robots.txt.")
        return out
    found, _ = _probe(session, origin, SITEMAP_PATHS, timeout, _looks_like_sitemap)
    if found:
        out["sources"] = [(found, VIA_COMMON)]
        out["notes"].append(f"Sitemap found at {found} (it is not listed in robots.txt).")
        return out

    # No XML sitemap anywhere: fall back to the next best list of URLs
    def is_feed(res, _path):
        return res["status"] == 200 and parse_sitemap(res["body"])["kind"] in ("rss", "atom")

    def is_html_sitemap(res, _path):
        # a real HTML sitemap says so in its <title>; this skips sites that answer 200 for any address
        if res["status"] != 200 or not is_html(res["ctype"]):
            return False
        title = re.search(rb"<title[^>]*>(.*?)</title>", res["body"][:20000], re.I | re.S)
        named = bool(title) and re.search(rb"site\s*map", title.group(1), re.I) is not None
        return named and len(page_links(res["body"], res["final_url"])) >= 10

    found, _ = _probe(session, origin, HTML_SITEMAP_PATHS, timeout, is_html_sitemap)
    if found:
        out["sources"], out["fallback"] = [(found, VIA_HTML)], VIA_HTML
        return out
    found, _ = _probe(session, origin, FEED_PATHS, timeout, is_feed)
    if found:
        out["sources"], out["fallback"] = [(found, VIA_FEED)], VIA_FEED
        return out
    out["sources"], out["fallback"] = [(home["final_url"], VIA_HOME)], VIA_HOME
    return out


def read_sitemaps(session, disc: dict, timeout, on_progress=None):
    """Downloads every sitemap file (following sitemap indexes) and lists what each one contains.

    Returns (files, entries): one record per sitemap file and one per <url> entry, duplicates included.
    """
    files, entries = [], []
    queue = [(u, via, "", "") for u, via in disc["sources"]]  # (url, found via, listed in, lastmod)
    seen = set()
    while queue and len(files) < MAX_SITEMAP_FILES and len(entries) < MAX_INVENTORY_URLS:
        url, via, parent, idx_lastmod = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        rec = {"Sitemap File": url, "Type": "", "Found Via": via, "Listed In": parent, "Status Code": None,
               "URLs": 0, "Child Sitemaps": 0, "Size (KB)": None, "Compressed": "", "Lastmod": idx_lastmod,
               "Problems": "", "_issues": []}
        files.append(rec)
        problems = rec["_issues"]
        from_page = via in (VIA_HTML, VIA_HOME)
        res = fetch_raw(session, url, timeout, max_bytes=MAX_HTML_BYTES if from_page else MAX_SITEMAP_BYTES)
        rec["Status Code"] = res["status"]
        if res["status"] != 200:
            problems.append((CRITICAL, "Sitemap file could not be read",
                             f"Could not be read ({res['status'] or res['error']})"))
        elif from_page:
            links = page_links(res["body"], res["final_url"])
            rec.update({"Type": "HTML page", "URLs": len(links), "Size (KB)": round(len(res["body"]) / 1024, 1)})
            entries += [{"URL": u, "Sitemap File": url, "Lastmod": "", "Images": 0, "Hreflang": 0, "_xml": False}
                        for u in links]
        else:
            content, was_gzip = gunzip(res["body"])
            rec["Compressed"] = "Yes" if was_gzip else "No"
            rec["Size (KB)"] = round(len(content) / 1024, 1)
            parsed = parse_sitemap(content)
            kind, found = parsed["kind"], parsed["entries"]
            rec["Type"] = {"index": "Sitemap index", "urlset": "URL sitemap", "text": "Text sitemap",
                           "rss": "RSS feed", "atom": "Atom feed", "html": "HTML page"}.get(kind, "Unknown")
            if parsed["error"]:
                problems.append((CRITICAL, "XML error in sitemap file", f"XML error ({parsed['error']})"))
            if kind == "html":
                problems.append((CRITICAL, "Sitemap URL returns a web page, not a sitemap", "Returns a web page, not a sitemap"))
            elif kind == "unknown" and not parsed["error"]:
                problems.append((CRITICAL, "Sitemap file format not recognised", "Format not recognised"))
            elif kind == "index":
                rec["Child Sitemaps"] = len(found)
                for e in found:
                    try:
                        child = urljoin(url, e["loc"])
                    except ValueError:
                        continue
                    queue.append((child, VIA_INDEX, url, e["lastmod"]))
                if not found and not parsed["error"]:
                    problems.append((WARNING, "Sitemap file is empty", "Empty"))
            else:
                rec["URLs"] = len(found)
                xml = kind == "urlset"
                entries += [{"URL": e["loc"], "Sitemap File": url, "Lastmod": e["lastmod"], "Images": e["images"],
                             "Hreflang": e["hreflang"], "_xml": xml} for e in found]
                if not found and not parsed["error"]:
                    problems.append((WARNING, "Sitemap file is empty", "Empty"))
                if len(found) > SITEMAP_URL_LIMIT:
                    problems.append((CRITICAL, f"More than {SITEMAP_URL_LIMIT:,} URLs in one sitemap file",
                                     f"{len(found):,} URLs (limit {SITEMAP_URL_LIMIT:,})"))
            if len(content) > SITEMAP_SIZE_LIMIT_MB * 1_000_000 or res["truncated"]:
                problems.append((CRITICAL, f"Sitemap file larger than {SITEMAP_SIZE_LIMIT_MB} MB",
                                 f"Larger than {SITEMAP_SIZE_LIMIT_MB} MB"))
        rec["Problems"] = "; ".join(text for _, _, text in problems)
        if on_progress:
            on_progress(len(files), len(entries))
    return files, entries


def _sections(paths: list) -> list:
    """Groups URLs by their first folder: /blog/post-1 -> /blog/."""
    parts = [None if p is None else [s for s in p.split("/") if s] for p in paths]
    folders = {segs[0].lower() for segs in parts if segs and len(segs) > 1}
    out = []
    for segs in parts:
        if segs is None:
            out.append("Not a valid URL")
        elif not segs:
            out.append("Homepage")
        elif len(segs) > 1 or segs[0].lower() in folders:
            out.append(f"/{segs[0].lower()}/")
        else:
            out.append("Top-level pages")
    return out


def build_inventory(disc: dict, files: list, entries: list) -> dict:
    """Turns the raw sitemap entries into the URL inventory, section counts and the list of problems."""
    origin = disc["origin"]
    try:
        o = urlsplit(origin)
        site_scheme, site_host, site_key = o.scheme, (o.hostname or "").lower(), host_key(origin)
    except ValueError:
        site_scheme, site_host, site_key = "https", "", ""

    times, first = {}, {}
    for e in entries:
        times[e["URL"]] = times.get(e["URL"], 0) + 1
        first.setdefault(e["URL"], e)
    urls = list(first)
    slashless = {}
    for u in urls:
        slashless.setdefault(u.rstrip("/"), set()).add(u)

    records, paths = [], []
    for u in urls:
        e, issues = first[u], []
        path, depth = None, None
        try:
            p = urlsplit(u)
            valid = p.scheme.lower() in ("http", "https") and bool(p.netloc)
        except ValueError:
            p, valid = None, False
        if not valid:
            issues.append((CRITICAL, "URL is not a full web address"))
        else:
            path = p.path
            depth = len([s for s in path.split("/") if s])
            host = (p.hostname or "").lower()
            if p.scheme.lower() == "http" and site_scheme == "https":
                issues.append((WARNING, "HTTP URL in the sitemap"))
            if site_host and host != site_host:
                same_site = host_key(u) == site_key
                issues.append((WARNING, "www / non-www differs from the site" if same_site else "URL on a different domain"))
            if " " in u or any(ord(c) > 127 for c in u):
                issues.append((WARNING, "Spaces or unencoded characters in URL"))
            if len(u) > 2048:
                issues.append((WARNING, "URL longer than 2,048 characters"))
            if len(slashless[u.rstrip("/")]) > 1:
                issues.append((WARNING, "Listed with and without a trailing slash"))
            if p.query:
                issues.append((NOTICE, "URL has parameters"))
            if any(c.isupper() for c in path):
                issues.append((NOTICE, "Uppercase letters in URL"))
            if p.fragment:
                issues.append((NOTICE, "URL has a # fragment"))
        if times[u] > 1:
            issues.append((WARNING, "Listed more than once in the sitemap"))
        if e["_xml"]:
            state = lastmod_state(e["Lastmod"])
            if state == "missing":
                issues.append((NOTICE, "Lastmod missing"))
            elif state == "invalid":
                issues.append((WARNING, "Lastmod is not a valid date"))
            elif state == "future":
                issues.append((WARNING, "Lastmod is in the future"))
        issues.sort(key=lambda i: SEV_RANK[i[0]])
        paths.append(path)
        records.append({
            "URL": u, "Section": "", "Depth": depth, "Sitemap File": e["Sitemap File"], "Lastmod": e["Lastmod"],
            "Times Listed": times[u], "Images in Sitemap": e["Images"], "Hreflang in Sitemap": e["Hreflang"],
            "Issues": "; ".join(name for _, name in issues), "_issues": issues,
        })
    for rec, section in zip(records, _sections(paths)):
        rec["Section"] = section

    cols = ["URL", "Section", "Depth", "Sitemap File", "Lastmod", "Times Listed",
            "Images in Sitemap", "Hreflang in Sitemap", "Issues", "_issues"]
    url_df = pd.DataFrame(records, columns=cols)
    for c in ("Depth", "Times Listed", "Images in Sitemap", "Hreflang in Sitemap"):
        url_df[c] = pd.array(url_df[c].tolist(), dtype="Int64")

    file_cols = ["Sitemap File", "Type", "Found Via", "Listed In", "Status Code", "URLs", "Child Sitemaps",
                 "Size (KB)", "Compressed", "Lastmod", "Problems"]
    file_df = pd.DataFrame([{c: f[c] for c in file_cols} for f in files], columns=file_cols)
    for c in ("Status Code", "URLs", "Child Sitemaps"):
        file_df[c] = pd.array(file_df[c].tolist(), dtype="Int64")
    file_df["Size (KB)"] = pd.array(file_df["Size (KB)"].tolist(), dtype="Float64")

    if len(url_df):
        counts = url_df["Section"].value_counts()
        section_df = pd.DataFrame({
            "Section": counts.index, "URLs": counts.values,
            "Share of URLs (%)": (100 * counts.values / len(url_df)).round(1),
        })
    else:
        section_df = pd.DataFrame(columns=["Section", "URLs", "Share of URLs (%)"])

    # ---- problems: per URL, per sitemap file and for the site as a whole
    tally = {}

    def count(sev, name, applies_to, n=1):
        key = (sev, name, applies_to)
        tally[key] = tally.get(key, 0) + n

    for rec in records:
        for sev, name in rec["_issues"]:
            count(sev, name, "URLs")
    for f in files:
        for sev, name, _ in f["_issues"]:
            count(sev, name, "Sitemap files")
    fallback = disc.get("fallback", "")
    if fallback:
        count(CRITICAL, "No XML sitemap found", "Site")
    else:
        # only when robots.txt names no sitemap at all (a sitemap you typed may be a child of a listed index)
        if disc.get("robots_status") == 200 and not disc.get("robots_sitemaps"):
            count(NOTICE, "Sitemap is not listed in robots.txt", "Site")
        dated = [r["Lastmod"][:10] for r in records if r["Lastmod"]]
        if len(dated) >= 20 and len(set(dated)) == 1:
            count(NOTICE, "Every lastmod date is the same", "Site")
    issue_rows = [{"Issue": name, "Severity": sev, "Count": n, "Applies To": where}
                  for (sev, name, where), n in tally.items()]
    issue_rows.sort(key=lambda d: (SEV_RANK[d["Severity"]], -d["Count"], d["Issue"]))
    issue_df = pd.DataFrame(issue_rows, columns=["Issue", "Severity", "Count", "Applies To"])

    return {"origin": origin, "fallback": fallback, "notes": list(disc.get("notes", [])),
            "files": file_df, "urls": url_df, "sections": section_df, "issues": issue_df,
            "entries": len(entries)}


def inventory_numbers(inv: dict) -> dict:
    urls = inv["urls"]
    with_lastmod = int((urls["Lastmod"] != "").sum()) if len(urls) else 0
    return {
        "Sitemap files": len(inv["files"]),
        "URLs listed": inv["entries"],
        "Unique URLs": len(urls),
        "Listed more than once": int((urls["Times Listed"] > 1).sum()) if len(urls) else 0,
        "Sections": len(inv["sections"]),
        "With lastmod": f"{round(100 * with_lastmod / len(urls))}%" if len(urls) else "0%",
    }


def select_urls(url_df: pd.DataFrame, sections: list, include: str, exclude: str,
                per_section: int, max_urls: int) -> list:
    """The URLs to check: chosen sections, optional text filters, optional even sample per section."""
    df = url_df[url_df["Section"].isin(sections)]
    lower = df["URL"].str.lower()
    if include.strip():
        df = df[lower.str.contains(include.strip().lower(), regex=False)]
        lower = df["URL"].str.lower()
    for bad in [x.strip().lower() for x in exclude.split(",") if x.strip()]:
        df = df[~lower.str.contains(bad, regex=False)]
        lower = df["URL"].str.lower()
    if per_section and per_section > 0:
        keep = []
        for _, group in df.groupby("Section", sort=False):
            n = len(group)
            if n <= per_section:
                keep += list(group.index)
            else:  # evenly spaced through the section, so old and new URLs are both covered
                step = (n - 1) / (per_section - 1) if per_section > 1 else 0
                picks = sorted({round(i * step) for i in range(per_section)})
                keep += [group.index[i] for i in picks]
        df = df.loc[sorted(keep)]
    return df["URL"].tolist()[: int(max_urls)]


def sitemap_extra(url_df: pd.DataFrame):
    """For finalize(): adds what the sitemap says about a URL to its page-check row."""
    lookup = {rec["URL"]: rec for rec in url_df.to_dict("records")}
    cols = SITEMAP_GROUP["Sitemap"]

    def extra(row):
        rec = lookup.get(row["URL"], {})
        values = {c: (None if rec.get(c) is pd.NA else rec.get(c, None if c in NUM_COLS else "")) for c in cols}
        issues = [(sev, name, name) for sev, name in rec.get("_issues", [])]
        if row["Indexable"] == "No":
            issues.append((WARNING, "Non-indexable URL in the sitemap", "Non-indexable URL in the sitemap"))
        return values, issues

    return extra
