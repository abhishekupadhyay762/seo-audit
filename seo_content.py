"""
SEO Audit Toolkit - engine for the content and schema tools (no screen code in this file)

  1. Content check        readability and content analysis for pasted text or many URLs
  2. Schema check         required and recommended schema fields for many URLs or pasted code
  3. Competitor comparison  your page next to competitors, and a content brief (Word)
  4. Link opportunities   pages that mention a keyword but do not link to the target page

The single-page checks themselves (readability, content analysis, schema fields, score) are in
seo_page.py, so every tool gives the same numbers for the same page.
"""

import io
import json
import re
from collections import Counter
from datetime import date
from statistics import median

from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

import seo_checks as checks
import seo_core as core
import seo_page as page
import seo_report as report

# --------------------------------------------------------------------------
# Settings you can safely change
# --------------------------------------------------------------------------
HARD_TO_READ = 50          # reading ease below this is flagged
THIN_WORDS = core.THIN_CONTENT_WORDS
MAX_COMPETITORS = 5
MAX_MENTIONS_PER_PAGE = 20
_HTML_KEYS = ("html", "headers", "main_text_marked")


def _drop_html(x: dict, *more):
    for key in _HTML_KEYS + more:
        x.pop(key, None)


def _join(items, sep=", ", limit=None) -> str:
    items = [str(i) for i in items if i not in (None, "")]
    return sep.join(items[:limit] if limit else items)


# ==========================================================================
# 1. Content check
# ==========================================================================
_HEADING_MD = re.compile(r"^(#{1,6})\s+")
_BULLET = re.compile(r"^\s*(?:[-*•▪◦]|\d{1,2}[.)])\s+")


def paste_blocks(text: str):
    """Pasted text -> (paragraphs, headings). A line starting with # (Markdown), or a short line without an
    end mark, is treated as a heading; a line starting with a bullet or a number is a list item."""
    blocks, headings = [], []
    for raw in (text or "").splitlines():
        line = core.clean(raw)
        if not line:
            continue
        md = _HEADING_MD.match(line)
        if md:
            headings.append({"Level": f"H{len(md.group(1))}", "Heading": line[md.end():]})
            continue
        if _BULLET.match(line):
            blocks.append(_BULLET.sub("", line))
            continue
        if len(line.split()) <= 12 and not re.search(r"[.!?:;,…\"”)]$", line):
            headings.append({"Level": "Heading?", "Heading": line})
            continue
        blocks.append(line)
    return blocks, headings


def keyword_places(keyword: str, body: str, headings: list, title: str = "", h1: str = "") -> dict:
    """Where the keyword appears. Yes = the phrase, Partial = every word but not together."""
    if not keyword:
        return {}
    first100 = " ".join(body.split()[:100])
    in_heads = [checks.keyword_match(keyword, h) for h in headings]
    out = {"In First 100 Words": checks.keyword_match(keyword, first100),
           "In A Heading": "Yes" if "Yes" in in_heads else ("Partial" if "Partial" in in_heads else "No")}
    if title or h1:
        out = {"In Title": checks.keyword_match(keyword, title), "In H1": checks.keyword_match(keyword, h1), **out}
    return out


def suggestions(read: dict, numbers: dict, places: dict, n_headings: int, keyword: str = "") -> list:
    """[(short label, full advice), ...] for a text or a page."""
    out = []
    words = numbers.get("Words (main content)", 0)
    if words < THIN_WORDS:
        out.append(("Thin", f"Only {words} words. Pages under about {THIN_WORDS} words rarely rank for competitive "
                            "searches; cover the topic fully: what, why, how, cost, examples and questions people ask."))
    ease = read.get("Reading ease")
    if ease is not None and ease < HARD_TO_READ:
        out.append(("Hard to read", f"Reading ease is {ease:g} ({read['Level'].lower()}). Shorten sentences to 15 to 20 "
                                    "words on average and use everyday words."))
    if read.get("Long sentences (%)", 0) > 20:
        out.append(("Long sentences", f"{read['Long sentences (%)']:g}% of sentences have more than "
                                      f"{page.LONG_SENTENCE_WORDS} words. Split them in two."))
    if read.get("Long paragraphs", 0):
        n = read["Long paragraphs"]
        out.append(("Long paragraphs", f"{n} paragraph{'s' if n != 1 else ''} with more than {page.LONG_PARAGRAPH_WORDS} "
                                       "words. Break them into paragraphs of two to four sentences."))
    if words >= THIN_WORDS and not n_headings:
        out.append(("No subheadings", "No subheadings found. Break the text into sections with descriptive H2 headings."))
    if keyword:
        uses = numbers.get("Keyword uses", 0)
        if not uses:
            out.append(("Keyword missing", f"'{keyword}' does not appear as a phrase. Use it in the opening paragraph "
                                           "and in at least one heading."))
        else:
            if places.get("In First 100 Words") != "Yes":
                out.append(("Keyword late", f"'{keyword}' is not in the first 100 words. Mention it early."))
            if places.get("In A Heading") != "Yes":
                out.append(("Keyword not in headings", f"'{keyword}' is not in any heading. Use it, or a close "
                                                       "variation, in one H2."))
            if numbers.get("Keyword density (%)", 0) > checks.KEYWORD_DENSITY_HIGH:
                out.append(("Keyword overused", f"'{keyword}' makes up {numbers['Keyword density (%)']:g}% of the "
                                                "words. That can read as stuffing; use variations and related terms."))
    return out


