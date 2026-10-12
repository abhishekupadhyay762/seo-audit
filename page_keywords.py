"""
Keyword check - for each URL and its target keyword, where the keyword appears on the page.
The matching rules are in seo_checks.py; the results view is in seo_ui.py.
"""

import time

import streamlit as st

import seo_checks as checks
import seo_core as core
import seo_report as report
import seo_ui as ui

DESCRIPTION = (
    "Give each URL its target keyword. The check shows where the keyword appears on the page, how often, and "
    "which URLs compete for the same keyword."
)
COVERS = [
    ("Title and H1", "Whether the keyword appears as a phrase, only as separate words, or not at all."),
    ("Meta description and URL", "Whether the snippet text and the address contain the keyword."),
    ("First 100 words and H2s", "Whether the opening of the content and the subheadings mention it."),
    ("Count and density", "How often the exact phrase appears in the main content, and its share of the words."),
    ("Competing pages", "The same keyword given to more than one URL, a sign of keyword cannibalisation."),
    ("Full on-page data", "Status, indexability, title, meta, headings and every other check for each URL."),
]
EXAMPLE = "https://example.com/seo-services, seo services\nhttps://example.com/local-seo, local seo agency"


def report_sections(df):
    def build():
        rows = [[report.url_label(r["URL"]), r["Target Keyword"], r["Keyword Score"], r["In Title"], r["In H1"],
                 r["In Meta Description"], r["In URL"], r["In First 100 Words"]] for r in df.head(100).to_dict("records")]
        return [{"title": "Keyword placement", "intro": "Yes means the phrase appears; Partial means every word "
                 "appears but not together. The score counts the five main places.",
                 "header": ["Page", "Keyword", "Score", "Title", "H1", "Meta", "URL", "First 100 words"], "rows": rows}]
    return build


def main():
    settings = ui.crawl_settings(default_max=1_000, limit=20_000)
    ui.page_header("keyword-check", "Keyword check", DESCRIPTION)

    with st.container(key="deck_keywords"):
        c1, c2 = st.columns([3, 2])
        text = c1.text_area("URL and target keyword, one pair per line", height=170, placeholder=EXAMPLE,
                            help="Separate the URL and the keyword with a comma, a tab or a | sign.")
        file = c2.file_uploader("Or upload a file", type=["csv", "txt", "xlsx", "xls"],
                                help="CSV or XLSX with the URL in the first column and the keyword in the second.")
        go = st.button("Check keywords", type="primary")

    if go:
        try:
            pairs = checks.parse_pairs(text, file)
        except Exception as e:
            st.error(f"The uploaded file could not be read: {e}")
            pairs = []
        pairs = [(u, k) for u, k in pairs if k][: settings["max_urls"]]
        if not pairs:
            st.warning("Add at least one line with a URL and a keyword, for example: https://example.com/page, my keyword")
        else:
            urls = list(dict.fromkeys(u for u, _ in pairs))
            session = core.make_session(settings["workers"], settings["user_agent"])
            fetched = {}
            ui.run_checks(urls, settings, fetched, core.RobotsCache(), {"text": True}, session)
            by_url = {r["URL"]: r for r in fetched.values()}
            results = {}
            for i, (url, keyword) in enumerate(pairs):
                row = dict(by_url[url])
                row["Target Keyword"] = keyword
                results[i] = row
            state = st.session_state
            state["kw_results"] = results
            state["kw_run_id"] = time.time()
            state["kw_total"] = len(pairs)
            state["kw_info"] = ui.run_info(settings)
            state.pop("kw_final", None)

    if not st.session_state.get("kw_results"):
        ui.covers("What the check covers", COVERS)
        return
    df = ui.results_table("kw", core.KEYWORD_GROUPS, checks.keyword_extra)
    st.caption("Yes means the phrase appears (singular and plural count as the same). Partial means every word "
               "appears, but not together. The score counts title, H1, meta description, URL and first 100 words.")
    ui.render_results(df, "kw", core.KEYWORD_GROUPS, core.KEYWORD_OVERVIEW_COLS, st.session_state.get("kw_info", {}),
                      "keyword-check", "Keyword check", report_sections=report_sections(df))


if __name__ == "__main__":
    main()
