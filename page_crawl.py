"""
Site crawl - start at a page, follow the internal links, check every page found.
Also compares the crawl with the sitemap and checks where every link leads.
The crawl itself is in seo_crawl.py; the results view is in seo_ui.py.
"""

import time

import streamlit as st

import seo_core as core
import seo_crawl as crawl
import seo_report as report
import seo_ui as ui

DESCRIPTION = (
    "Start at the homepage and follow internal links like a search engine. Every page found is checked, compared "
    "with the sitemap, and every link is tested."
)
COVERS = [
    ("Pages found by links", "Every page reachable from the start page, how many clicks deep it is and how many pages link to it."),
    ("Crawl versus sitemap", "Orphan pages that only the sitemap knows about, and indexable pages the sitemap is missing."),
    ("Broken links", "Every internal and external link that leads to an error, with the page it is on and its anchor text."),
    ("Links to redirects", "Internal links that point at a redirect instead of the final URL."),
    ("Canonical and hreflang", "Whether canonical targets and hreflang alternates answer 200, are indexable and link back."),
    ("Full on-page data", "Title, meta description, headings, content, images, schema and issues for every page."),
    ("On-page score", "A score out of 100 for every page, so you can fix the weakest pages first."),
]


def run_crawl(target: str, opts: dict, settings: dict):
    state = st.session_state
    for key in ("cr_results", "cr_final", "cr_links", "cr_comp", "cr_meta"):
        state.pop(key, None)
    session = core.make_session(settings["workers"], settings["user_agent"])
    with st.spinner("Opening the start page..."):
        start, notes, error = crawl.resolve_start(session, target, settings["timeout"])
    if error:
        st.error(error)
        return
    robots = core.RobotsCache()
    sitemap_urls, sitemap_note = [], ""
    if opts["sitemap"]:
        with st.spinner("Reading the sitemap..."):
            disc = core.discover_sitemaps(session, start, settings["timeout"])
            if not disc["error"]:
                robots.store(disc["origin"], disc["robots_status"], disc["robots_text"], disc["robots_error"])
                if disc["fallback"]:
                    sitemap_note = "No XML sitemap was found, so the crawl could not be compared with one."
                else:
                    files, entries = core.read_sitemaps(session, disc, settings["timeout"])
                    sitemap_urls = list(dict.fromkeys(e["URL"] for e in entries))
                    sitemap_note = f"{len(sitemap_urls):,} URLs read from the sitemap."

    status = st.empty()
    started = time.time()

    def on_crawl(n, depth, elapsed):
        status.caption(f"Crawling: {n:,} pages checked, now {depth} click{'s' if depth != 1 else ''} from the start page "
                       f"({int(elapsed // 60)}m {int(elapsed % 60)}s)")

    page_opts = ui.page_opts(opts["score"], "", settings, robots)
    result = crawl.crawl_site(session, start, settings, robots, opts["max_pages"], opts["max_depth"],
                              opts["robots"], opts["skip_params"], on_crawl, page_opts)
    status.empty()
    comp = None
    if opts["sitemap"] and sitemap_urls:
        on_progress, done = ui.progress("Sitemap pages the crawl did not reach, checked")
        comp = crawl.compare_sitemap(session, result, sitemap_urls, settings, robots, on_progress, page_opts)
        done()
    rows = result["rows"]
    links_df = None
    if opts["links"]:
        links_df = ui.run_link_checks(rows, result["links"], settings, session, opts["external"])
    if opts["targets"]:
        ui.run_target_checks(rows, settings, robots, session)

    state["cr_extras"] = {"score": opts["score"]}
    state["cr_results"] = dict(enumerate(rows))
    state["cr_run_id"] = time.time()
    state["cr_total"] = len(rows)
    state["cr_links"] = links_df
    state["cr_comp"] = comp
    state["cr_info"] = {"Start page": start, **ui.run_info(settings), "Most pages": f"{opts['max_pages']:,}",
                        "Most clicks deep": opts["max_depth"], "Follows robots.txt": "Yes" if opts["robots"] else "No"}
    state["cr_meta"] = {"start": start, "notes": notes + ([sitemap_note] if sitemap_note else []),
                        "stopped": result["stopped"], "skipped": result["skipped"],
                        "minutes": round((time.time() - started) / 60, 1)}
    st.toast("Crawl complete", icon="✅")


