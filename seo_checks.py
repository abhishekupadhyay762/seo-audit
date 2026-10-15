"""
SEO Audit Toolkit - extra checks (no screen code in this file)

  validate_targets()   canonical targets and hreflang alternates: do they answer 200, are they indexable,
                       do hreflang pages link back
  keyword_*            keyword placement: title, H1, meta description, URL, first 100 words, H2s
  check_redirects()    migration check: does each old URL redirect to the expected new URL
  compare_runs()       before / after comparison of two exports from this tool
  sitemap_xml()        a clean XML sitemap from the indexable URLs found
"""

import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit
from xml.sax.saxutils import escape

import pandas as pd

import seo_core as core

# --------------------------------------------------------------------------
# Settings you can safely change
# --------------------------------------------------------------------------
MAX_TARGET_CHECKS = 2000      # most canonical / hreflang targets to request per run
KEYWORD_DENSITY_HIGH = 3.0    # % of main-content words above which density is flagged

# ISO 639-1 language codes and ISO 3166-1 alpha-2 region codes (what Google accepts in hreflang)
LANGUAGES = set("""
aa ab ae af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en
eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja
jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb
nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg sh si sk sl sm sn so
sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu
""".split())
REGIONS = set("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO
FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE
JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO
MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW
PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM
TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())


