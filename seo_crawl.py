"""
SEO Audit Toolkit - site crawl and link checks (no screen code in this file)

  crawl_site()      starts at a page and follows internal links level by level, checking every page
  compare_sitemap() marks which crawled pages are in the sitemap, and checks sitemap pages the crawl never reached
  check_links()     checks where every link on the crawled pages leads (broken links, links to redirects)

Used by page_crawl.py (Site crawl) and, for the link check, by page_bulk.py.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

import seo_core as core

# --------------------------------------------------------------------------
# Settings you can safely change
# --------------------------------------------------------------------------
DEEP_PAGE_CLICKS = 3          # more clicks than this from the start page -> "Deep page"
MAX_ORPHAN_CHECKS = 1000      # most sitemap-only pages to check after a crawl
MAX_LINK_CHECKS = 3000        # most link targets to request in one link check
LINK_TIMEOUT = 10             # seconds to wait for each link target
# Sites that answer automated requests with these codes often work fine in a browser
UNVERIFIABLE_CODES = {401, 403, 405, 406, 429, 999}

LINK_COLS = ["Source Page", "Link URL", "Anchor Text", "Link Type", "Nofollow", "Status Code", "Final URL", "Result"]


def crawl_key(url: str) -> str:
    """How two addresses are judged to be the same page: scheme and host in lower case, no #fragment."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


# --------------------------------------------------------------------------
# Starting point
# --------------------------------------------------------------------------
def resolve_start(session, raw: str, timeout):
    """Turns what the user typed into the page the crawl starts from. Returns (start_url, notes, error)."""
    raw = raw.strip().strip('"\'')
    if not raw:
        return "", [], "Enter a domain or the page to start from."
    typed_scheme = raw.lower().startswith(("http://", "https://"))
    url = raw if typed_scheme else "https://" + raw
    try:
        p = urlsplit(url)
        if not p.netloc:
            raise ValueError
    except ValueError:
        return "", [], "That does not look like a web address."
    notes = []
    res = core.fetch_raw(session, url, timeout, max_bytes=50_000, retries=0)
    if res["status"] is None and not typed_scheme:
        alt = "http://" + raw
        res2 = core.fetch_raw(session, alt, timeout, max_bytes=50_000, retries=0)
        if res2["status"] is not None:
            notes.append(f"{url} could not be reached ({res['error']}), so the http:// address is used.")
            url, res = alt, res2
    if res["status"] is None:
        return "", notes, f"Could not reach {p.netloc} ({res['error']}). Check the address and try again."
    landed = res["final_url"] or url
    if crawl_key(landed) != crawl_key(url):
        notes.append(f"{url} redirects to {landed}, so the crawl starts there.")
        url = landed
    if not urlsplit(url).path:
        url += "/"  # example.com -> example.com/
    return url, notes, ""


def not_crawled_row(url: str) -> dict:
    """A row for a URL the crawl found but did not request, because robots.txt blocks it."""
    row = core.blank_row(url)
    row["Robots.txt"] = "Blocked"
    row["Fetch Error"] = "Not crawled (blocked by robots.txt)"
    row["Indexable"], row["Indexability Reason"] = "No", "Blocked by robots.txt (not crawled)"
    row["_x"]["not_crawled"] = True
    return row