def analyze_text(text: str, keyword: str = "") -> dict:
    """Readability and content analysis of pasted text (for example a draft from Google Docs)."""
    blocks, headings = paste_blocks(text)
    lines = [h["Heading"] for h in headings] + blocks
    body = " ".join(blocks)
    read = page.readability(blocks, "en")
    marked = f" {core.BLOCK_MARK} ".join(core.clean(l) for l in (text or "").splitlines() if core.clean(l))
    content = page.content_analysis(" ".join(lines), 0, keyword, marked)
    content["numbers"].pop("Text to HTML (%)", None)
    places = keyword_places(keyword, body, [h["Heading"] for h in headings])
    return {"read": read, "content": content, "headings": headings, "places": places, "keyword": keyword,
            "advice": suggestions(read, content["numbers"], places, len(headings), keyword)}


CONTENT_COLS = ["URL", "Status Code", "Title", "Word Count", "Reading Ease", "Reading Level", "Words per Sentence",
                "Long Sentences (%)", "Long Paragraphs", "Different Words", "Text to HTML (%)", "Top Words",
                "Top Phrases", "Target Keyword", "Keyword Uses", "Keyword Density (%)", "In Title", "In H1",
                "In First 100 Words", "In A Heading", "To Improve", "Note"]


def content_hook(keywords: dict) -> dict:
    """Page-check options that add the content analysis to every row. keywords = {url: keyword}."""
    def after(row: dict):
        x = row["_x"]
        try:
            if not x.get("parsed"):
                return
            details = page.page_details(row)
            read = page.readability(details["blocks"], row["Lang"])
            kw = keywords.get(row["URL"], "")
            content = page.content_analysis(x.get("main_text", ""), details["html_bytes"], kw, x.get("main_text_marked", ""))
            heads = [h["Heading"] for h in details["headings"] if h["Level"] != "H1"]
            places = keyword_places(kw, x.get("intro_text", "") or x.get("main_text", ""), heads, row["Title"], row["H1"])
            advice = suggestions(read, content["numbers"], places, len(heads), kw)
            n = content["numbers"]
            row.update({
                "Reading Ease": read.get("Reading ease"),
                "Reading Level": read.get("Level") or read.get("status", ""),
                "Words per Sentence": read["Average words per sentence"], "Long Sentences (%)": read["Long sentences (%)"],
                "Long Paragraphs": read["Long paragraphs"], "Different Words": n["Different words"],
                "Text to HTML (%)": n["Text to HTML (%)"],
                "Top Words": _join(content["words"]["Word"].head(5)),
                "Top Phrases": _join(content["phrases"]["Phrase"].head(5)),
                "Target Keyword": kw, "Keyword Uses": n.get("Keyword uses"), "Keyword Density (%)": n.get("Keyword density (%)"),
                **places, "To Improve": _join([a for a, _ in advice], "; "),
            })
            x["content"] = {"read": dict(read), "numbers": n, "words": content["words"],
                            "phrases": content["phrases"], "headings": details["headings"], "advice": advice}
        finally:
            _drop_html(x, "main_text", "intro_text", "h2s")
    return {"text": True, "keep_html": True, "after": after}


def content_table(rows: list) -> pd.DataFrame:
    records = []
    for r in rows:
        rec = {c: r.get(c, "") for c in CONTENT_COLS}
        rec["Status Code"] = r["Final Status Code"] if r["Final Status Code"] is not None else ""
        rec["Word Count"] = r["Word Count"] if r["_x"].get("parsed") else None
        if not r["_x"].get("parsed"):
            rec["Note"] = r["Fetch Error"] or f"Not an HTML page that answered 200 ({r['Final Status Code']})"
        elif r["Redirect Hops"]:
            rec["Note"] = f"Redirects to {r['Final URL']}; the content is from that page"
        records.append(rec)
    df = pd.DataFrame(records, columns=CONTENT_COLS)
    for c in ("Word Count", "Long Paragraphs", "Different Words", "Keyword Uses"):
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce").round().astype("Int64")
    for c in ("Reading Ease", "Words per Sentence", "Long Sentences (%)", "Text to HTML (%)", "Keyword Density (%)"):
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce").astype("Float64")
    if not df["Target Keyword"].astype(str).str.len().any():
        df = df.drop(columns=["Target Keyword", "Keyword Uses", "Keyword Density (%)", "In Title", "In H1",
                              "In First 100 Words", "In A Heading"])
    return df


def content_numbers(df: pd.DataFrame) -> dict:
    read = df["Reading Ease"].dropna()
    words = df["Word Count"].dropna()
    return {"URLs checked": len(df), "Pages read": int(len(words)),
            "Average reading ease": round(float(read.mean()), 1) if len(read) else "-",
            "Hard to read": int((read < HARD_TO_READ).sum()),
            "Thin (under 300 words)": int((words < THIN_WORDS).sum()),
            "Average words": int(round(float(words.mean()))) if len(words) else 0}


