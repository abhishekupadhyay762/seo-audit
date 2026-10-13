"""
Internal link opportunities - pages on the site that mention a keyword but do not link to the page
that should rank for it, with the sentence to add the link in.
The search is in seo_content.py (link_hook, link_tables).
"""

import re
import time

import streamlit as st

import seo_content as content
import seo_core as core
import seo_ui as ui

DESCRIPTION = (
    "Enter the page you want to rank and its keywords. The tool reads the site's pages and finds the ones that "
    "mention a keyword but do not link to that page yet, with the sentence to link from."
)
COVERS = [
    ("Link opportunities", "Pages that mention the keyword in their main content and do not link to the target page."),
    ("Sentence to link from", "The sentence where the keyword appears, and the words to use as anchor text."),
    ("Pages that already link", "Which pages link to the target page today, and with what anchor text."),
    ("Anchor text mix", "Every anchor text pointing at the target, so you can spot over-used exact matches."),
    ("Sitemap or your own list", "Scan the pages in the site's sitemap, or paste the URLs to scan."),
    ("Main content only", "Menus, headers and footers are left out, so suggestions are links inside the content."),
]
SOURCES = ["The site's sitemap", "A list of URLs"]
LINK = st.column_config.LinkColumn


def parse_keywords(text: str) -> list:
    parts = [core.clean(p) for p in re.split(r"[\n,;]+", text or "")]
    return list(dict.fromkeys(p for p in parts if p))


def run(target: str, keywords: list, source: str, url_text: str, include: str, exclude: str, settings: dict):
    state = st.session_state
    session = core.make_session(settings["workers"], settings["user_agent"])
    with st.spinner("Opening the target page..."):
        tgt = core.audit_url(session, target, settings["timeout"], 0, None, None)
    if tgt["Final Status Code"] is None:
        st.error(f"The target page did not answer ({tgt['Fetch Error']}). Check the address.")
        return
    final = tgt["Final URL"] or target
    if tgt["Final Status Code"] != 200:
        st.warning(f"The target page answers {tgt['Final Status Code']}. Links to it would lead to an error; fix the page first.")
    if not keywords:
        fallback = tgt["H1"] or tgt["Title"]
        if not fallback:
            st.warning("Add at least one keyword: the target page has no H1 or title to use instead.")
            return
        keywords = [fallback]
        st.info(f"No keyword given, so the target page's {'H1' if tgt['H1'] else 'title'} is used: {fallback}")

    robots = None
    if source == SOURCES[0]:
        urls, note, robots = ui.urls_from_sitemap(core.origin_of(final), settings, include, exclude)
        if robots is None:
            st.error(note)
            return
    else:
        urls = core.collect_inputs(url_text, None)
        inc = [p.strip() for p in include.split(",") if p.strip()]
        exc = [p.strip() for p in exclude.split(",") if p.strip()]
        urls = [u for u in urls if (not inc or any(p in u for p in inc)) and not any(p in u for p in exc)]
        note = f"{len(urls):,} URLs in the list."
    site = core.host_key(final)
    target_keys = {content.link_key(target), content.link_key(final)}
    other_site = [u for u in urls if core.host_key(u) != site]
    urls = [u for u in urls if core.host_key(u) == site and content.link_key(u) not in target_keys]
    if other_site:
        note += f" {len(other_site):,} URLs on other sites are skipped."
    if len(urls) > settings["max_urls"]:
        note += f" The first {settings['max_urls']:,} are scanned; raise the limit in the sidebar to scan more."
        urls = urls[: settings["max_urls"]]
    if not urls:
        st.warning(note + " There are no pages to scan.")
        return

    results = {}
    ui.run_checks(urls, settings, results, robots or core.RobotsCache(), content.link_hook(target_keys, keywords), session)
    rows = [results[i] for i in sorted(results)]
    state["lo_tables"] = content.link_tables(rows)
    state["lo_run_id"] = time.time()
    state["lo_meta"] = {"target": final, "title": tgt["Title"] or tgt["H1"] or "", "keywords": keywords, "note": note}
    state["lo_info"] = {"Target page": final, "Keywords": ", ".join(keywords), **ui.run_info(settings)}


