"""
Page audit - a full on-page audit of one URL, with a score out of 100.

Optional: a target keyword, up to three competitor URLs, and a smartphone versus desktop comparison.
The checks and the score are in seo_page.py; the shared look is in seo_ui.py.
"""

import re
import time
from urllib.parse import quote, urlsplit

import pandas as pd
import streamlit as st

import seo_core as core
import seo_page as page
import seo_ui as ui

DESCRIPTION = (
    "Enter one URL for a full on-page audit and a score out of 100. Add a target keyword and competitor URLs "
    "to see where the page falls short."
)
COVERS = [
    ("On-page score", "A score out of 100 from weighted checks in seven areas (eight with a keyword), with the points "
                      "behind every check."),
    ("What to fix first", "Every failed check, ordered by how many points the fix adds, with how to fix it."),
    ("Search result preview", "How the title and description may be cut in Google on desktop and mobile."),
    ("Readability", "Reading ease, sentence and paragraph length, and the longest sentences to rewrite."),
    ("Content analysis", "Word count, most used words and phrases, keyword use and the heading outline."),
    ("Schema field check", "Each schema type checked for the fields Google needs for rich results."),
    ("Smartphone versus desktop", "Fetches the page as a phone and as a desktop and shows what differs."),
    ("Competitor comparison", "Your page next to up to three competitors, with the phrases and schema they use and you do not."),
]
MOBILE_MODES = {"As Chrome browsers": "chrome", "As Googlebot": "googlebot", "Off": ""}
RESULT_ICON = {"Pass": "✅ Pass", "Warning": "⚠️ Warning", "Fail": "❌ Fail", "Info": "ℹ️ Info"}
SCHEMA_ICON = {"OK": "✅ OK", "Missing required fields": "❌ Missing required fields",
               "Missing recommended fields": "⚠️ Missing recommended fields"}
LINK = st.column_config.LinkColumn


def file_stem(url: str) -> str:
    try:
        p = urlsplit(url)
        name = p.netloc + p.path
    except ValueError:
        name = url
    return "page-audit-" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "page")


def table_height(n: int, most: int = 420) -> int:
    return min(38 + 35 * max(n, 1), most)


# --------------------------------------------------------------------------
# Running the audit
# --------------------------------------------------------------------------
def run(url: str, keyword: str, competitors: list, settings: dict, check_links: bool, check_targets: bool, mobile: str):
    session = core.make_session(settings["workers"], settings["user_agent"])
    pages = [url] + competitors
    with st.status(f"Auditing {url}", expanded=True) as status:
        audits = []
        for i, target in enumerate(pages):
            who = "your page" if i == 0 else f"competitor {i} of {len(competitors)}"
            line = st.empty()

            def step(text, who=who):
                line.caption(f"{who.capitalize()}: {text}...")
            try:
                audits.append(page.audit_page(session, target, settings, keyword, check_links, check_targets,
                                              mobile, on_step=step))
            except Exception as e:  # one failing competitor must not lose the whole run
                if i == 0:
                    status.update(label="The audit could not finish", state="error")
                    st.error(f"The page could not be audited: {e}")
                    return
                st.warning(f"Competitor {target} was skipped: {e}")
            line.empty()
        comparison = page.compare_pages(audits[0], audits[1:]) if len(audits) > 1 else None
        status.update(label="Audit complete", state="complete", expanded=False)

    state = st.session_state
    state["pa_audit"], state["pa_comps"], state["pa_cmp"] = audits[0], audits[1:], comparison
    state["pa_id"] = time.time()
    state["pa_info"] = {**ui.run_info(settings), "mobile": mobile}


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------
def top_fixes(checklist: pd.DataFrame) -> pd.DataFrame:
    todo = checklist[checklist["Result"].isin(["Fail", "Warning"])].copy()
    todo["Points To Gain"] = (todo["Out Of"] - todo["Points"]).round(1)
    return todo.sort_values("Points To Gain", ascending=False)[["Check", "Points To Gain", "Found", "How To Fix", "Area"]]