def content_excel(df: pd.DataFrame, rows: list, info: dict) -> bytes:
    words, phrases, heads = [], [], []
    for r in rows:
        c = r["_x"].get("content")
        if not c:
            continue
        words += [{"URL": r["URL"], **w} for w in c["words"].to_dict("records")]
        phrases += [{"URL": r["URL"], **p} for p in c["phrases"].to_dict("records")]
        heads += [{"URL": r["URL"], **h} for h in c["headings"]]
    sheets = [("Pages", df), ("Top words", pd.DataFrame(words, columns=["URL", "Word", "Uses", "Density (%)"])),
              ("Top phrases", pd.DataFrame(phrases, columns=["URL", "Phrase", "Words", "Uses"])),
              ("Headings", pd.DataFrame(heads, columns=["URL", "Level", "Heading"]))]
    return checks.simple_excel("Content check", info, content_numbers(df), sheets)


def text_excel(result: dict) -> bytes:
    read = result["read"]
    read_df = pd.DataFrame([{"Measure": k, "Value": "" if v is None else str(v)} for k, v in read.items()
                            if k not in ("examples", "status")])
    advice = pd.DataFrame([{"To improve": a, "Advice": t} for a, t in result["advice"]], columns=["To improve", "Advice"])
    places = pd.DataFrame([{"Place": k, "Keyword": v} for k, v in result["places"].items()], columns=["Place", "Keyword"])
    sheets = [("To improve", advice), ("Readability", read_df), ("Top words", result["content"]["words"]),
              ("Top phrases", result["content"]["phrases"]),
              ("Headings", pd.DataFrame(result["headings"], columns=["Level", "Heading"])), ("Keyword", places),
              ("Long sentences", pd.DataFrame({"Sentence": read.get("examples", [])}))]
    info = {"Text": "Pasted text", "Keyword": result["keyword"] or "None"}
    return checks.simple_excel("Content check", info, result["content"]["numbers"], sheets)


# ==========================================================================
# 2. Schema check
# ==========================================================================
RESULT_RANK = {"Invalid JSON": 0, "Missing required fields": 1, "Missing recommended fields": 2, "OK": 3,
               "Not checked": 4}
SCHEMA_PAGE_COLS = ["URL", "Status Code", "Schema Types", "Schema Result", "Missing Required", "Missing Recommended",
                    "Invalid JSON-LD", "Note"]


def schema_summary(table: pd.DataFrame) -> dict:
    if table.empty:
        return {"Schema Result": "No schema", "Missing Required": "", "Missing Recommended": ""}
    worst = min(table["Result"], key=lambda r: RESULT_RANK.get(r, 5))
    req = [f"{t}: {m}" for t, m in zip(table["Type"], table["Missing Required"]) if m]
    rec = [f"{t}: {m}" for t, m in zip(table["Type"], table["Missing Recommended"]) if m]
    return {"Schema Result": worst, "Missing Required": "; ".join(req), "Missing Recommended": "; ".join(rec)}


def schema_hook() -> dict:
    """Page-check options that add the schema field check to every row."""
    def after(row: dict):
        x = row["_x"]
        try:
            if not x.get("parsed"):
                return
            d = page.page_details(row)
            table = page.schema_fields(d["schema_objects"], d["microdata"], d["schema_errors"])
            x["schema_table"] = table
            row.update(schema_summary(table))
        finally:
            _drop_html(x)
    return {"keep_html": True, "after": after}


def schema_tables(rows: list):
    """(pages table, one row per schema item, summary by type)."""
    pages, items = [], []
    for r in rows:
        x = r["_x"]
        rec = {c: r.get(c, "") for c in SCHEMA_PAGE_COLS}
        rec["Status Code"] = r["Final Status Code"] if r["Final Status Code"] is not None else ""
        if not x.get("parsed"):
            rec["Schema Result"] = "Not read"
            rec["Note"] = r["Fetch Error"] or f"Not an HTML page that answered 200 ({r['Final Status Code']})"
        pages.append(rec)
        table = x.get("schema_table")
        if table is not None:
            items += [{"URL": r["URL"], **i} for i in table.to_dict("records")]
    pages_df = pd.DataFrame(pages, columns=SCHEMA_PAGE_COLS)
    pages_df["Invalid JSON-LD"] = pd.to_numeric(pages_df["Invalid JSON-LD"].replace("", None),
                                                errors="coerce").round().astype("Int64")
    items_df = pd.DataFrame(items, columns=["URL", "Type", "Result", "Missing Required", "Missing Recommended", "Note"])
    by_type = []
    if not items_df.empty:
        for t, g in items_df.groupby("Type", sort=False):
            counts = g["Result"].value_counts()
            by_type.append({"Type": t, "Pages": g["URL"].nunique(), "OK": int(counts.get("OK", 0)),
                            "Missing required": int(counts.get("Missing required fields", 0)),
                            "Missing recommended": int(counts.get("Missing recommended fields", 0)),
                            "Not checked": int(counts.get("Not checked", 0)) + int(counts.get("Invalid JSON", 0))})
    type_df = pd.DataFrame(by_type, columns=["Type", "Pages", "OK", "Missing required", "Missing recommended", "Not checked"])
    return pages_df, items_df, type_df.sort_values("Pages", ascending=False).reset_index(drop=True)


def schema_numbers(pages_df: pd.DataFrame) -> dict:
    res = pages_df["Schema Result"]
    return {"URLs checked": len(pages_df), "With schema": int((~res.isin(["No schema", "Not read"])).sum()),
            "No schema": int((res == "No schema").sum()),
            "Missing required fields": int((res == "Missing required fields").sum()),
            "Invalid JSON-LD": int((pages_df["Invalid JSON-LD"].fillna(0) > 0).sum())}