def show_comparison(comp):
    if comp is None:
        st.info("The crawl was not compared with a sitemap. Turn on Compare with the sitemap and crawl again.")
        return
    counts = comp["Finding"].value_counts()
    ui.cards({
        "Orphan pages": int(sum(v for k, v in counts.items() if k.startswith(("Orphan", "In the sitemap")))),
        "Missing from the sitemap": int(counts.get("Found by the crawl, missing from the sitemap", 0)),
    })
    if comp.empty:
        st.success("The crawl and the sitemap match: every indexable page found is in the sitemap, and every sitemap page was reached.")
        return
    st.dataframe(comp, width="stretch", hide_index=True, height=360,
                 column_config={"URL": st.column_config.LinkColumn("URL", pinned=True, width="large"),
                                "Linked From": st.column_config.LinkColumn("Linked From")})
    st.caption("Orphan pages are in the sitemap but no crawled page links to them. Missing pages are indexable pages "
               "the crawl found that the sitemap does not list.")


def report_sections(comp, links_df):
    """Extra report sections. Gets the data passed in: the report is built outside the page run."""
    sections = []
    if comp is not None and not comp.empty:
        sections.append({
            "title": "Crawl compared with the sitemap",
            "intro": "Pages only the sitemap knows about (orphans) and indexable pages the sitemap does not list.",
            "header": ["Page", "Finding"],
            "rows": [[report.url_label(r["URL"]), r["Finding"]] for r in comp.head(80).to_dict("records")],
        })
    links = ui.broken_link_section(links_df)
    if links:
        sections.append(links)
    return sections


def main():
    settings = ui.crawl_settings(show_max=False)
    ui.page_header("site-crawl", "Site crawl", DESCRIPTION)

    with st.container(key="deck_crawl"):
        with st.form("cr_start", border=False):
            c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
            target = c1.text_input("Start page or domain", placeholder="example.com   or   https://example.com/blog/")
            go = c2.form_submit_button("Start crawl", type="primary", width="stretch")
            c3, c4, _ = st.columns(3)
            max_pages = c3.number_input("Most pages to crawl", 10, 10_000, 500, step=100,
                                        help="Large sites take a while. Start with a few hundred pages.")
            max_depth = c4.number_input("Most clicks from the start page", 1, 50, 10)
            o1, o2, o3 = st.columns(3)
            follow_robots = o1.checkbox("Follow robots.txt", value=True,
                                        help="Pages robots.txt blocks for Googlebot are listed but not requested.")
            skip_params = o1.checkbox("Skip URLs with ?parameters", value=True,
                                      help="Filter and sort links can create thousands of near-copies of a page.")
            use_sitemap = o2.checkbox("Compare with the sitemap", value=True)
            check_targets = o2.checkbox("Check canonical and hreflang targets", value=True)
            check_links = o3.checkbox("Check every link", value=True)
            external = o3.checkbox("Include external links", value=True)
            add_score = o1.checkbox("Add the on-page score", value=True,
                                    help="A score out of 100 for every page, from the same checks as the Page audit "
                                         "tool. Turn off for very large sites to finish faster.")
    if go:
        run_crawl(target, {"max_pages": int(max_pages), "max_depth": int(max_depth), "robots": follow_robots,
                           "skip_params": skip_params, "sitemap": use_sitemap, "links": check_links,
                           "external": external, "targets": check_targets, "score": add_score}, settings)

    state = st.session_state
    if not state.get("cr_results"):
        ui.covers("What the crawl covers", COVERS)
        return

    meta = state.get("cr_meta", {})
    for note in meta.get("notes", []):
        st.caption(note)
    if meta.get("stopped"):
        st.warning(meta["stopped"] + " Raise the limit to crawl further.")
    skipped = meta.get("skipped", {})
    if skipped.get("parameters") or skipped.get("files"):
        n_par, n_file = skipped.get("parameters", 0), skipped.get("files", 0)
        st.caption(f"Not crawled: {n_par:,} URL{'s' if n_par != 1 else ''} with parameters and "
                   f"{n_file:,} link{'s' if n_file != 1 else ''} to files such as images.")

    extras = state.get("cr_extras", {})
    groups = core.with_extras(core.CRAWL_GROUPS, **extras)
    df = ui.results_table("cr", groups)
    links_df, comp = state.get("cr_links"), state.get("cr_comp")
    tabs = st.tabs(["Pages", f"Links ({crawl.link_summary(links_df)['Broken']:,} broken)" if links_df is not None else "Links",
                    "Crawl versus sitemap"])
    with tabs[0]:
        ui.render_results(df, "cr", groups, ui.overview_cols(core.CRAWL_OVERVIEW_COLS, extras), state.get("cr_info", {}),
                          "site-crawl", "Site crawl", site=meta.get("start", ""),
                          report_sections=lambda: report_sections(comp, links_df))
    with tabs[1]:
        if links_df is None:
            st.info("Links were not checked. Turn on Check every link and crawl again.")
        else:
            ui.links_view(links_df, "cr", "site-crawl", state.get("cr_info", {}))
    with tabs[2]:
        show_comparison(comp)


if __name__ == "__main__":
    main()