# --------------------------------------------------------------------------
# Pairs typed or uploaded: "URL, keyword" or "old URL, new URL"
# --------------------------------------------------------------------------
def _split_pair(line: str):
    for sep in ("\t", "|", ","):
        if sep in line:
            a, b = line.split(sep, 1)
            return a.strip().strip('"\''), b.strip().strip('"\'')
    parts = line.split(None, 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def parse_pairs(text: str, file=None, second_is_url: bool = False) -> list:
    """Reads pairs from pasted lines and/or an uploaded CSV / XLSX (first two columns).

    Lines whose first part is not a URL (a header row, for example) are skipped.
    With second_is_url, a second part like "/new-page" is read relative to the first URL.
    """
    rows = [_split_pair(l) for l in (text or "").splitlines() if l.strip()]
    if file is not None:
        raw = file.getvalue()
        if file.name.lower().endswith((".xlsx", ".xls")):
            table = pd.read_excel(io.BytesIO(raw), header=None, dtype=str)
        elif file.name.lower().endswith(".txt"):
            table = None
            rows += [_split_pair(l) for l in raw.decode("utf-8-sig", "replace").splitlines() if l.strip()]
        else:
            table = pd.read_csv(io.BytesIO(raw), header=None, dtype=str, encoding="utf-8-sig", keep_default_na=False)
        if table is not None:
            table = table.fillna("")
            for values in table.itertuples(index=False):
                a = str(values[0]).strip() if len(values) > 0 else ""
                b = str(values[1]).strip() if len(values) > 1 else ""
                rows.append((a, b))
    out = []
    for a, b in rows:
        if not core.looks_like_url(a):
            continue
        url = core.normalize_url(a)
        if not url:
            continue
        if second_is_url and b:
            if b.startswith("/"):
                b = urljoin(url, b)
            elif not re.match(r"^https?://", b, re.I) and core.looks_like_url(b):
                b = core.normalize_url(b)
        out.append((url, b))
    return out


# --------------------------------------------------------------------------
# Canonical targets and hreflang alternates
# --------------------------------------------------------------------------
def hreflang_code_problem(code: str):
    """None when the hreflang value is valid for Google, otherwise a short reason."""
    c = code.strip()
    if c.lower() == "x-default":
        return None
    if "_" in c:
        return "use a hyphen, not an underscore"
    parts = c.split("-")
    lang = parts[0].lower()
    if lang not in LANGUAGES:
        if len(parts) == 1 and lang.upper() in REGIONS:
            return "a region on its own is not allowed, add the language first"
        return "unknown language code"
    rest = parts[1:]
    if rest and len(rest[0]) == 4 and rest[0].isalpha():  # a script such as zh-Hant
        rest = rest[1:]
    if len(rest) > 1:
        return "too many parts"
    if rest:
        region = rest[0].upper()
        if region == "UK":
            return "use GB for the United Kingdom"
        if region not in REGIONS:
            return "unknown region code"
    return None


def _is_indexable(r) -> bool:
    return r["Indexable"] == "Yes"


def validate_targets(session, rows: list, robots, settings: dict, on_progress=None) -> int:
    """Checks the canonical target of every canonicalised page and every hreflang alternate.

    Targets already in `rows` are reused; the rest are requested (up to MAX_TARGET_CHECKS).
    Writes the results onto the rows (columns + issues). Returns how many extra URLs were requested.
    """
    known = {}
    for r in rows:
        known.setdefault(core.norm_url(r["URL"]), r)
    need = []
    for r in rows:
        x = r["_x"]
        if not x.get("parsed"):
            continue
        if r["Canonical Status"] == "Different" and r["Canonical URL"]:
            need.append(r["Canonical URL"])
        need += [href for _, href in x.get("hreflang", [])]
    fetch = [u for u in dict.fromkeys(need) if core.norm_url(u) not in known][:MAX_TARGET_CHECKS]
    if fetch:
        results = {}
        core.run_audit(fetch, settings["workers"], settings["timeout"], settings["delay"], settings["user_agent"],
                       results, on_progress or (lambda n, t: None), robots, None, session)
        for r in results.values():
            known.setdefault(core.norm_url(r["URL"]), r)

    for r in rows:
        x = r["_x"]
        if not x.get("parsed"):
            continue
        issues = x.setdefault("more_issues", [])
        _check_canonical(r, known, issues)
        _check_hreflang(r, known, issues)
    return len(fetch)


def _check_canonical(r, known, issues):
    status = r["Canonical Status"]
    if status == "Self":
        r["Canonical Target Note"] = "Self"
        return
    if status != "Different" or not r["Canonical URL"]:
        return
    t = known.get(core.norm_url(r["Canonical URL"]))
    if t is None:
        r["Canonical Target Note"] = "Not checked (limit reached)"
        return
    r["Canonical Target Status"] = t["Status Code"]
    fs = t["Final Status Code"]
    if fs is None and not t["Redirect Hops"]:
        r["Canonical Target Note"] = f"Could not be fetched ({t['Fetch Error']})"
        issues.append((core.WARNING, "Canonical target could not be fetched"))
    elif t["Redirect Hops"]:
        if fs is None or fs >= 400:
            r["Canonical Target Note"] = f"Redirects to an error ({fs or t['Fetch Error']})"
            issues.append((core.CRITICAL, "Canonical points to an error page"))
        else:
            r["Canonical Target Note"] = f"Redirects ({t['Status Code']}) to {t['Final URL']}"
            issues.append((core.WARNING, "Canonical points to a redirect"))
    elif fs >= 400:
        r["Canonical Target Note"] = f"Error ({fs})"
        issues.append((core.CRITICAL, "Canonical points to an error page", f"Canonical points to an error page ({fs})"))
    elif t["Robots.txt"] == "Blocked":
        r["Canonical Target Note"] = "Blocked by robots.txt"
        issues.append((core.WARNING, "Canonical points to a URL blocked by robots.txt"))
    elif t["_x"].get("noindex_meta") or t["_x"].get("noindex_header"):
        r["Canonical Target Note"] = "Noindex"
        issues.append((core.CRITICAL, "Canonical points to a noindex page"))
    elif t["Canonical Status"] == "Different":
        r["Canonical Target Note"] = f"Canonicalises again, to {t['Canonical URL']}"
        issues.append((core.WARNING, "Canonical chain (the target canonicalises elsewhere)"))
    else:
        r["Canonical Target Note"] = "OK"


def _check_hreflang(r, known, issues):
    alternates = r["_x"].get("hreflang", [])
    if not alternates:
        return
    problems, found = [], {}
    own = {core.norm_url(r["URL"]), core.norm_url(r["Final URL"] or r["URL"])}
    by_code = {}
    for code, href in alternates:
        reason = hreflang_code_problem(code)
        if reason:
            problems.append(f"{code}: {reason}")
            found["Invalid hreflang code"] = found.get("Invalid hreflang code", 0) + 1
        by_code.setdefault(code.strip().lower(), set()).add(core.norm_url(href))
    dups = [c for c, hrefs in by_code.items() if len(hrefs) > 1]
    if dups:
        problems.append("same code for different URLs: " + ", ".join(dups))
        found["Duplicate hreflang codes"] = len(dups)
    if not any(core.norm_url(h) in own for _, h in alternates):
        problems.append("no hreflang points to this page itself")
        found["No self-referencing hreflang"] = 1
    if len(alternates) >= 2 and "x-default" not in by_code:
        found["No x-default hreflang"] = 1
    for code, href in alternates:
        key = core.norm_url(href)
        if key in own:
            continue
        t = known.get(key)
        if t is None:
            continue
        fs = t["Final Status Code"]
        if fs is None or fs >= 400 or t["Redirect Hops"]:
            what = f"redirects ({t['Status Code']})" if t["Redirect Hops"] else f"returns {fs or t['Fetch Error']}"
            problems.append(f"{code} alternate {what}")
            found["Hreflang alternate is broken or redirects"] = found.get("Hreflang alternate is broken or redirects", 0) + 1
        elif not _is_indexable(t):
            problems.append(f"{code} alternate is not indexable ({t['Indexability Reason']})")
            found["Hreflang alternate is not indexable"] = found.get("Hreflang alternate is not indexable", 0) + 1
        else:
            back = {core.norm_url(h) for _, h in t["_x"].get("hreflang", [])}
            if not (back & own):
                problems.append(f"no return link from the {code} page")
                found["Hreflang return link missing"] = found.get("Hreflang return link missing", 0) + 1
    severity = {"Invalid hreflang code": core.WARNING, "Duplicate hreflang codes": core.WARNING,
                "Hreflang alternate is broken or redirects": core.WARNING, "Hreflang alternate is not indexable": core.WARNING,
                "Hreflang return link missing": core.WARNING, "No self-referencing hreflang": core.NOTICE,
                "No x-default hreflang": core.NOTICE}
    for name, n in found.items():
        issues.append((severity[name], name, f"{name} ({n})" if n > 1 else name))
    r["Hreflang Problems"] = "; ".join(problems[:12])


# --------------------------------------------------------------------------
# Keyword check
# --------------------------------------------------------------------------
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def keyword_tokens(text: str) -> list:
    return [_stem(t) for t in _NON_WORD.split((text or "").lower()) if t]


def keyword_match(keyword: str, text: str) -> str:
    """'Yes' when the phrase appears (singular/plural ignored), 'Partial' when every word appears, else 'No'."""
    k, t = keyword_tokens(keyword), keyword_tokens(text)
    if not k:
        return ""
    if not t:
        return "No"
    n = len(k)
    if any(t[i:i + n] == k for i in range(len(t) - n + 1)):
        return "Yes"
    return "Partial" if set(k) <= set(t) else "No"


def keyword_count(keyword: str, text: str) -> int:
    k, t = keyword_tokens(keyword), keyword_tokens(text)
    n = len(k)
    return sum(1 for i in range(len(t) - n + 1) if t[i:i + n] == k) if n else 0


def keyword_extra(rows: list):
    """For finalize(): keyword columns and issues for each URL + keyword row."""
    targets = {}
    for r in rows:
        kw = " ".join(keyword_tokens(r.get("Target Keyword", "")))
        if kw and r["_x"].get("parsed"):
            targets.setdefault(kw, set()).add(core.norm_url(r["Final URL"] or r["URL"]))
    shared = {kw for kw, pages in targets.items() if len(pages) > 1}

    def extra(r):
        kw = r.get("Target Keyword", "")
        x = r["_x"]
        values = {c: "" for c in core.KEYWORD_GROUP["Keyword"]}
        values.update({"Target Keyword": kw, "Keyword Count": None, "Keyword Density (%)": None})
        if not kw or not x.get("parsed"):
            return values, []
        path = urlsplit(r["Final URL"] or r["URL"]).path
        text = x.get("main_text", "")
        first100 = x.get("intro_text") or " ".join(text.split()[:100])
        h2 = [keyword_match(kw, h) for h in x.get("h2s", [])]
        places = {
            "In Title": keyword_match(kw, r["Title"]), "In H1": keyword_match(kw, r["H1"]),
            "In Meta Description": keyword_match(kw, r["Meta Description"]), "In URL": keyword_match(kw, path),
            "In First 100 Words": keyword_match(kw, first100),
        }
        count = keyword_count(kw, text)
        words = len(text.split())
        density = round(100 * count * len(keyword_tokens(kw)) / words, 2) if words else 0.0
        values.update(places)
        values.update({
            "In H2s": "Yes" if "Yes" in h2 else ("Partial" if "Partial" in h2 else "No"),
            "Keyword Count": count, "Keyword Density (%)": density,
            "Keyword Score": f"{sum(1 for v in places.values() if v == 'Yes')}/5",
        })
        issues = []
        for col, label, sev in (("In Title", "title", core.WARNING), ("In H1", "H1", core.WARNING)):
            if places[col] == "No":
                issues.append((sev, f"Keyword not in {label}"))
            elif places[col] == "Partial":
                issues.append((core.NOTICE, f"Keyword only partly in {label}"))
        if places["In Meta Description"] == "No":
            issues.append((core.NOTICE, "Keyword not in meta description"))
        if places["In URL"] == "No":
            issues.append((core.NOTICE, "Keyword not in URL"))
        if places["In First 100 Words"] == "No":
            issues.append((core.NOTICE, "Keyword not in the first 100 words"))
        if density > KEYWORD_DENSITY_HIGH:
            issues.append((core.NOTICE, f"High keyword density (over {KEYWORD_DENSITY_HIGH:g}%)",
                           f"High keyword density ({density:g}%)"))
        if " ".join(keyword_tokens(kw)) in shared:
            issues.append((core.WARNING, "Same keyword targeted by several URLs"))
        return values, [(s, n, t[0] if t else n) for s, n, *t in issues]

    return extra


# --------------------------------------------------------------------------
# Redirect check (site migration)
# --------------------------------------------------------------------------
REDIRECT_COLS = ["Old URL", "Expected URL", "Severity", "Result", "Match", "First Status", "Redirect Type", "Hops",
                 "Final URL", "Final Status", "Expected URL Status", "Redirect Chain"]


def url_match(final: str, expected: str) -> str:
    """'Exact', 'Close' (differs only in http/https, www, letter case or a trailing slash) or 'No'."""
    if not final or not expected:
        return ""
    if core.norm_url(final) == core.norm_url(expected):
        return "Exact"

    def loose(u):
        try:
            p = urlsplit(u)
        except ValueError:
            return u
        return core.host_key(u), (p.path.rstrip("/") or "/").lower(), p.query
    return "Close" if loose(final) == loose(expected) else "No"


def _status_text(res) -> str:
    if res["status"] is None and not res["hops"]:
        return res["error"] or "Failed"
    codes = [str(c) for _, c in res["hops"]] + [str(res["status"] or res["error"])]
    return " → ".join(codes)


def check_one_redirect(session, old: str, expected: str, timeout) -> dict:
    res = core.fetch_chain(session, old, timeout, read_body=False)
    hops, fs = res["hops"], res["status"]
    codes = [c for _, c in hops]
    row = {"Old URL": old, "Expected URL": expected, "First Status": codes[0] if codes else fs,
           "Redirect Type": (core.REDIRECT_LABEL.get(codes[0], str(codes[0])) if len(codes) == 1
                             else " → ".join(map(str, codes))) if codes else "",
           "Hops": len(codes), "Final URL": res["final_url"] if hops else "", "Final Status": fs,
           "Expected URL Status": "", "Redirect Chain": ""}
    if hops:
        row["Redirect Chain"] = " → ".join([f"{u} ({c})" for u, c in hops] + [f"{res['final_url']} ({fs or res['error']})"])
    match = url_match(res["final_url"], expected) if (hops and expected) else ""
    row["Match"] = match
    error = res["error"]

    if fs is None and not hops:
        sev, result = core.CRITICAL, f"Old URL could not be reached ({error})"
    elif fs is None:
        sev, result = core.CRITICAL, error or "Redirect failed"
    elif not hops:
        sev, result = core.CRITICAL, f"Not redirected ({fs})"
    elif fs >= 400:
        sev, result = core.CRITICAL, f"Redirects to an error page ({fs})"
    elif expected and match == "No":
        sev, result = core.CRITICAL, "Redirects to a different URL"
    elif any(c in (302, 303, 307) for c in codes):
        sev, result = core.WARNING, "Right place, but a temporary redirect"
    elif len(codes) > 1:
        sev, result = core.WARNING, f"Right place, but through a chain of {len(codes)} redirects"
    elif expected and match == "Close":
        sev, result = core.NOTICE, "Right place, small difference in the address"
    elif not expected:
        sev, result = "OK", "Redirects (no expected URL given)"
    else:
        sev, result = "OK", "Correct"
    if expected:
        if hops and match in ("Exact", "Close"):
            row["Expected URL Status"] = str(fs)
        else:
            row["Expected URL Status"] = _status_text(core.fetch_chain(session, expected, timeout, read_body=False))
    row["Severity"], row["Result"] = sev, result
    return row


def check_redirects(session, pairs: list, settings: dict, on_progress=None) -> pd.DataFrame:
    timeout = settings["timeout"]
    out = [None] * len(pairs)
    with ThreadPoolExecutor(max_workers=settings["workers"]) as ex:
        futures = {ex.submit(check_one_redirect, session, old, new, timeout): i for i, (old, new) in enumerate(pairs)}
        for n, fut in enumerate(as_completed(futures), 1):
            out[futures[fut]] = fut.result()
            if on_progress and (n % 3 == 0 or n == len(pairs)):
                on_progress(n, len(pairs))
    df = pd.DataFrame(out, columns=REDIRECT_COLS)
    for c in ("First Status", "Hops", "Final Status"):
        df[c] = pd.array(df[c].tolist(), dtype="Int64")
    return df


def redirect_numbers(df: pd.DataFrame) -> dict:
    return {
        "URLs checked": len(df),
        "Correct": int(df["Severity"].isin(["OK", core.NOTICE]).sum()),
        "Need attention": int((df["Severity"] == core.WARNING).sum()),
        "Wrong or broken": int((df["Severity"] == core.CRITICAL).sum()),
    }


def simple_excel(title: str, info: dict, numbers: dict, sheets: list, summary: pd.DataFrame = None) -> bytes:
    """An Excel file with a Summary sheet and one plain sheet per (name, table)."""
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    core._summary_sheet(wb, title, info, numbers, summary)
    for name, table in sheets:
        core._plain_sheet(wb, name[:31], table)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def redirect_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = df.groupby(["Result", "Severity"]).size().reset_index(name="URLs")
    out["_rank"] = out["Severity"].map({**core.SEV_RANK, "OK": 4})
    return out.sort_values(["_rank", "URLs"], ascending=[True, False])[["Result", "Severity", "URLs"]].reset_index(drop=True)


def redirects_excel_bytes(df: pd.DataFrame, info: dict) -> bytes:
    return simple_excel("Redirect check", info, redirect_numbers(df),
                        [("All redirects", df), ("Need fixing", df[df["Severity"].isin([core.CRITICAL, core.WARNING])])],
                        redirect_summary(df))


# --------------------------------------------------------------------------
# Compare two runs
# --------------------------------------------------------------------------
COMPARE_FIELDS = ["Status Code", "Final URL", "Indexable", "Indexability Reason", "Robots.txt", "Meta Robots",
                  "Canonical URL", "Title", "Meta Description", "H1", "H1 Count", "Word Count", "Schema Types",
                  "On-page Score", "Severity"]
_DETAIL = re.compile(r"\s*\([^()]*\)\s*$")


def load_export(file) -> pd.DataFrame:
    """Reads a CSV or Excel file downloaded from this tool (Excel: the All Data sheet)."""
    raw = file.getvalue()
    if file.name.lower().endswith((".xlsx", ".xls")):
        xl = pd.ExcelFile(io.BytesIO(raw))
        sheet = next((s for s in ("All Data", "URL inventory", "All redirects") if s in xl.sheet_names), xl.sheet_names[0])
        df = xl.parse(sheet, dtype=str)
    else:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig", keep_default_na=False)
    df = df.fillna("")
    for c in df.columns:  # undo the protection added to text that starts like a formula
        df[c] = df[c].map(lambda v: v[1:] if isinstance(v, str) and len(v) > 1 and v[0] == "'" and v[1] in "=+-@" else v)
    if "URL" not in df.columns:
        raise ValueError("this file has no URL column. Use a CSV or Excel file downloaded from this tool.")
    return df.drop_duplicates("URL").reset_index(drop=True)


def _issue_set(row) -> set:
    names = set()
    for col in ("Critical", "Warnings", "Notices"):
        for part in str(row.get(col, "") or "").split("; "):
            part = _DETAIL.sub("", part.strip())
            if part:
                names.add(part)
    return names


def _same(field, before, after) -> bool:
    if field == "On-page Score":
        try:
            return abs(float(after or 0) - float(before or 0)) < 1
        except ValueError:
            return str(before).strip() == str(after).strip()
    if field == "Word Count":
        try:
            b, a = float(before or 0), float(after or 0)
        except ValueError:
            return before == after
        return abs(a - b) < max(20, 0.1 * max(a, b))
    return str(before).strip() == str(after).strip()


def compare_runs(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    b, a = before.set_index("URL", drop=False), after.set_index("URL", drop=False)
    fields = [f for f in COMPARE_FIELDS if f in b.columns and f in a.columns]
    common = [u for u in a.index if u in b.index]
    added = [u for u in a.index if u not in b.index]
    removed = [u for u in b.index if u not in a.index]

    changes, per_url = [], []
    fixed_total = new_total = 0
    for u in common:
        rb, ra = b.loc[u], a.loc[u]
        changed = []
        for f in fields:
            if not _same(f, rb[f], ra[f]):
                changed.append(f)
                changes.append({"URL": u, "Field": f, "Before": rb[f], "After": ra[f]})
        ib, ia = _issue_set(rb), _issue_set(ra)
        fixed, new = sorted(ib - ia), sorted(ia - ib)
        fixed_total += len(fixed)
        new_total += len(new)
        if changed or fixed or new:
            per_url.append({"URL": u, "Changed Fields": ", ".join(changed), "Issues Fixed": "; ".join(fixed),
                            "New Issues": "; ".join(new), "Severity Before": rb.get("Severity", ""),
                            "Severity After": ra.get("Severity", "")})

    def tally(df):
        counts = {}
        for _, row in df.iterrows():
            for name in _issue_set(row):
                counts[name] = counts.get(name, 0) + 1
        return counts
    tb, ta = tally(b), tally(a)
    trend = [{"Issue": n, "URLs Before": tb.get(n, 0), "URLs After": ta.get(n, 0), "Change": ta.get(n, 0) - tb.get(n, 0)}
             for n in set(tb) | set(ta)]
    trend.sort(key=lambda d: (d["Change"], -d["URLs Before"]))
    numbers = {"URLs before": len(b), "URLs after": len(a), "In both": len(common), "New URLs": len(added),
               "Removed URLs": len(removed), "URLs with changes": len(per_url), "Issues fixed": fixed_total,
               "New issues": new_total}
    return {
        "numbers": numbers,
        "trend": pd.DataFrame(trend, columns=["Issue", "URLs Before", "URLs After", "Change"]),
        "per_url": pd.DataFrame(per_url, columns=["URL", "Changed Fields", "Issues Fixed", "New Issues",
                                                  "Severity Before", "Severity After"]),
        "changes": pd.DataFrame(changes, columns=["URL", "Field", "Before", "After"]),
        "added": pd.DataFrame({"URL": added}), "removed": pd.DataFrame({"URL": removed}),
    }


def is_page_audit(file) -> bool:
    """True for an Excel file downloaded from the Page audit tool."""
    if not file.name.lower().endswith(".xlsx"):
        return False
    try:
        names = pd.ExcelFile(io.BytesIO(file.getvalue())).sheet_names
    except Exception:
        return False
    return "Checklist" in names and "Areas" in names


def load_page_audit(file) -> dict:
    xl = pd.ExcelFile(io.BytesIO(file.getvalue()))
    summary = xl.parse("Summary", header=None, dtype=str).fillna("")
    kv = {}
    for values in summary.itertuples(index=False):
        if len(values) > 1 and str(values[0]).strip():
            kv.setdefault(str(values[0]).strip(), str(values[1]).strip())
    try:
        score = int(float(kv.get("On-page score", "") or 0))
    except ValueError:
        score = 0
    return {"url": kv.get("URL", ""), "keyword": kv.get("Keyword", ""), "score": score, "grade": kv.get("Grade", ""),
            "areas": xl.parse("Areas", dtype=str).fillna(""), "checklist": xl.parse("Checklist", dtype=str).fillna("")}


def _pts(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compare_page_audits(before: dict, after: dict) -> dict:
    """Score, areas and checks of two Page audit downloads of the same page."""
    b_areas = {r["Area"]: r for r in before["areas"].to_dict("records")}
    a_areas = {r["Area"]: r for r in after["areas"].to_dict("records")}
    areas = []
    for name in list(dict.fromkeys(list(b_areas) + list(a_areas))):
        bv = _pts(b_areas[name]["Score (%)"]) if name in b_areas else None
        av = _pts(a_areas[name]["Score (%)"]) if name in a_areas else None
        areas.append({"Area": name, "Before (%)": None if bv is None else int(bv), "After (%)": None if av is None else int(av),
                      "Change": None if bv is None or av is None else int(av - bv)})
    key = lambda r: (r["Area"], r["Check"])
    b_checks = {key(r): r for r in before["checklist"].to_dict("records")}
    a_checks = {key(r): r for r in after["checklist"].to_dict("records")}
    problem = {"Fail", "Warning"}
    changed = []
    for k in list(dict.fromkeys(list(b_checks) + list(a_checks))):
        rb, ra = b_checks.get(k), a_checks.get(k)
        res_b, res_a = (rb or {}).get("Result", "Not run"), (ra or {}).get("Result", "Not run")
        pts_b, pts_a = _pts((rb or {}).get("Points")), _pts((ra or {}).get("Points"))
        if res_b == res_a and abs(pts_a - pts_b) < 0.01 and (rb or {}).get("Found") == (ra or {}).get("Found"):
            continue
        if res_b in problem and res_a == "Pass":
            what = "Fixed"
        elif res_a in problem and res_b == "Pass":
            what = "New problem"
        elif pts_a > pts_b:
            what = "Better"
        elif pts_a < pts_b:
            what = "Worse"
        else:
            what = "Changed"
        changed.append({"Change": what, "Area": k[0], "Check": k[1], "Result Before": res_b, "Result After": res_a,
                        "Found Before": (rb or {}).get("Found", ""), "Found After": (ra or {}).get("Found", ""),
                        "Points Change": round(pts_a - pts_b, 2),
                        "How To Fix": (ra or {}).get("How To Fix", "") if res_a in problem else ""})
    order = {"New problem": 0, "Worse": 1, "Fixed": 2, "Better": 3, "Changed": 4}
    changed.sort(key=lambda c: (order[c["Change"]], -abs(c["Points Change"])))
    cols = ["Change", "Area", "Check", "Result Before", "Result After", "Found Before", "Found After", "Points Change",
            "How To Fix"]
    changes = pd.DataFrame(changed, columns=cols)
    numbers = {"Score before": before["score"], "Score after": after["score"], "Change": after["score"] - before["score"],
               "Checks fixed": int((changes["Change"] == "Fixed").sum()),
               "New problems": int((changes["Change"] == "New problem").sum())}
    area_df = pd.DataFrame(areas, columns=["Area", "Before (%)", "After (%)", "Change"])
    for c in ("Before (%)", "After (%)", "Change"):
        area_df[c] = pd.array(area_df[c].tolist(), dtype="Int64")
    return {"numbers": numbers, "areas": area_df,
            "changes": changes, "before": before, "after": after, "page_audit": True}


def page_compare_excel(result: dict, info: dict) -> bytes:
    return simple_excel("Page audit comparison", info, result["numbers"],
                        [("Areas", result["areas"]), ("Changed checks", result["changes"])])


def compare_excel_bytes(result: dict, info: dict) -> bytes:
    return simple_excel("Run comparison", info, result["numbers"], [
        ("Issue trend", result["trend"]), ("Changed URLs", result["per_url"]), ("All changes", result["changes"]),
        ("New URLs", result["added"]), ("Removed URLs", result["removed"])])


# --------------------------------------------------------------------------
# XML sitemap from the results
# --------------------------------------------------------------------------
def sitemap_urls(df: pd.DataFrame, lastmod: bool = True, images: bool = False) -> list:
    """[(url, lastmod, [image urls])] for every indexable URL that answered 200 without a redirect.

    lastmod  take the page's updated or published date (or the sitemap's lastmod) when there is one
    images   add the images found on each page (an image sitemap)"""
    ok = df[(df["Indexable"] == "Yes") & (df["Final Status Code"] == 200) & (df["Redirect Hops"] == 0)]
    out, seen = [], set()
    for rec in ok.to_dict("records"):
        url = rec["URL"]
        if url in seen:
            continue
        seen.add(url)
        date_ = ""
        if lastmod:
            for col in ("Updated", "Published", "Lastmod"):
                v = str(rec.get(col) or "")[:10]
                if v and core.lastmod_state(v) == "":
                    date_ = v
                    break
        pics = list(dict.fromkeys(rec.get("_images") or []))[:1000] if images else []
        out.append((url, date_, pics))
    return out


def _urlset(entries) -> bytes:
    with_images = any(e[2] for e in entries)
    rows = []
    for url, lastmod, pics in entries:
        lm = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        imgs = "".join(f"<image:image><image:loc>{escape(i)}</image:loc></image:image>" for i in pics)
        rows.append(f"  <url><loc>{escape(url)}</loc>{lm}{imgs}</url>")
    ns = ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"' if with_images else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"{ns}>\n'
            + "\n".join(rows) + "\n</urlset>\n").encode("utf-8")


def sitemap_xml(df: pd.DataFrame, lastmod: bool = True, images: bool = False):
    """Returns (file bytes, file name, mime type, URL count). Over 50,000 URLs: a zip with an index file."""
    entries = sitemap_urls(df, lastmod, images)
    limit = core.SITEMAP_URL_LIMIT
    if len(entries) <= limit:
        return _urlset(entries), "sitemap.xml", "application/xml", len(entries)
    origin = core.origin_of(entries[0][0])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        names = []
        for n, start in enumerate(range(0, len(entries), limit), 1):
            name = f"sitemap-{n}.xml"
            names.append(name)
            z.writestr(name, _urlset(entries[start:start + limit]))
        index = ('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 + "\n".join(f"  <sitemap><loc>{escape(origin)}/{n}</loc></sitemap>" for n in names)
                 + "\n</sitemapindex>\n")
        z.writestr("sitemap_index.xml", index)
    return buf.getvalue(), "sitemaps.zip", "application/zip", len(entries)


# --------------------------------------------------------------------------
# Open a saved run (a CSV or Excel download from this tool) to view it again
# --------------------------------------------------------------------------
def _issue_name(text: str, names: list) -> str:
    """The issue name behind the text shown on a row ("Images missing alt (2)" -> "Images missing alt attribute")."""
    base = _DETAIL.sub("", text.strip())
    for n in names:
        if base == n:
            return n
    starts = [n for n in names if base.startswith(n)]
    if starts:
        return max(starts, key=len)
    for n in names:
        if n.startswith(base):
            return n
    return base


def rebuild_run(raw: pd.DataFrame):
    """A saved download turned back into a results table. Returns (df, groups, overview columns, tool name)."""
    import seo_report as report
    cols = set(raw.columns)
    for need in ("Status Code", "Indexable", "Severity"):
        if need not in cols:
            raise ValueError("this file is not a page check download (no Status Code, Indexable or Severity column). "
                             "Use a CSV or Excel file from Sitemap audit, Site crawl, Bulk URL check or Keyword check.")
    if "Crawl Depth" in cols:
        base, overview, tool = core.CRAWL_GROUPS, core.CRAWL_OVERVIEW_COLS, "Site crawl"
    elif "Sitemap File" in cols:
        base, overview, tool = core.SITEMAP_GROUPS, core.SITEMAP_OVERVIEW_COLS, "Sitemap audit"
    elif "Target Keyword" in cols:
        base, overview, tool = core.KEYWORD_GROUPS, core.KEYWORD_OVERVIEW_COLS, "Keyword check"
    else:
        base, overview, tool = core.GROUPS, core.OVERVIEW_COLS, "Bulk URL check"
    extras = {"score": "On-page Score" in cols, "mobile": "Mobile Match" in cols, "security": "Mixed Content" in cols,
              "duplicates": "Exact Duplicates" in cols, "images": "Broken Images" in cols}
    groups = core.with_extras(base, **extras)
    df = pd.DataFrame({c: (raw[c] if c in cols else "") for c in core.all_cols(groups)})
    for c in df.columns:
        if c in core.INT_COLS:
            df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce").round().astype("Int64")
        elif c in core.FLOAT_COLS or c == "HTML Size (KB)":
            df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce").astype("Float64")
        else:
            df[c] = df[c].astype(str).replace({"nan": "", "<NA>": "", "None": ""})
    names = list(report.ADVICE)
    sev_cols = (("Critical", core.CRITICAL), ("Warnings", core.WARNING), ("Notices", core.NOTICE))
    df["_issues"] = [[(sev, _issue_name(part, names)) for col, sev in sev_cols
                      for part in str(r.get(col, "") or "").split("; ") if part.strip()]
                     for r in raw.to_dict("records")]
    df["_images"] = [[] for _ in range(len(df))]
    sev = df["Severity"].astype(str)
    df["Severity"] = sev.where(sev.isin(list(core.SEV_RANK)), "OK")
    return df.reset_index(drop=True), groups, core.overview_with_score(overview, extras["score"]), tool
