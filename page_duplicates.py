"""
Duplicate content - exact and near-duplicate pages, and repeated titles, H1s and meta descriptions.
The comparison is in seo_tech.py (find_duplicates); the shared look is in seo_ui.py.
"""

import time

import streamlit as st

import seo_tech as tech
import seo_ui as ui

DESCRIPTION = (
    "Find pages with the same or nearly the same main content, such as location pages with only the city changed, "
    "and pages that repeat a title, H1 or meta description."
)
COVERS = [
    ("Exact copies", "Pages whose main content is word for word the same, on different addresses."),
    ("Near copies", "Pages that are mostly the same (90% alike by default, you choose), with the similarity of each pair."),
    ("Groups to fix", "Copies grouped together, with the page to keep and what to do with the others."),
    ("Handled already", "Groups where only one page is indexable (the rest canonicalise to it or are noindex)."),
    ("Repeated titles, H1s and metas", "The same title, H1 or meta description on more than one page."),
    ("Each page's own text only", "Menus, header, footer, sidebars and short text repeated across the site (form "
                                  "labels, buttons, link lists) are left out, so a shared template does not count."),
]


def main():
    settings = ui.crawl_settings(default_max=500, limit=10_000)
    ui.page_header("duplicate-content", "Duplicate content", DESCRIPTION)
    state = st.session_state

    with st.container(key="deck_duplicates"):
        spec = ui.source_inputs("dc")
        go = st.button("Find duplicates", type="primary")

    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            rows, info, error = ui.collect_pages(spec, settings, tech.duplicate_hook())
            if error:
                st.error(error)
            else:
                state["dc_rows"], state["dc_run_id"] = rows, time.time()
                state["dc_info"] = {**info, **ui.run_info(settings)}
                state.pop("dc_result", None)
                st.toast("Check complete", icon="✅")

    rows = state.get("dc_rows")
    if not rows:
        ui.covers("What the check finds", COVERS)
        return

    threshold = st.slider("Count pages as near copies when they are at least this similar (%)", 50, 99,
                          tech.DUP_THRESHOLD, key=f"dc_threshold_{state.get('dc_run_id')}",
                          help="90% catches template pages with a few words changed. Lower it to find pages that "
                               "share large parts of their text.")
    cached = state.get("dc_result")
    if not cached or cached[0] != (state.get("dc_run_id"), threshold):
        state["dc_result"] = ((state.get("dc_run_id"), threshold), tech.find_duplicates(rows, threshold))
    result = state["dc_result"][1]
    info = {**state.get("dc_info", {}), "Similarity threshold": f"{threshold}%"}
    ui.duplicates_view(result, "dc", "duplicate-content", info,
                       f"Pages with fewer than {tech.DUP_MIN_WORDS} words of main content are too short to compare and "
                       "are left out of the near-copy check. Only pages that answered 200 are compared.")


if __name__ == "__main__":
    main()