def checklist_tab(s: dict, run_id):
    table = s["checklist"]
    problems = table["Result"].isin(["Fail", "Warning"])
    labels = {"problems": f"Problems only ({int(problems.sum())})", "all": f"All checks ({len(table)})"}
    show = st.radio("Show", list(labels), format_func=labels.get, horizontal=True, key=f"pa_check_show_{run_id}")
    view = table[problems] if show == "problems" else table
    if view.empty:
        st.success("Every scored check passed.")
        return
    view = view.assign(Result=view["Result"].map(RESULT_ICON),
                       Points=[f"{p:g} / {o:g}" if o else "Not scored" for p, o in zip(view["Points"], view["Out Of"])])
    st.dataframe(view[["Area", "Check", "Result", "Found", "Points", "How To Fix"]], width="stretch", hide_index=True,
                 height=table_height(len(view), 560),
                 column_config={"Found": st.column_config.TextColumn(width="medium"),
                                "How To Fix": st.column_config.TextColumn(width="large")})
    st.caption("Info rows are shown for context and do not count toward the score.")


def content_tab(audit: dict):
    ui.content_view(audit["readability"], audit["content"], audit["details"]["headings"])


def images_tab(audit: dict):
    imgs = pd.DataFrame(audit["details"]["images"], columns=["Image", "Alt", "Alt Text", "Width", "Height", "Loading"])
    if imgs.empty:
        st.info("No images were found in the page HTML. Images added later by JavaScript are not seen.")
        return
    ui.cards({"Images": len(imgs), "Alt missing": int((imgs["Alt"] == "Missing").sum()),
              "Alt empty": int((imgs["Alt"] == "Empty").sum()),
              "No width or height": int(((imgs["Width"] == "") | (imgs["Height"] == "")).sum()),
              "Lazy loaded": int((imgs["Loading"] == "lazy").sum())})
    only = st.checkbox("Only images with a problem", key="pa_img_only")
    if only:
        imgs = imgs[(imgs["Alt"] != "OK") | (imgs["Width"] == "") | (imgs["Height"] == "")]
    st.dataframe(imgs, width="stretch", hide_index=True, height=table_height(len(imgs)),
                 column_config={"Image": LINK("Image", width="large")})
    st.caption("Empty alt text is right for decorative images. Images that carry meaning need a short description.")


def schema_tab(audit: dict):
    schema, details, url = audit["schema"], audit["details"], audit["row"]["Final URL"] or audit["url"]
    if details["schema_errors"]:
        st.error(f"{details['schema_errors']} JSON-LD block(s) could not be read, so Google ignores them. "
                 "Check for a missing comma, quote or bracket.")
    if schema.empty:
        st.info("No schema markup was found on this page.")
    else:
        st.dataframe(schema.assign(Result=schema["Result"].map(lambda r: SCHEMA_ICON.get(r, r))), width="stretch",
                     hide_index=True, height=table_height(len(schema)),
                     column_config={"Note": st.column_config.TextColumn(width="large")})
        st.caption("Required fields decide whether the type can show as a rich result. Recommended fields add detail. "
                   "The rules follow Google's structured data documentation; confirm with Google's own test.")
    row = st.container(horizontal=True)
    row.link_button("Test in Google's Rich Results Test", f"https://search.google.com/test/rich-results?url={quote(url, safe='')}")
    row.link_button("Open in the Schema Markup Validator", f"https://validator.schema.org/#url={quote(url, safe='')}")


def mobile_tab(audit: dict, info: dict):
    mobile = audit["mobile"]
    if mobile is None:
        st.info("The comparison was turned off for this run, or the page did not answer.")
        return
    diff = mobile[mobile["Same"] == "No"]
    if diff.empty:
        st.success("The smartphone and desktop versions match on every field compared.")
    else:
        st.warning("Different on smartphone and desktop: " + ", ".join(diff["Field"]) + ". Google indexes the "
                   "smartphone version, so anything missing there is missing for Google.")
    if audit.get("mobile_note"):
        st.warning(audit["mobile_note"])
    st.dataframe(mobile.assign(Same=mobile["Same"].map({"Yes": "✅ Yes", "No": "❌ No"})), width="stretch",
                 hide_index=True, height=table_height(len(mobile), 560))
    how = {"googlebot": "Fetched as Googlebot Smartphone and Googlebot Desktop. ",
           "chrome": "Fetched as Chrome on a phone and Chrome on a desktop. "}.get(info.get("mobile"), "")
    st.caption(how + "Word count, links and images count as the same when they are within 10% of each other. "
               "Content added by JavaScript is not seen.")