def schema_excel(pages_df, items_df, type_df, info: dict) -> bytes:
    return checks.simple_excel("Schema check", info, schema_numbers(pages_df),
                               [("Pages", pages_df), ("Schema fields", items_df), ("Types", type_df)])


def _collect(data) -> list:
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("@graph"), list):
            out += [o for o in item["@graph"] if isinstance(o, dict)]
        elif isinstance(item, dict):
            out.append(item)
    return out


def _context_note(data) -> str:
    items = data if isinstance(data, list) else [data]
    missing = [i for i in items if isinstance(i, dict) and "schema.org" not in json.dumps(i.get("@context", ""))]
    return ('Add "@context": "https://schema.org" to each top-level item; without it the types may not be read as '
            "schema.org types.") if missing else ""


def _json_error(e: ValueError, label: str = "") -> str:
    if isinstance(e, json.JSONDecodeError):
        return f"{label}{e.msg} at line {e.lineno}, column {e.colno}. Look for a missing comma, quote or bracket there."
    return f"{label}{e}"


def check_code(text: str) -> dict:
    """Schema field check for pasted JSON-LD, a <script> block or a whole page's HTML."""
    raw = (text or "").strip()
    errors, notes, objects, micro = [], [], [], []
    if re.search(r"<script|<html|<head|<body|itemtype\s*=", raw, re.I):
        soup = BeautifulSoup(raw, "lxml")
        for i, txt in enumerate(core.jsonld_scripts(soup), 1):
            body = re.sub(r"^\s*(<!--|//\s*<!\[CDATA\[|<!\[CDATA\[)", "", txt or "")
            body = re.sub(r"(-->|//\s*\]\]>|\]\]>)\s*$", "", body).strip()
            if not body:
                continue
            try:
                data = json.loads(body, strict=False)
            except ValueError as e:
                errors.append(_json_error(e, f"JSON-LD block {i}: "))
                continue
            objects += _collect(data)
            note = _context_note(data)
            if note and note not in notes:
                notes.append(note)
        micro = core.uniq(core._short_type(t) for el in soup.find_all(attrs={"itemtype": True})
                          for t in str(el.get("itemtype")).split())
        if not objects and not micro and not errors:
            notes.append("No JSON-LD or Microdata was found in the pasted HTML.")
    else:
        try:
            data = json.loads(raw, strict=False)
            objects = _collect(data)
            note = _context_note(data)
            if note:
                notes.append(note)
        except ValueError as e:
            errors.append(_json_error(e))
    table = page.schema_fields(objects, micro, len(errors))
    return {"table": table, "errors": errors, "notes": notes, "items": len(objects) + len(micro)}


# ==========================================================================
# 3. Competitor comparison and the content brief
# ==========================================================================
_QUESTION_START = re.compile(r"^(what|how|why|when|where|which|who|whom|whose|can|could|do|does|did|is|are|was|were|"
                             r"should|will|would|may|has|have)\b", re.I)


def is_question(heading: str) -> bool:
    """A heading written as a question: ends with ?, or starts with a question word ("How to choose ...")
    but not a statement about the business ("What we do", "Why choose us")."""
    h = (heading or "").strip()
    if h.endswith("?"):
        return True
    if not _QUESTION_START.match(h):
        return False
    words = re.split(r"[\W_]+", h.lower())
    return len(words) > 2 and not any(w in ("we", "our", "us", "i") for w in words[1:3])


def _norm_heading(text: str) -> str:
    words = [checks._stem(w) for w in re.split(r"[\W_]+", (text or "").lower()) if w and not w.isdigit()]
    return " ".join(w for w in words if w not in page.STOP_WORDS)


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _round_to(value: float, step: int = 50) -> int:
    return int(step * round(float(value) / step))


def _faq_questions(audit: dict) -> list:
    out = []
    for obj in audit["details"]["schema_objects"]:
        types = page._as_list(obj.get("@type"))
        if "FAQPage" in types:
            for q in page._as_list(obj.get("mainEntity")):
                if isinstance(q, dict) and isinstance(q.get("name"), str):
                    out.append(core.clean(q["name"]))
    return out


MEDIAN_MEASURES = {"Title length", "Meta description length", "H2 headings", "Words (main content)", "Reading ease",
                   "Images", "Images missing alt", "Internal links", "External links", "Keyword uses"}