# --------------------------------------------------------------------------
# The crawl
# --------------------------------------------------------------------------
def crawl_site(session, start: str, settings: dict, robots, max_pages: int, max_depth: int,
               follow_robots: bool = True, skip_params: bool = True, on_progress=None, extra_opts: dict = None) -> dict:
    """Breadth-first crawl: the start page, then every page it links to, then the pages those link to...

    Returns a dict with
      rows          one audit row per crawled URL, in the order found
      links         [(source URL, link URL, anchor text, is_nofollow, is_internal), ...] from every page
      stopped       "" when every reachable page was crawled, else why it stopped
      skipped       {"parameters": n, "files": n}
    """
    timeout, delay, workers = settings["timeout"], settings["delay"], settings["workers"]
    site = core.host_key(start)
    opts = {**(extra_opts or {}), "links": True}
    seen = {crawl_key(start)}
    rows, by_key, links = [], {}, []
    inlinks, first_from = {}, {}
    skipped = {"parameters": set(), "files": set()}
    level, depth, stopped = [start], 0, ""
    started = time.time()

    def eligible(url: str) -> bool:
        try:
            p = urlsplit(url)
        except ValueError:
            return False
        if p.path.lower().endswith(core._SKIP_LINK_EXT):
            skipped["files"].add(crawl_key(url))
            return False
        if skip_params and p.query:
            skipped["parameters"].add(crawl_key(url))
            return False
        return True

    def queue(url: str, source: str, into: list):
        key = crawl_key(url)
        if key in seen or not eligible(url):
            return
        seen.add(key)
        first_from[key] = source
        into.append(url)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        while level:
            if depth > max_depth:
                stopped = f"Stopped at the depth limit ({max_depth} clicks). {len(level):,} more pages were found but not checked."
                break
            room = max_pages - len(rows)
            if room <= 0:
                stopped = f"Stopped at the page limit ({max_pages:,} pages). {len(level):,} more pages were found but not checked."
                break
            if len(level) > room:
                stopped = f"Stopped at the page limit ({max_pages:,} pages). {len(level) - room:,} more pages were found but not checked."
                level = level[:room]

            fetched = {}
            futures = {}
            for url in level:
                if follow_robots and robots.verdict(session, url, timeout) == "Blocked":
                    fetched[url] = not_crawled_row(url)
                else:
                    futures[ex.submit(core.audit_url, session, url, timeout, delay, robots, opts)] = url
            for fut in as_completed(futures):
                fetched[futures[fut]] = fut.result()
                if on_progress:
                    on_progress(len(rows) + len(fetched), depth, time.time() - started)

            next_level = []
            for url in level:  # keep the order pages were found in
                row = fetched[url]
                key = crawl_key(url)
                row["Crawl Depth"] = depth
                row["Linked From"] = first_from.get(key, "")
                rows.append(row)
                by_key[key] = row
                x = row["_x"]
                final = row["Final URL"]
                if row["Redirect Hops"] and final and core.host_key(final) == site:
                    # the page a redirect lands on is part of the site too; it inherits the links to the redirect
                    target = crawl_key(final)
                    inlinks.setdefault(target, set()).update(inlinks.get(key, set()))
                    queue(final, url, next_level)
                if not x.get("parsed") or row["Redirect Hops"]:
                    x.pop("links", None)  # a redirect's links belong to the page it lands on, crawled on its own
                    continue
                for target_url, anchor, nofollow in x.get("links", []):
                    internal = core.host_key(target_url) == site
                    links.append((url, target_url, anchor, nofollow, internal))
                    if internal:
                        inlinks.setdefault(crawl_key(target_url), set()).add(key)
                        if not nofollow and not x.get("nofollow_meta"):
                            queue(target_url, url, next_level)
                x.pop("links", None)  # kept in `links` now; frees memory
            level, depth = next_level, depth + 1

    for key, row in by_key.items():
        row["Inlinks"] = len(inlinks.get(key, set()) - {key})
    for row in rows:  # the start page needs no links pointing at it
        x = row["_x"]
        indexable = row["Indexable"] == "Yes"
        if indexable and row["Crawl Depth"] and row["Crawl Depth"] > DEEP_PAGE_CLICKS:
            x.setdefault("more_issues", []).append(
                (core.NOTICE, f"Deep page (more than {DEEP_PAGE_CLICKS} clicks from the start page)",
                 f"Deep page ({row['Crawl Depth']} clicks)"))
        if indexable and row["Crawl Depth"] and row["Inlinks"] == 1:
            x.setdefault("more_issues", []).append((core.NOTICE, "Only one internal link points here"))
    return {"rows": rows, "links": links, "stopped": stopped,
            "skipped": {k: len(v) for k, v in skipped.items()}, "site": site}