def competitors_tab(cmp: dict, comps: list):
    st.dataframe(cmp["table"], width="stretch", hide_index=True, height=table_height(len(cmp["table"]), 700),
                 column_config={"Measure": st.column_config.TextColumn(pinned=True)})
    st.caption("Competitors were audited with the same options as your page, so the scores compare directly.")
    st.markdown("**Phrases competitors use that your page does not**")
    if cmp["gaps"].empty:
        st.success("Your page already uses the phrases the competitors repeat.")
    else:
        need = "at least two competitors" if len(comps) >= 2 else "the competitor"
        st.caption(f"Two and three word phrases that {need} use more than once. Use them where they fit the topic.")
        st.dataframe(cmp["gaps"], width="stretch", hide_index=True, height=table_height(len(cmp["gaps"]), 390))
    if cmp["schema_gap"]:
        st.info("Schema types competitors use that your page does not: " + ", ".join(cmp["schema_gap"]))
    st.markdown("**H2 headings on each page**")
    st.dataframe(cmp["h2s"], width="stretch", hide_index=True,
                 column_config={"URL": LINK("URL", width="medium"), "H2 Headings": st.column_config.TextColumn(width="large")})


def page_data_tab(audit: dict):
    df = audit["df"].drop(columns=["_issues"])
    data = pd.DataFrame({"Field": df.columns, "Value": ["" if pd.isna(v) else str(v) for v in df.iloc[0].tolist()]})
    st.dataframe(data, width="stretch", hide_index=True, height=560,
                 column_config={"Value": st.column_config.TextColumn(width="large")})
    headers = audit["details"]["headers"]
    if headers:
        with st.expander("Response headers"):
            st.dataframe(pd.DataFrame({"Header": list(headers), "Value": [str(v) for v in headers.values()]}),
                         width="stretch", hide_index=True)


def show_results(audit: dict, comps: list, cmp: dict, info: dict, run_id):
    s, row = audit["score"], audit["row"]
    url = audit["url"]
    final = row["Final URL"] or url
    note = f"Audited {url}"
    if core.norm_url(final) != core.norm_url(url):
        note += f", which redirects to {final}"
    if audit["keyword"]:
        note += f". Target keyword: {audit['keyword']}"
    st.caption(note + ".")

    ui.score_block(s["score"], s["grade"], s["counts"], s["areas"], bool(s["blockers"]), s.get("loaded", True))
    if not s.get("loaded", True):
        st.error("The page did not load, so only indexability was checked and the score is 0: "
                 + "; ".join(s["blockers"]) + ". Fix this first, then audit the page again.")
    elif s["blockers"]:
        st.error(f"These problems stop the page from ranking, so the score is capped at {page.BLOCKER_CAP}: "
                 + "; ".join(s["blockers"]) + ".")

    if s.get("loaded", True):
        fixes_and_preview(s, row)
    result_tabs(audit, comps, cmp, info, run_id)


def fixes_and_preview(s: dict, row: dict):
    st.subheader("What to fix first")
    fixes = top_fixes(s["checklist"])
    if fixes.empty:
        st.success("Every scored check passed.")
    else:
        st.dataframe(fixes.head(8), width="stretch", hide_index=True, height=table_height(min(len(fixes), 8)),
                     column_config={"Found": st.column_config.TextColumn(width="medium"),
                                    "How To Fix": st.column_config.TextColumn(width="large"),
                                    "Points To Gain": st.column_config.NumberColumn(format="+%.1f")})
        if len(fixes) > 8:
            st.caption(f"The 8 biggest of {len(fixes)} fixes. The Checklist tab below has all of them.")

    st.subheader("How the page may look in Google")
    prev = page.serp_preview(row)
    ui.serp_block(prev)
    cut = [name for name, flag in (("title", prev["title_cut"]), ("meta description", prev["desc_cut"])) if flag]
    st.caption(("The " + " and ".join(cut) + " is likely to be cut on desktop. " if cut else "")
               + "An estimate from the width Google usually shows; Google may also rewrite titles and descriptions.")