def compare_competitors(yours: dict, comps: list, keyword: str = "") -> dict:
    """Your page (or None, when planning a new page) next to the competitors."""
    pages = ([("Your page", yours)] if yours else []) + [(f"Competitor {i}", c) for i, c in enumerate(comps, 1)]
    metrics = [(label, page._metrics(a)) for label, a in pages]
    names = list(dict.fromkeys(k for _, m in metrics for k in m))
    comp_labels = [label for label, _ in pages if label != "Your page"]
    rows = []
    for n in names:
        rec = {"Measure": n, **{label: m.get(n, "Not scored" if n.endswith(" score") else "") for label, m in metrics}}
        values = [_num(rec[label]) for label in comp_labels] if n in MEDIAN_MEASURES else []
        rec["Competitor median"] = (f"{median(values):g}" if values and all(v is not None for v in values) else "")
        rows.append(rec)
    table = pd.DataFrame(rows)
    table = pd.concat([pd.DataFrame([{"Measure": "URL", **{label: a["url"] for label, a in pages}, "Competitor median": ""}]),
                       table], ignore_index=True)

    # ---- phrases: what competitors repeat (and your page does not use)
    used = {}
    for c in comps:
        words = c["content"].get("phrase_list") or c["content"]["word_list"]
        seen = set()
        for n in (2, 3):
            for phrase, count in page.top_phrases(words, n, limit=40):
                if phrase in seen:
                    continue
                seen.add(phrase)
                entry = used.setdefault(phrase, [0, 0])
                entry[0] += 1
                entry[1] += count
    need = 2 if len(comps) >= 2 else 1
    mine = " " + " ".join(yours["content"]["word_list"]) + " " if yours else ""
    gaps = sorted(((p, n, c) for p, (n, c) in used.items() if n >= need and (not yours or f" {p} " not in mine)),
                  key=lambda t: (-t[1], -t[2]))[:40]
    gap_df = pd.DataFrame([{"Phrase": p, "Competitors Using It": n, "Total Uses": c,
                            **({"On Your Page": "No"} if yours else {})} for p, n, c in gaps])
    if gap_df.empty:
        gap_df = pd.DataFrame(columns=["Phrase", "Competitors Using It", "Total Uses"])

    # ---- headings: every competitor H2 and H3, the H2s several competitors share, and questions
    all_heads, groups, questions = [], {}, []
    for label, a in pages:
        for h in a["details"]["headings"]:
            if h["Level"] in ("H2", "H3") and h["Heading"]:
                all_heads.append({"Page": label, "Level": h["Level"], "Heading": h["Heading"]})
            if label != "Your page" and h["Level"] == "H2" and h["Heading"]:
                key = _norm_heading(h["Heading"])
                if key:
                    g = groups.setdefault(key, {"Heading": h["Heading"], "pages": set()})
                    g["pages"].add(label)
            if label != "Your page" and h["Level"] in ("H2", "H3", "H4") and is_question(h["Heading"]):
                questions.append({"Question": h["Heading"], "Found On": label, "Where": f"{h['Level']} heading"})
        if label != "Your page":
            questions += [{"Question": q, "Found On": label, "Where": "FAQ schema"} for q in _faq_questions(a)]
    your_keys = {_norm_heading(h["Heading"]) for h in yours["details"]["headings"]} if yours else set()
    suggested_df = pd.DataFrame([{"Heading": g["Heading"], "Competitors Using It": len(g["pages"]),
                                  "Found On": ", ".join(sorted(g["pages"])),
                                  **({"On Your Page": "Yes" if k in your_keys else "No"} if yours else {})}
                                 for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["pages"]))])
    if suggested_df.empty:
        suggested_df = pd.DataFrame(columns=["Heading", "Competitors Using It", "Found On"])
    q_seen, q_rows = set(), []
    for q in questions:
        key = _norm_heading(q["Question"])
        if key and key not in q_seen:
            q_seen.add(key)
            q_rows.append(q)
    questions_df = pd.DataFrame(q_rows, columns=["Question", "Found On", "Where"])

    # ---- titles, metas and schema
    titles = pd.DataFrame([{"Page": label, "Title": a["row"]["Title"], "Title Length": a["row"]["Title Length"] or 0,
                            "Meta Description": a["row"]["Meta Description"], "Meta Length": a["row"]["Meta Length"] or 0,
                            **({"Keyword In Title": checks.keyword_match(keyword, a["row"]["Title"])} if keyword else {})}
                           for label, a in pages])
    schema_rows, comp_types = [], Counter()
    for label, a in pages:
        types = top_types(a)
        if label != "Your page":
            comp_types.update(set(types))
        schema_rows.append({"Page": label, "Schema Types": ", ".join(types) or "None",
                            "All Types (nested too)": a["row"]["Schema Types"] or ""})
    mine_types = set(top_types(yours)) if yours else set()
    schema_gap = [t for t, _ in comp_types.most_common() if t not in mine_types]

    # ---- targets from the competitors
    def comp_values(key):
        out = []
        for c in comps:
            v = c["row"].get(key) if key in c["row"] else None
            if v is not None and v is not pd.NA:
                out.append(float(v))
        return out
    words = [float(c["row"]["Word Count"] or 0) for c in comps if c["row"]["Word Count"]]
    if words:
        if len(words) >= 3:
            ordered = sorted(words)
            low, high = median(ordered), ordered[int(round(0.75 * (len(ordered) - 1)))]
        else:
            low, high = min(words), max(words)
        word_target = (_round_to(low), _round_to(max(high, low)))
    else:
        word_target = None
    ease = [c["readability"]["Reading ease"] for c in comps if c["readability"].get("Reading ease") is not None]
    targets = {
        "words": word_target,
        "h2": int(round(median(comp_values("H2 Count")))) if comp_values("H2 Count") else None,
        "images": int(round(median(comp_values("Images")))) if comp_values("Images") else None,
        "ease": round(median(ease), 1) if ease else None,
        "internal": int(round(median(comp_values("Internal Links")))) if comp_values("Internal Links") else None,
    }
    return {"table": table, "gaps": gap_df, "headings": pd.DataFrame(all_heads, columns=["Page", "Level", "Heading"]),
            "suggested": suggested_df, "questions": questions_df, "titles": titles,
            "schema": pd.DataFrame(schema_rows, columns=["Page", "Schema Types", "All Types (nested too)"]),
            "schema_gap": schema_gap,
            "targets": targets, "keyword": keyword, "has_yours": bool(yours),
            "pages": [(label, a["url"], a["row"]["Title"] or "", a["row"]["Final Status Code"]) for label, a in pages],
            "yours": _your_numbers(yours) if yours else None}


