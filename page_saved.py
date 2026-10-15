"""
Open a saved run - load a CSV or Excel download from Sitemap audit, Site crawl, Bulk URL check or Keyword check
and view, filter and report on it again, without checking the pages again.
"""

import time

import streamlit as st

import seo_checks as checks
import seo_core as core
import seo_ui as ui

DESCRIPTION = (
    "Open a CSV or Excel download from an earlier run to view and filter the results again, and to download a new "
    "client report or XML sitemap from it, without checking the pages again."
)
COVERS = [
    ("Any page check download", "Files from Sitemap audit, Site crawl, Bulk URL check and Keyword check."),
    ("The same results view", "Issue summary, filters, views by group and the status bar, as when the run finished."),
    ("A new client report", "Download the Word report again, for example with your agency branding added."),
    ("XML sitemap", "Build an XML sitemap of the indexable URLs in the file."),
]


def main():
    ui.page_header("open-saved-run", "Open a saved run", DESCRIPTION)
    state = st.session_state
    with st.container(key="deck_saved"):
        file = st.file_uploader("A CSV or Excel file downloaded from this tool", type=["csv", "xlsx"], key="saved_file",
                                help="Excel files are read from their All Data sheet. A filtered download holds only "
                                     "the rows that were shown when it was saved.")
        go = st.button("Open", type="primary", disabled=file is None)
    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            try:
                df, groups, overview, tool = checks.rebuild_run(checks.load_export(file))
            except Exception as e:
                st.error(f"The file could not be opened: {e}")
            else:
                state["saved_run"] = (df, groups, overview, tool)
                state["saved_run_id"] = time.time()
                state["saved_total"] = len(df)
                state["saved_info"] = {"Opened from": file.name, "Tool": tool}
    if not state.get("saved_run"):
        ui.covers("What you can open", COVERS)
        return
    df, groups, overview, tool = state["saved_run"]
    hosts = {core.host_key(u) for u in df["URL"]}
    site = core.origin_of(df["URL"].iloc[0]) if len(hosts) == 1 and len(df) else ""
    st.caption(f"{tool} results from {state['saved_info']['Opened from']}: {len(df):,} URLs. Link, image and duplicate "
               "details are not in the download, so only the columns saved in the file are shown.")
    ui.render_results(df, "saved", groups, overview, state.get("saved_info", {}), "saved-run", tool, site=site)


if __name__ == "__main__":
    main()