# --------------------------------------------------------------------------
# Crawl vs sitemap
# --------------------------------------------------------------------------
def compare_sitemap(session, crawl: dict, sitemap_urls: list, settings: dict, robots, on_progress=None,
                    opts: dict = None) -> pd.DataFrame:
    """Marks every crawled page as in / not in the sitemap, then checks the sitemap pages the crawl never reached.

    Adds those pages to crawl["rows"] (Crawl Depth empty, Inlinks 0) and returns the comparison table.
    """
    rows = crawl["rows"]
    in_sitemap = {crawl_key(u) for u in sitemap_urls}
    crawled = {crawl_key(r["URL"]) for r in rows}
    complete = not crawl["stopped"]
    for r in rows:
        r["In Sitemap"] = "Yes" if crawl_key(r["URL"]) in in_sitemap else "No"
        if (r["In Sitemap"] == "No" and r["Indexable"] == "Yes" and r["Final Status Code"] == 200
                and not r["Redirect Hops"]):
            r["_x"].setdefault("more_issues", []).append((core.WARNING, "Indexable page missing from the sitemap"))

    site = crawl["site"]
    missing = [u for u in dict.fromkeys(sitemap_urls)
               if crawl_key(u) not in crawled and core.host_key(u) == site][:MAX_ORPHAN_CHECKS]
    if missing:
        results = {}
        core.run_audit(missing, settings["workers"], settings["timeout"], settings["delay"], settings["user_agent"],
                       results, on_progress or (lambda n, t: None), robots, opts, session)
        for i in sorted(results):
            r = results[i]
            r["Crawl Depth"], r["Inlinks"], r["Linked From"], r["In Sitemap"] = None, 0, "", "Yes"
            if complete:
                r["_x"].setdefault("more_issues", []).append(
                    (core.WARNING, "Orphan page (in the sitemap, no internal links found)"))
            else:
                r["_x"].setdefault("more_issues", []).append((core.NOTICE, "In the sitemap, not reached by the crawl"))
            rows.append(r)

    table = []
    for r in rows:
        key = crawl_key(r["URL"])
        found = key in crawled
        listed = key in in_sitemap
        if listed and not found:
            where = "Orphan: in the sitemap, no internal links found" if complete else "In the sitemap, not reached by the crawl"
        elif found and not listed:
            if r["Indexable"] != "Yes" or r["Redirect Hops"]:
                continue  # non-indexable pages belong out of the sitemap anyway
            where = "Found by the crawl, missing from the sitemap"
        else:
            continue
        table.append({"URL": r["URL"], "Finding": where, "Status Code": r["Status Code"],
                      "Indexable": r["Indexable"], "Linked From": r.get("Linked From", "")})
    df = pd.DataFrame(table, columns=["URL", "Finding", "Status Code", "Indexable", "Linked From"])
    df["Status Code"] = pd.array(df["Status Code"].tolist(), dtype="Int64")
    return df


# --------------------------------------------------------------------------
# Link check
# --------------------------------------------------------------------------
def _link_result(status, final_status, hops, error, internal):
    if status is None:
        return f"Failed ({error or 'no answer'})" if internal else f"Could not be checked ({error or 'no answer'})"
    if hops:
        if final_status is None or final_status >= 400:
            return f"Redirect to an error ({final_status or error})"
        return f"Redirect ({status})"
    if status >= 500:
        return f"Server error ({status})"
    if status >= 400:
        if not internal and status in UNVERIFIABLE_CODES:
            return f"Not verified ({status}, site blocks automated checks)"
        return f"Broken ({status})"
    return "OK"


def is_broken(result: str) -> bool:
    return result.startswith(("Broken", "Server error", "Failed", "Redirect to an error"))