def top_types(audit: dict) -> list:
    """The main schema types of a page: the top-level JSON-LD items (and @graph items) and Microdata types,
    without the types nested inside them (Question, Answer, Offer ...)."""
    out = []
    for obj in audit["details"]["schema_objects"]:
        out += [core._short_type(t) for t in page._as_list(obj.get("@type")) if isinstance(t, str)]
    out += audit["details"]["microdata"]
    return core.uniq(out)


def _your_numbers(a: dict) -> dict:
    r = a["row"]
    return {"words": r["Word Count"] or 0, "h2": r["H2 Count"] or 0, "images": r["Images"] or 0,
            "ease": a["readability"].get("Reading ease"), "internal": r["Internal Links"] or 0,
            "score": a["score"]["score"], "grade": a["score"]["grade"]}


def targets_table(result: dict) -> pd.DataFrame:
    t, y = result["targets"], result["yours"]
    rows = []

    def add(measure, target, yours_value, comp_value):
        rows.append({"Measure": measure, "Aim For": target, **({"Your Page": yours_value} if y else {}),
                     "Competitors (median)": comp_value})
    if t["words"]:
        add("Words of main content", f"{t['words'][0]:,} to {t['words'][1]:,}", f"{y['words']:,}" if y else "",
            f"{t['words'][0]:,}")
    if t["h2"] is not None:
        add("H2 subheadings", f"About {max(t['h2'], 3)}", y["h2"] if y else "", t["h2"])
    if t["images"] is not None:
        add("Images", f"At least {max(t['images'], 1)}, with alt text", y["images"] if y else "", t["images"])
    add("Reading ease", f"{max(60, t['ease'] or 0):g} or higher" if t["ease"] is not None else "60 or higher",
        (y["ease"] if y and y["ease"] is not None else "-") if y else "", t["ease"] if t["ease"] is not None else "-")
    if t["internal"] is not None:
        add("Internal links", f"At least {max(t['internal'], 3)}", y["internal"] if y else "", t["internal"])
    add("Title", "Under about 60 characters (600px), keyword near the start", "", "")
    add("Meta description", "120 to 155 characters, with the keyword and a reason to click", "", "")
    return pd.DataFrame(rows)


def _field_guide(schema_type: str) -> str:
    key = page.SCHEMA_ALIASES.get(schema_type, schema_type)
    if key not in page.SCHEMA_RULES:
        if schema_type in page.LOCAL_BUSINESS_TYPES:
            key = "LocalBusiness"
        elif schema_type in page.ORGANIZATION_TYPES:
            key = "Organization"
        else:
            return ""
    required, one_of, recommended = page.SCHEMA_RULES[key]
    parts = []
    if required:
        parts.append("required: " + ", ".join(f.replace("|", " or ") for f in required))
    if one_of:
        parts.append("plus one of: " + ", ".join(one_of))
    if recommended:
        parts.append("recommended: " + ", ".join(f.replace("|", " or ") for f in recommended))
    return "; ".join(parts)


