"""
Content check - readability and content analysis for a pasted draft or for many live pages.
The checks are in seo_content.py and seo_page.py; the shared look is in seo_ui.py.
"""

import time

import streamlit as st

import seo_checks as checks
import seo_content as content
import seo_core as core
import seo_ui as ui

DESCRIPTION = (
    "Paste a draft to check it before it goes live, or check many live pages at once: reading ease, sentence and "
    "paragraph length, most used words and phrases, keyword use and what to improve."
)
COVERS = [
    ("What to improve", "Plain advice on length, readability, long sentences and paragraphs, subheadings and keyword use."),
    ("Readability", "Flesch reading ease, average sentence length, long sentences and long paragraphs."),
    ("Most used words and phrases", "The words and two and three word phrases the text repeats most, with density."),
    ("Keyword use", "Uses and density of the target keyword, and whether it is in the opening and in a heading."),
    ("Heading outline", "The headings of the page, or the heading lines of the pasted draft."),
    ("Many pages at once", "One row per URL, so you can sort a whole section by reading ease or word count."),
]
MODES = ["Pasted text", "Live pages"]
LINK = st.column_config.LinkColumn


def text_results(result: dict):
    st.subheader("What to improve")
    ui.advice_list(result["advice"], "No problems found: length, readability and keyword use all look fine.")
    if result["places"]:
        st.caption("Keyword: " + ", ".join(f"{k.lower()}: {v}" for k, v in result["places"].items())
                   + ". Yes means the exact phrase; Partial means every word, but not together.")
    ui.content_view(result["read"], result["content"], result["headings"],
                    "No heading lines found. Start a line with # or ## to mark it as a heading.")
    st.caption("A short line without a full stop is read as a heading (shown as Heading?), and lines that start with "
               "a bullet or a number as list items.")
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download Excel", lambda: content.text_excel(result), "content-check-text.xlsx", core.XLSX_MIME,
                "ct_text_xlsx", st.session_state.get("ct_text_id"), heavy=True)


def page_results():
    state = st.session_state
    rows = [state["ct_results"][i] for i in sorted(state["ct_results"])]
    df = content.content_table(rows)
    ui.cards(content.content_numbers(df))
    st.dataframe(df, width="stretch", hide_index=True, height=ui.table_height(len(df), 460),
                 column_config={"URL": LINK("URL", pinned=True, width="medium"),
                                "Reading Ease": st.column_config.NumberColumn(format="%.1f"),
                                "To Improve": st.column_config.TextColumn(width="large")})
    st.caption(f"Reading ease below {content.HARD_TO_READ} is hard for most readers. Thin means under "
               f"{content.THIN_WORDS} words of main content. Menus, headers and footers are left out of the counts.")

    read_rows = [r for r in rows if r["_x"].get("content")]
    if read_rows:
        st.subheader("One page in detail")
        pick = st.selectbox("Page", [r["URL"] for r in read_rows], key=f"ct_pick_{state.get('ct_run_id')}")
        r = next(r for r in read_rows if r["URL"] == pick)
        c = r["_x"]["content"]
        ui.advice_list(c["advice"], "No problems found on this page.")
        ui.content_view(c["read"], c, c["headings"])

    info = state.get("ct_info", {})
    row = st.container(horizontal=True)
    run_id = state.get("ct_run_id")
    ui.download(row, "⬇ Download CSV", lambda: core.to_csv_bytes(df), "content-check.csv", "text/csv", "ct_csv", run_id)
    ui.download(row, "⬇ Download Excel", lambda: content.content_excel(df, rows, info), "content-check.xlsx",
                core.XLSX_MIME, "ct_xlsx", run_id, heavy=True)


def main():
    settings = ui.crawl_settings(default_max=500, limit=5_000)
    ui.page_header("content-check", "Content check", DESCRIPTION)
    state = st.session_state

    with st.container(key="deck_content"):
        mode = st.segmented_control("Check", MODES, default=MODES[0], key="ct_mode") or MODES[0]
        if mode == MODES[0]:
            text = st.text_area("Paste the text", height=260, key="ct_text",
                                placeholder="Paste the draft here, for example from Google Docs.\n\n"
                                            "# Main heading\nOpening paragraph...\n## A section heading\nMore text...")
            keyword = st.text_input("Target keyword (optional)", key="ct_keyword", placeholder="local seo services")
            go = st.button("Check text", type="primary")
        else:
            c1, c2 = st.columns([3, 2])
            text = c1.text_area("URLs, one per line", height=170,
                                placeholder="https://example.com/page-1\nhttps://example.com/page-2, target keyword",
                                help="Add a comma and a keyword after a URL to check that keyword on the page.")
            file = c2.file_uploader("Or upload a file", type=["csv", "txt", "xlsx", "xls"],
                                    help="CSV or XLSX with the URL in the first column and, optionally, a keyword in the second.")
            go = st.button("Check pages", type="primary")

    if go and mode == MODES[0]:
        if len((text or "").split()) < 20:
            st.warning("Paste at least a few sentences of text to check.")
        else:
            state["ct_text_result"] = content.analyze_text(text, (keyword or "").strip())
            state["ct_text_id"] = time.time()
    elif go:
        try:
            pairs = checks.parse_pairs(text, file)
        except Exception as e:
            st.error(f"The uploaded file could not be read: {e}")
            pairs = []
        keywords = {}
        for url, kw in pairs:
            keywords.setdefault(url, kw)
        urls = list(keywords)[: settings["max_urls"]]
        if not urls:
            st.warning("Paste or upload at least one URL.")
        else:
            if len(keywords) > len(urls):
                st.info(f"Only the first {len(urls):,} URLs are checked. Raise the limit in the sidebar to check more.")
            results = {}
            session = core.make_session(settings["workers"], settings["user_agent"])
            ui.run_checks(urls, settings, results, core.RobotsCache(), content.content_hook(keywords), session)
            state["ct_results"] = results
            state["ct_run_id"] = time.time()
            state["ct_info"] = ui.run_info(settings)

    if mode == MODES[0]:
        if state.get("ct_text_result"):
            text_results(state["ct_text_result"])
        else:
            ui.covers("What the check covers", COVERS)
    elif state.get("ct_results"):
        page_results()
    else:
        ui.covers("What the check covers", COVERS)


if __name__ == "__main__":
    main()
