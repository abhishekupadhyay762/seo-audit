"""
Custom search and extraction - find any text or code on every page, and pull out any element.
The search itself is in seo_tech.py; the shared look is in seo_ui.py.
"""

import time

import pandas as pd
import streamlit as st

import seo_core as core
import seo_tech as tech
import seo_ui as ui

DESCRIPTION = (
    "Search every page for any text or code, such as a missing tracking tag or an old phone number, and pull out "
    "any element into a table: author, date, price, breadcrumb or anything else."
)
COVERS = [
    ("Search the source code", "Find pages that contain, or do not contain, a piece of text or code (GA4, GTM, a pixel)."),
    ("Search the visible text", "Find words visitors see, such as lorem ipsum, an old phone number or out of stock."),
    ("Extract with CSS selectors", "Pull out elements, such as breadcrumbs, prices or author names, the way you style them."),
    ("Extract with XPath", "Reach any element or attribute, for example //meta[@name='author']/@content."),
    ("Extract with regex", "Match any pattern in the HTML; the first group in brackets is the value kept."),
    ("Ready-made rules", "Load examples for analytics tags, author, dates, breadcrumbs, prices and og:image."),
]
LINK = st.column_config.LinkColumn


def editors():
    """The two rule tables. Returns (search table, extraction table) as edited."""
    state = st.session_state
    version = state.setdefault("cs_version", 0)
    search = state.setdefault("cs_search", tech.EXAMPLE_SEARCH.copy())
    extract = state.setdefault("cs_extract", tech.EXAMPLE_EXTRACT.copy())
    b = st.container(horizontal=True)
    if b.button("Load the examples", key="cs_examples"):
        state["cs_search"], state["cs_extract"] = tech.EXAMPLE_SEARCH.copy(), tech.EXAMPLE_EXTRACT.copy()
        state["cs_version"] = version + 1
        st.rerun()
    if b.button("Clear all rules", key="cs_clear"):
        state["cs_search"], state["cs_extract"] = tech.EMPTY_SEARCH.copy(), tech.EMPTY_EXTRACT.copy()
        state["cs_version"] = version + 1
        st.rerun()
    st.markdown("**Search** (counts how often the text appears on each page)")
    s = st.data_editor(
        search, num_rows="dynamic", width="stretch", hide_index=True, key=f"cs_search_editor_{version}",
        column_config={
            "Name": st.column_config.TextColumn(width="medium"),
            "Mode": st.column_config.SelectboxColumn(options=tech.SEARCH_MODES, required=True, default="Contains"),
            "Type": st.column_config.SelectboxColumn(options=tech.SEARCH_TYPES, required=True, default="Text"),
            "Look in": st.column_config.SelectboxColumn(options=tech.SEARCH_WHERE, required=True, default=tech.SEARCH_WHERE[0]),
            "Find": st.column_config.TextColumn(width="large", help="Plain text, or a regular expression when Type is Regex."),
            "Match case": st.column_config.CheckboxColumn(default=False),
        })
    st.markdown("**Extract** (pulls the matching values out of each page)")
    e = st.data_editor(
        extract, num_rows="dynamic", width="stretch", hide_index=True, key=f"cs_extract_editor_{version}",
        column_config={
            "Name": st.column_config.TextColumn(width="medium"),
            "Method": st.column_config.SelectboxColumn(options=tech.EXTRACT_METHODS, required=True, default="CSS selector"),
            "Expression": st.column_config.TextColumn(width="large",
                                                      help="A CSS selector (h1, .price), an XPath (//h1) or a regex."),
            "Extract": st.column_config.SelectboxColumn(options=tech.EXTRACT_WHAT, required=True, default="Text"),
            "Attribute": st.column_config.TextColumn(help="Only for Extract = Attribute, for example content, href or src."),
        })
    st.caption("Add a row with the + at the bottom of a table, or select rows and delete them. A rule with an empty "
               "Find or Expression is skipped.")
    return s, e


def results():
    state = st.session_state
    pages_df, values_df, summary_df = state["cs_tables"]
    rules, run_id, info = state["cs_rules"], state.get("cs_run_id"), state.get("cs_info", {})
    read = int(pages_df["Note"].eq("").sum())
    ui.cards({"Pages checked": len(pages_df), "Pages read": read, "Rules": len(summary_df),
              "Values extracted": len(values_df)})
    st.subheader("Rules")
    st.dataframe(summary_df, width="stretch", hide_index=True, height=ui.table_height(len(summary_df), 380))
    st.caption("Pages Matching means the pages that contain the text (or, for Does not contain, the pages that do not), "
               "or the pages where an extraction found a value.")
    names = [r["name"] for r in rules]
    if names:
        pick = st.selectbox("Show the pages matching a rule", ["Every page"] + names, key=f"cs_pick_{run_id}")
    else:
        pick = "Every page"
    view = pages_df if pick == "Every page" else tech.matching_pages(pages_df, next(r for r in rules if r["name"] == pick))
    tabs = st.tabs([f"Pages ({len(view):,})", f"Extracted values ({len(values_df):,})"])
    with tabs[0]:
        st.dataframe(view, width="stretch", hide_index=True, height=ui.table_height(len(view), 480),
                     column_config={"URL": LINK("URL", pinned=True, width="medium")})
    with tabs[1]:
        if values_df.empty:
            st.info("No values were extracted. Check the expressions, or try the rule on one page's source first.")
        else:
            st.dataframe(values_df, width="stretch", hide_index=True, height=ui.table_height(len(values_df), 480),
                         column_config={"URL": LINK("URL", pinned=True, width="medium"),
                                        "Value": st.column_config.TextColumn(width="large")})
    st.caption("Searches and extractions read the HTML the server sends. Text added later by JavaScript is not seen.")
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download CSV", lambda: core.to_csv_bytes(pages_df), "custom-search.csv", "text/csv", "cs_csv", run_id)
    search_df, extract_df = state.get("cs_used", (None, None))
    ui.download(row, "⬇ Download Excel",
                lambda: tech.search_excel(pages_df, values_df, summary_df, search_df, extract_df, info),
                "custom-search.xlsx", core.XLSX_MIME, "cs_xlsx", run_id, heavy=True)


def main():
    settings = ui.crawl_settings(default_max=500, limit=10_000)
    ui.page_header("custom-search", "Custom search and extraction", DESCRIPTION)
    state = st.session_state

    with st.container(key="deck_search"):
        spec = ui.source_inputs("cs")
        search_df, extract_df = editors()
        go = st.button("Search pages", type="primary")

    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            search, extract, problems = tech.read_rules(search_df, extract_df)
            for p in problems:
                st.error(p)
            if not (search or extract):
                st.warning("Add at least one search or extraction rule that works.")
            else:
                rows, info, error = ui.collect_pages(spec, settings, tech.search_hook(search, extract))
                if error:
                    st.error(error)
                else:
                    state["cs_tables"] = tech.search_tables(rows, search, extract)
                    state["cs_rules"] = search + extract
                    state["cs_used"] = (pd.DataFrame(search_df).copy(), pd.DataFrame(extract_df).copy())
                    state["cs_run_id"] = time.time()
                    state["cs_info"] = {**info, **ui.run_info(settings)}
                    st.toast("Search complete", icon="✅")

    if not state.get("cs_tables"):
        ui.covers("What you can do", COVERS)
        return
    results()


if __name__ == "__main__":
    main()