def results():
    state = st.session_state
    opp_df, linking_df, anchor_df, scanned_df = state["lo_tables"]
    meta, run_id = state.get("lo_meta", {}), state.get("lo_run_id")
    st.caption(f"Target page: {meta.get('target', '')}. Keywords: {', '.join(meta.get('keywords', []))}. {meta.get('note', '')}")
    ui.cards(content.link_numbers(opp_df, linking_df, scanned_df))
    tabs = st.tabs([f"Opportunities ({len(opp_df):,})", f"Already linking ({len(linking_df):,})",
                    f"Anchor texts ({len(anchor_df):,})", f"All pages scanned ({len(scanned_df):,})"])
    with tabs[0]:
        if opp_df.empty:
            st.info("No page mentions the keywords without already linking to the target. Try other wordings of "
                    "the keyword, or scan more pages.")
        else:
            st.dataframe(opp_df, width="stretch", hide_index=True, height=ui.table_height(len(opp_df), 520),
                         column_config={"Page": LINK("Page", pinned=True, width="medium"),
                                        "Sentence To Link From": st.column_config.TextColumn(width="large")})
            st.caption("Add a link to the target page on the words in Anchor Text To Use, inside that sentence. Vary "
                       "the anchor text across pages, and link from indexable pages first. Pages that link to the "
                       "target only from a menu or footer are listed too: a link inside the content counts for more.")
    with tabs[1]:
        if linking_df.empty:
            st.info("None of the scanned pages links to the target page, in the content or in menus.")
        else:
            st.dataframe(linking_df, width="stretch", hide_index=True, height=ui.table_height(len(linking_df), 460),
                         column_config={"Page": LINK("Page", pinned=True, width="medium"),
                                        "Anchor Texts Used": st.column_config.TextColumn(width="large")})
            st.caption("Links To Target counts every link on the page, menus and footers included; In-Content Links "
                       "counts only the links inside the main content.")
    with tabs[2]:
        if anchor_df.empty:
            st.info("No links to the target page were found.")
        else:
            st.dataframe(anchor_df, width="stretch", hide_index=True, height=ui.table_height(len(anchor_df), 460))
    with tabs[3]:
        st.dataframe(scanned_df, width="stretch", hide_index=True, height=ui.table_height(len(scanned_df), 460),
                     column_config={"Page": LINK("Page", pinned=True, width="medium")})

    info = state.get("lo_info", {})
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download opportunities (CSV)", lambda: core.to_csv_bytes(opp_df), "link-opportunities.csv",
                "text/csv", "lo_csv", run_id)
    ui.download(row, "⬇ Download Excel", lambda: content.links_excel(opp_df, linking_df, anchor_df, scanned_df, info),
                "link-opportunities.xlsx", core.XLSX_MIME, "lo_xlsx", run_id, heavy=True)


def main():
    settings = ui.crawl_settings(default_max=500, limit=10_000)
    ui.page_header("link-opportunities", "Internal link opportunities", DESCRIPTION)

    with st.container(key="deck_links"):
        c1, c2 = st.columns([3, 2])
        target = c1.text_input("Page that should get the links", placeholder="https://example.com/services/local-seo")
        kw_text = c2.text_input("Keywords (separate with commas)", placeholder="local seo, local seo services",
                                help="Wordings of the topic the target page should rank for. Singular and plural "
                                     "both match. Leave empty to use the page's H1.")
        source = st.radio("Pages to scan", SOURCES, horizontal=True)
        url_text = ""
        if source == SOURCES[1]:
            url_text = st.text_area("URLs to scan, one per line", height=130,
                                    placeholder="https://example.com/blog/post-1\nhttps://example.com/blog/post-2")
        f1, f2 = st.columns(2)
        include = f1.text_input("Only URLs containing", placeholder="/blog/", help="Separate several with commas.")
        exclude = f2.text_input("Skip URLs containing", placeholder="/tag/, /author/")
        go = st.button("Find opportunities", type="primary")

    if go:
        url = core.normalize_url(target) if core.looks_like_url(target) else ""
        if not url:
            st.warning("Enter the full address of the page that should get the links.")
        elif source == SOURCES[1] and not url_text.strip():
            st.warning("Paste the URLs to scan, or choose the site's sitemap.")
        else:
            run(url, parse_keywords(kw_text), source, url_text, include, exclude, settings)

    if not st.session_state.get("lo_tables"):
        ui.covers("What the search covers", COVERS)
        return
    results()


if __name__ == "__main__":
    main()