def check_links(session, links: list, known_rows: list, settings: dict, check_external: bool = True,
                on_progress=None) -> pd.DataFrame:
    """Where every link leads. Uses the rows already checked, requests the rest (without downloading pages).

    links       [(source URL, link URL, anchor text, is_nofollow, is_internal), ...]
    known_rows  audit rows already fetched (their status is reused)
    Returns one row per source page + link URL, and adds link issues to the source pages.
    """
    known, blocked = {}, set()
    for r in known_rows:
        if r["_x"].get("not_crawled"):
            blocked.add(crawl_key(r["URL"]))  # robots.txt said no, so the link check does not request it either
        else:
            known[crawl_key(r["URL"])] = (r["Status Code"], r["Final Status Code"], r["Redirect Hops"], r["Final URL"], r["Fetch Error"])

    targets = {}
    for _, target, _, _, internal in links:
        key = crawl_key(target)
        if key not in known and key not in blocked and key not in targets and (internal or check_external):
            targets[key] = target
    to_fetch = list(targets.items())[:MAX_LINK_CHECKS]
    timeout = min(settings["timeout"], LINK_TIMEOUT)

    def one(item):
        key, url = item
        res = core.fetch_chain(session, url, timeout, read_body=False)
        hops = res["hops"]
        first = hops[0][1] if hops else res["status"]
        return key, (first, res["status"], len(hops), res["final_url"], res["error"])

    with ThreadPoolExecutor(max_workers=settings["workers"]) as ex:
        futures = [ex.submit(one, item) for item in to_fetch]
        for n, fut in enumerate(as_completed(futures), 1):
            key, info = fut.result()
            known[key] = info
            if on_progress and (n % 5 == 0 or n == len(futures)):
                on_progress(n, len(futures))

    out, seen = [], set()
    for source, target, anchor, nofollow, internal in links:
        pair = (crawl_key(source), crawl_key(target))
        if pair in seen:
            continue
        seen.add(pair)
        info = known.get(pair[1])
        if pair[1] in blocked:
            result, status, final = "Not checked (blocked by robots.txt)", None, ""
        elif info is None:
            result, status, final = ("Not checked (external links off)" if not internal and not check_external
                                     else "Not checked (limit reached)"), None, ""
        else:
            status, final_status, hops, final, error = info
            result = _link_result(status, final_status, hops, error, internal)
            final = final if hops else ""
        out.append({"Source Page": source, "Link URL": target, "Anchor Text": anchor,
                    "Link Type": "Internal" if internal else "External", "Nofollow": "Yes" if nofollow else "No",
                    "Status Code": status, "Final URL": final, "Result": result})
    df = pd.DataFrame(out, columns=LINK_COLS)
    df["Status Code"] = pd.array(df["Status Code"].tolist(), dtype="Int64")

    # issues on the pages that hold the links
    by_source = {}
    for rec in out:
        by_source.setdefault(crawl_key(rec["Source Page"]), []).append(rec)
    for r in known_rows:
        recs = by_source.get(crawl_key(r["URL"]), [])
        if not r["_x"].get("parsed"):
            continue
        broken_int = sum(1 for rec in recs if rec["Link Type"] == "Internal" and is_broken(rec["Result"]))
        broken_ext = sum(1 for rec in recs if rec["Link Type"] == "External" and is_broken(rec["Result"]))
        to_redirect = sum(1 for rec in recs if rec["Link Type"] == "Internal" and rec["Result"].startswith("Redirect ("))
        r["Broken Links"] = broken_int + broken_ext
        r["Links To Redirects"] = to_redirect
        issues = r["_x"].setdefault("more_issues", [])
        if broken_int:
            issues.append((core.WARNING, "Broken internal links", f"Broken internal links ({broken_int})"))
        if broken_ext:
            issues.append((core.NOTICE, "Broken external links", f"Broken external links ({broken_ext})"))
        if to_redirect:
            issues.append((core.NOTICE, "Internal links to redirects", f"Internal links to redirects ({to_redirect})"))
    return df


def link_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"Links checked": 0, "Broken": 0, "To redirects": 0, "Not verified": 0}
    return {
        "Links checked": len(df),
        "Broken": int(df["Result"].map(is_broken).sum()),
        "To redirects": int(df["Result"].str.startswith("Redirect (").sum()),
        "Not verified": int(df["Result"].str.startswith(("Not verified", "Could not be checked", "Not checked")).sum()),
    }