def build_brief(result: dict, brand: dict = None) -> bytes:
    """A content brief (Word) a writer can work from."""
    from docx import Document
    from docx.shared import Pt
    keyword = result["keyword"]
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10.5)
    report.apply_brand(doc, brand)
    doc.add_heading(f"Content brief: {keyword}" if keyword else "Content brief", level=0)
    n_comp = sum(1 for label, *_ in result["pages"] if label != "Your page")
    doc.add_paragraph().add_run(report.brand_line(brand) + f"Based on {n_comp} competing page{'s' if n_comp != 1 else ''}. "
                                f"Prepared on {date.today().strftime('%d %B %Y')}.").italic = True

    doc.add_heading("Summary", level=1)
    t, y = result["targets"], result["yours"]
    lines = []
    if t["words"]:
        lines.append(f"Competitors use {t['words'][0]:,} words of main content (median); aim for {t['words'][0]:,} to "
                     f"{t['words'][1]:,} words that fully answer the search.")
    if y:
        lines.append(f"Your page scores {y['score']} out of 100 (grade {y['grade']}) and has {y['words']:,} words.")
        if t["words"] and y["words"] < t["words"][0]:
            lines.append(f"It is about {t['words'][0] - y['words']:,} words shorter than the competitors' median.")
    if len(result["gaps"]):
        lines.append(f"{len(result['gaps'])} phrases the competitors repeat are listed below as topics to cover.")
    if result["schema_gap"]:
        lines.append("Competitors use schema your page " + ("lacks" if y else "should consider") + ": "
                     + ", ".join(result["schema_gap"]) + ".")
    for line in lines:
        doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("Targets", level=1)
    tt = targets_table(result)
    report._table(doc, list(tt.columns), tt.values.tolist())

    doc.add_heading("Suggested H2 headings", level=1)
    sug = result["suggested"]
    if sug.empty:
        doc.add_paragraph("The competitors have no H2 headings to learn from. Plan sections around what, why, how, "
                          "cost, examples and common questions.")
    else:
        doc.add_paragraph("Headings the competitors use, the most shared first. Rewrite them in your own words and "
                          "keep only the ones that fit your page.")
        for g in sug.head(15).to_dict("records"):
            n = g["Competitors Using It"]
            doc.add_paragraph(f"{g['Heading']}  (used by {n} competitor{'s' if n != 1 else ''})", style="List Bullet")

    doc.add_heading("Questions to answer", level=1)
    qs = result["questions"]
    if qs.empty:
        doc.add_paragraph("No question headings or FAQ markup were found on the competing pages. Add a short FAQ "
                          "section with the questions your customers ask most.")
    else:
        doc.add_paragraph("Questions the competitors answer in headings or FAQ markup. Answer each in two to four sentences.")
        for q in qs.head(15)["Question"]:
            doc.add_paragraph(q, style="List Bullet")

    doc.add_heading("Phrases and topics to cover", level=1)
    if result["gaps"].empty:
        doc.add_paragraph("No phrase is repeated across the competitors" + (" that your page does not already use." if y else "."))
    else:
        doc.add_paragraph("Two and three word phrases the competitors repeat" + (" and your page does not use" if y else "")
                          + ". Use the ones that fit naturally; do not force them in.")
        gaps = result["gaps"][["Phrase", "Competitors Using It", "Total Uses"]].head(25)
        report._table(doc, ["Phrase", "Competitors using it", "Total uses"], gaps.values.tolist())

    doc.add_heading("Schema to add", level=1)
    types = result["schema_gap"] or []
    if not types:
        doc.add_paragraph("The competitors use no schema types that " + ("your page lacks." if y else "need adding.")
                          + " At least add Organization (homepage) or the type that matches the page (Service, Product, "
                            "Article, LocalBusiness).")
    else:
        for st_ in types:
            guide = _field_guide(st_)
            doc.add_paragraph(f"{st_}" + (f": {guide}" if guide else ""), style="List Bullet")
        doc.add_paragraph("Test the markup with Google's Rich Results Test before publishing.")

    doc.add_heading("Competitor titles and meta descriptions", level=1)
    titles = result["titles"]
    report._table(doc, ["Page", "Title", "Meta description"],
                  titles[["Page", "Title", "Meta Description"]].values.tolist())

    if y:
        doc.add_heading("Your page compared", level=1)
        table = result["table"]
        table = table[table["Measure"] != "URL"]
        report._table(doc, list(table.columns), table.values.tolist())

    doc.add_heading("Pages analysed", level=1)
    for label, url, title, status in result["pages"]:
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(f"{label}: ")
        name = title or report.url_label(url, "")
        try:
            host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])
        except Exception:
            host = ""
        report._link(p, url, f"{name} ({host})" if host else name)
        if status != 200:
            p.add_run(f"  (answered {status if status is not None else 'nothing'})")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def competitor_excel(result: dict, info: dict) -> bytes:
    numbers = {"Pages compared": len(result["pages"])}
    t = result["targets"]
    if t["words"]:
        numbers["Words to aim for"] = f"{t['words'][0]:,} to {t['words'][1]:,}"
    sheets = [("Comparison", result["table"]), ("Targets", targets_table(result)), ("Phrases to cover", result["gaps"]),
              ("Suggested H2s", result["suggested"]), ("All headings", result["headings"]),
              ("Questions", result["questions"]), ("Titles and metas", result["titles"]), ("Schema", result["schema"])]
    return checks.simple_excel("Competitor comparison", info, numbers, sheets)


# ==========================================================================
# 4. Internal link opportunities
# ==========================================================================
def phrase_pattern(keyword: str):
    """Regex for a keyword phrase: any case, flexible spaces and hyphens, singular or plural last word."""
    tokens = [t for t in re.split(r"[\W_]+", (keyword or "").lower()) if t]
    if not tokens:
        return None
    parts = []
    for i, t in enumerate(tokens):
        if i == len(tokens) - 1:
            stem = t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t
            parts.append(re.escape(stem) + r"(?:s|es)?")
        else:
            parts.append(re.escape(t))
    return re.compile(r"(?<![\w])" + r"[\s\-]+".join(parts) + r"(?![\w])", re.I)


def _sentences(text: str) -> list:
    out = []
    for block in (text or "").split(core.BLOCK_MARK):
        block = core.clean(block)
        if block:
            out += [s.strip() for s in page._SENTENCE_END.split(block) if s.strip()]
    return out


