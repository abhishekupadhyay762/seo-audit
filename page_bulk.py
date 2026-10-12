"""
Bulk URL check - paste or upload URLs, get status, indexability and on-page data for each one.
The checks themselves are in seo_core.py; the results view is in seo_ui.py.
"""

import time

import streamlit as st

import seo_core as core
import seo_crawl as crawl
import seo_ui as ui

DESCRIPTION = (
    "Paste or upload a list of URLs to check status codes, redirects, indexability, titles, meta descriptions, "
    "headings, content, schema and links in one run."
)
COVERS = [
    ("URL and status", "First status code, redirect type and hops, the full chain, final URL and response time."),
    ("Indexability", "A Yes or No verdict with the reason: robots.txt, noindex, canonical, redirect or error."),
    ("Title and meta", "Title with length and pixel width, meta description, and duplicates within the list."),
    ("Headings", "H1 text and count, the H2 list, H3 count and skipped heading levels."),
    ("Content", "Main-content word count, published and updated dates, and a flag for JavaScript-built pages."),
    ("Images", "Image count, missing alt attributes, empty alt text and images without width or height."),
    ("Schema", "Schema types found in JSON-LD, Microdata or RDFa, and JSON-LD that does not parse."),
    ("Social and tags", "Open Graph title, description and image, Twitter card, lang, viewport and hreflang count."),
    ("Links", "Link counts, links with empty anchor text and, if you choose, every link's status (broken links, links to redirects)."),
    ("Canonical and hreflang", "Whether canonical targets and hreflang alternates answer 200, are indexable and link back."),
    ("Issues", "Every finding graded Critical, Warning or Notice, with a summary you can filter by."),
]


def main():
    settings = ui.crawl_settings(default_max=1_000, limit=20_000)
    ui.page_header("bulk-url-check", "Bulk URL check", DESCRIPTION)

    with st.container(key="deck_bulk"):
        c1, c2 = st.columns([3, 2])
        text = c1.text_area("URLs, one per line", height=170,
                            placeholder="https://example.com/page-1\nhttps://example.com/page-2")
        file = c2.file_uploader("Or upload a file", type=["csv", "txt", "xlsx", "xls"],
                                help="CSV, TXT or XLSX with the URLs in the first column.")
        o1, o2, o3 = st.columns(3)
        check_targets = o1.checkbox("Check canonical and hreflang targets", value=True)
        check_links = o2.checkbox("Check the links on these pages", value=False,
                                  help="Finds broken links and links to redirects. Adds one request per unique link.")
        external = o3.checkbox("Include external links", value=True, disabled=not check_links)
        go = st.button("Check URLs", type="primary")

    if go:
        try:
            urls = core.collect_inputs(text, file)
        except Exception as e:
            st.error(f"The uploaded file could not be read: {e}")
            urls = []
        if not urls:
            st.warning("Paste or upload at least one URL, then choose Check URLs.")
        else:
            if len(urls) > settings["max_urls"]:
                st.info(f"{len(urls):,} URLs given. The first {settings['max_urls']:,} will be checked. "
                        "Raise the limit in the sidebar to check more.")
                urls = urls[: settings["max_urls"]]
            state = st.session_state
            results = {}
            state["bulk_results"] = results
            state["bulk_run_id"] = time.time()
            state["bulk_total"] = len(urls)
            state["bulk_info"] = ui.run_info(settings)
            state.pop("bulk_final", None)
            state.pop("bulk_links", None)
            session = core.make_session(settings["workers"], settings["user_agent"])
            robots = core.RobotsCache()
            ui.run_checks(urls, settings, results, robots, {"links": check_links}, session, toast=False)
            rows = [results[i] for i in sorted(results)]
            if check_links:
                state["bulk_links"] = ui.run_link_checks(rows, ui.links_from_rows(rows), settings, session, external)
            if check_targets:
                ui.run_target_checks(rows, settings, robots, session)
            st.toast("Check complete", icon="✅")

    if not st.session_state.get("bulk_results"):
        ui.covers("What the report covers", COVERS)
        return

    state = st.session_state
    df = ui.results_table("bulk")
    hosts = {core.host_key(u) for u in df["URL"]}
    site = core.origin_of(df["URL"].iloc[0]) if len(hosts) == 1 else ""
    links_df = state.get("bulk_links")
    sections = (lambda: [s for s in [ui.broken_link_section(links_df)] if s]) if links_df is not None else None

    def pages():
        ui.render_results(df, "bulk", core.GROUPS, core.OVERVIEW_COLS, state.get("bulk_info", {}),
                          "bulk-url-check", "Bulk URL check", site=site, report_sections=sections)
    if links_df is None:
        pages()
        return
    tab_pages, tab_links = st.tabs(["Pages", f"Links ({crawl.link_summary(links_df)['Broken']:,} broken)"])
    with tab_pages:
        pages()
    with tab_links:
        ui.links_view(links_df, "bulk", "bulk-url-check", state.get("bulk_info", {}))


if __name__ == "__main__":
    main()