def result_tabs(audit: dict, comps: list, cmp: dict, info: dict, run_id):
    s, url = audit["score"], audit["url"]
    loaded = s.get("loaded", True)
    names = ["Checklist", "Content", "Links", "Images", "Schema", "Smartphone vs desktop"] if loaded else ["Checklist"]
    if cmp:
        names.append(f"Competitors ({len(comps)})")
    names.append("Page data")
    tabs = dict(zip(names, st.tabs(names)))
    with tabs["Checklist"]:
        checklist_tab(s, run_id)
    if loaded:
        with tabs["Content"]:
            content_tab(audit)
        with tabs["Links"]:
            if audit["links"] is None:
                st.info("Link checking was turned off for this run.")
            else:
                ui.links_view(audit["links"], "pa", file_stem(url), {"Page": url})
        with tabs["Images"]:
            images_tab(audit)
        with tabs["Schema"]:
            schema_tab(audit)
        with tabs["Smartphone vs desktop"]:
            mobile_tab(audit, info)
    if cmp:
        with tabs[f"Competitors ({len(comps)})"]:
            competitors_tab(cmp, comps)
    with tabs["Page data"]:
        page_data_tab(audit)

    # Downloads: the data is captured here, so the file builders never read session state
    stem = file_stem(url)
    buttons = st.container(horizontal=True)
    brand = ui.branding()
    ui.download(buttons, "⬇ Download page report (Word)", lambda: page.build_page_report(audit, cmp, brand),
                f"{stem}-report.docx", ui.DOCX_MIME, "pa_docx", run_id, heavy=True)
    ui.download(buttons, "⬇ Download Excel", lambda: page.page_excel_bytes(audit, cmp),
                f"{stem}.xlsx", core.XLSX_MIME, "pa_xlsx", run_id, heavy=True)
    st.caption("The Word report opens in Google Docs and Word; the Excel file opens in Google Sheets and Excel.")


# --------------------------------------------------------------------------
# Screen
# --------------------------------------------------------------------------
def main():
    settings = ui.crawl_settings(show_max=False)
    ui.page_header("page-audit", "Page audit", DESCRIPTION)

    with st.container(key="deck_page"):
        c1, c2 = st.columns([3, 2])
        raw_url = c1.text_input("Page URL", placeholder="https://example.com/services/seo")
        keyword = c2.text_input("Target keyword (optional)", placeholder="seo services",
                                help="Adds keyword checks to the score: title, H1, meta description, URL, "
                                     "first 100 words and how often it is used.")
        raw_comps = st.text_area(f"Competitor URLs (optional, up to {page.MAX_COMPETITORS}, one per line)", height=95,
                                 placeholder="https://competitor-one.com/seo-services\nhttps://competitor-two.com/seo",
                                 help="Pages that rank for the same keyword. Each one is audited the same way.")
        o1, o2, o3 = st.columns(3)
        check_links = o1.checkbox("Check every link on the page", value=True,
                                  help="Finds broken links and internal links that redirect.")
        check_targets = o2.checkbox("Check canonical and hreflang targets", value=True,
                                    help="Requests the canonical URL and each hreflang alternate.")
        mobile_label = o3.selectbox(
            "Compare smartphone and desktop", list(MOBILE_MODES),
            help="Fetches the page twice, as a phone and as a desktop. Many sites block requests that claim to be "
                 "Googlebot, so start with Chrome.")
        go = st.button("Audit page", type="primary")

    if go:
        url = core.normalize_url(raw_url) if core.looks_like_url(raw_url) else ""
        if not url:
            st.warning("Enter the full address of one page, for example https://example.com/services/seo")
        else:
            comps = []
            for line in raw_comps.splitlines():
                c = core.normalize_url(line) if core.looks_like_url(line) else ""
                if c and core.norm_url(c) != core.norm_url(url) and c not in comps:
                    comps.append(c)
            if len(comps) > page.MAX_COMPETITORS:
                st.info(f"Only the first {page.MAX_COMPETITORS} competitor URLs are audited.")
                comps = comps[: page.MAX_COMPETITORS]
            run(url, keyword.strip(), comps, settings, check_links, check_targets, MOBILE_MODES[mobile_label])

    state = st.session_state
    if not state.get("pa_audit"):
        ui.covers("What the audit covers", COVERS)
        return
    show_results(state["pa_audit"], state.get("pa_comps", []), state.get("pa_cmp"), state.get("pa_info", {}),
                 state.get("pa_id"))


if __name__ == "__main__":
    main()