def _excerpt(sentence: str, start: int, end: int, width: int = 220) -> str:
    if len(sentence) <= width:
        return sentence
    left = max(0, start - (width - (end - start)) // 2)
    right = min(len(sentence), left + width)
    left = max(0, right - width)
    return ("..." if left else "") + sentence[left:right].strip() + ("..." if right < len(sentence) else "")


def find_mentions(text: str, patterns: list, limit: int = MAX_MENTIONS_PER_PAGE, skip: set = None) -> list:
    """[(keyword, text as written on the page, sentence excerpt), ...]

    skip  lower-case texts to leave out (the page's H1: a link belongs in the body text, not the main heading)"""
    out = []
    for sentence in _sentences(text):
        if skip and sentence.lower() in skip:
            continue
        for keyword, pat in patterns:
            m = pat.search(sentence)
            if m:
                out.append((keyword, m.group(0), _excerpt(sentence, m.start(), m.end())))
                break
        if len(out) >= limit:
            break
    return out


def link_key(url: str) -> str:
    """A URL in the form used to match links to the target (trailing slash ignored)."""
    return core.norm_url(url).rstrip("/")


def content_links(html: bytes, base_url: str) -> list:
    """[(absolute URL, anchor text)] of the links inside the main content (not menus, header, footer)."""
    soup = BeautifulSoup(html, "lxml")
    scope, _ = core.main_scope(soup)
    out = []
    if scope is None:
        return out
    for a in scope.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            out.append((urljoin(base_url, href), core.clean(a.get_text(" ")) or core.clean(a.get("aria-label") or "")))
        except ValueError:
            continue
    return out


def link_hook(target_keys: set, keywords: list) -> dict:
    """Page-check options that look for keyword mentions and links to the target on every row.

    target_keys  link_key() forms of the target page's URL (as entered and where it lands)"""
    patterns = [(k, p) for k, p in ((k, phrase_pattern(k)) for k in keywords) if p is not None]

    def after(row: dict):
        x = row["_x"]
        try:
            links = x.get("links", [])
            anywhere = [anchor or "(no anchor text)" for url, anchor, _ in links if link_key(url) in target_keys]
            in_content = []
            if x.get("parsed") and x.get("html"):
                base = row["Final URL"] or row["URL"]
                in_content = [anchor or "(no anchor text)" for url, anchor in content_links(x["html"], base)
                              if link_key(url) in target_keys]
            row["Links To Target"] = len(anywhere)
            row["In-Content Links To Target"] = len(in_content)
            row["Anchor Texts Used"] = " | ".join(core.uniq(anywhere))[:500]
            x["anchors"] = in_content or anywhere
            skip = {h.lower() for h in (row["H1"], row["All H1s"]) if h}
            mentions = (find_mentions(x.get("main_text_marked") or x.get("main_text", ""), patterns, skip=skip)
                        if x.get("parsed") else [])
            row["Mentions"] = len(mentions)
            if mentions:
                row["Keyword Found"], row["Anchor Text To Use"], row["Sentence"] = mentions[0]
            x["mentions"] = mentions
        finally:
            _drop_html(x, "links", "main_text", "intro_text", "h2s")
    return {"links": True, "text": True, "keep_html": True, "after": after}


def link_tables(rows: list):
    """(opportunities, pages that already link, anchor texts used, every page scanned).

    A page that links to the target only from its menu, header or footer is still an opportunity:
    a link inside the content, on relevant words, carries more weight."""
    opps, linking, scanned, anchors = [], [], [], Counter()
    for r in rows:
        ok = r["_x"].get("parsed") and r["Final Status Code"] == 200
        links_to, in_content = r.get("Links To Target") or 0, r.get("In-Content Links To Target") or 0
        scanned.append({"Page": r["URL"], "Status": r["Final Status Code"] if r["Final Status Code"] is not None else r["Fetch Error"],
                        "Indexable": r["Indexable"], "Mentions": r.get("Mentions") or 0, "Links To Target": links_to,
                        "In-Content Links": in_content, "Title": r["Title"]})
        if links_to:
            linking.append({"Page": r["URL"], "Links To Target": links_to, "In-Content Links": in_content,
                            "Anchor Texts Used": r.get("Anchor Texts Used", ""), "Indexable": r["Indexable"]})
            anchors.update(r["_x"].get("anchors", []))
        if ok and r.get("Mentions") and not in_content:
            for kw, found, sentence in r["_x"].get("mentions", [])[:3]:
                opps.append({"Page": r["URL"], "Indexable": r["Indexable"], "Keyword": kw, "Anchor Text To Use": found,
                             "Sentence To Link From": sentence, "Mentions On Page": r["Mentions"],
                             "Links From Menu Or Footer": "Yes" if links_to else "No", "Page Title": r["Title"]})
    opp_df = pd.DataFrame(opps, columns=["Page", "Indexable", "Keyword", "Anchor Text To Use", "Sentence To Link From",
                                         "Mentions On Page", "Links From Menu Or Footer", "Page Title"])
    if not opp_df.empty:
        opp_df["_rank"] = (opp_df["Indexable"] != "Yes").astype(int)
        opp_df = opp_df.sort_values(["_rank", "Mentions On Page", "Page"], ascending=[True, False, True]).drop(columns="_rank")
    return (opp_df.reset_index(drop=True),
            pd.DataFrame(linking, columns=["Page", "Links To Target", "In-Content Links", "Anchor Texts Used", "Indexable"]),
            pd.DataFrame([{"Anchor Text": a, "Links": n} for a, n in anchors.most_common()], columns=["Anchor Text", "Links"]),
            pd.DataFrame(scanned, columns=["Page", "Status", "Indexable", "Mentions", "Links To Target", "In-Content Links",
                                           "Title"]))


def link_numbers(opp_df, linking_df, scanned_df) -> dict:
    return {"Pages scanned": len(scanned_df),
            "Link from the content": int((linking_df["In-Content Links"] > 0).sum()) if len(linking_df) else 0,
            "Link from menus only": int((linking_df["In-Content Links"] == 0).sum()) if len(linking_df) else 0,
            "Pages with an opportunity": int(opp_df["Page"].nunique()) if len(opp_df) else 0,
            "Could not be read": int((~scanned_df["Status"].astype(str).isin(["200"])).sum())}


def links_excel(opp_df, linking_df, anchor_df, scanned_df, info: dict) -> bytes:
    return checks.simple_excel("Internal link opportunities", info, link_numbers(opp_df, linking_df, scanned_df),
                               [("Opportunities", opp_df), ("Already linking", linking_df),
                                ("Anchor texts", anchor_df), ("All pages scanned", scanned_df)])
