"""
Sitemap audit - find a site's sitemap, list every URL in it, check the sitemap itself for
problems, then check the pages you choose.
The checks themselves are in seo_core.py; the results view is in seo_ui.py.
"""

import time

import streamlit as st

import seo_core as core
import seo_crawl as crawl
import seo_report as report
import seo_tech as tech
import seo_ui as ui

DESCRIPTION = (
    "Enter a sitemap or a domain to list every URL it contains, find problems in the sitemap itself, and check "
    "the pages for status, indexability and on-page data."
)
COVERS = [
    ("Sitemap files", "Every sitemap and sitemap index found, with URL counts, file size and anything that could not be read."),
    ("URL inventory", "Each URL the sitemap lists, with lastmod, section, depth and how many times it appears."),
    ("Sitemap problems", "Duplicates, HTTP or wrong-domain URLs, invalid or missing lastmod dates and oversized files."),
    ("Sections", "URL counts by folder, so you can check one section or an even sample from each."),
    ("Page checks", "Status code, redirects, robots.txt, noindex and canonical for the URLs you choose."),
    ("On-page data", "Title, meta description, headings, word count, images, schema and links, with issues by severity."),
]
SITE_ADVICE = {
    "No XML sitemap found": "Add an XML sitemap for the site and list it in robots.txt.",
    "Sitemap is not listed in robots.txt": "Add a line to robots.txt in this form: Sitemap: https://example.com/sitemap.xml",
    "Every lastmod date is the same": "Google only uses lastmod when it matches real page changes. Set it to each page's own last change.",
}
LINK = st.column_config.LinkColumn


def find_urls(target: str, settings: dict):
    """Step 1: find the sitemap(s) and read them into the inventory."""
    for key in ("sm_inv", "sm_disc", "sm_results", "sm_final", "sm_dup", "sm_images"):
        st.session_state.pop(key, None)
    session = ui.session(settings, 6)
    with st.spinner("Looking for the sitemap..."):
        disc = core.discover_sitemaps(session, target, settings["timeout"])
    if disc["error"]:
        st.error(disc["error"])
        return
    holder = st.empty()
    files, entries = core.read_sitemaps(
        session, disc, settings["timeout"],
        on_progress=lambda f, u: holder.caption(f"Read {f:,} file(s), {u:,} URLs so far..."),
    )
    holder.empty()
    st.session_state["sm_inv"] = core.build_inventory(disc, files, entries)
    st.session_state["sm_disc"] = {k: disc[k] for k in ("origin", "robots_status", "robots_text", "robots_error")}
    st.session_state["sm_inv_id"] = time.time()


def show_inventory(inv: dict):
    inv_id = st.session_state.get("sm_inv_id")
    urls, files, sections, issues = inv["urls"], inv["files"], inv["sections"], inv["issues"]
    st.subheader("Sitemap")
    if inv["fallback"]:
        st.warning(f"No XML sitemap was found for {inv['origin']}. The URLs below come from the "
                   f"{inv['fallback'].lower()} instead, so the list may be incomplete.")
    for note in inv["notes"]:
        st.caption(note)
    ui.cards(core.inventory_numbers(inv))

    views = ["Sections", "Sitemap files", "URL list", f"Problems ({len(issues)})"]
    view = st.segmented_control("Sitemap view", views, default="Sections", key=f"sm_inv_view_{inv_id}",
                                label_visibility="collapsed") or "Sections"
    if view == "Sections":
        st.dataframe(
            sections, width="stretch", hide_index=True, height=min(38 + 35 * max(len(sections), 1), 318),
            column_config={"Share of URLs (%)": st.column_config.ProgressColumn(
                "Share of URLs", format="%.1f%%", min_value=0, max_value=100)},
        )
    elif view == "Sitemap files":
        st.dataframe(files, width="stretch", hide_index=True, height=min(38 + 35 * max(len(files), 1), 318),
                     column_config={"Sitemap File": LINK("Sitemap File", width="large"), "Listed In": LINK("Listed In")})
    elif view == "URL list":
        st.dataframe(urls.drop(columns=["_issues"]), width="stretch", hide_index=True, height=420,
                     column_config={"URL": LINK("URL", pinned=True, width="large"), "Sitemap File": LINK("Sitemap File")})
    elif issues.empty:
        st.success("No problems found in the sitemap itself.")
    else:
        picked = ui.pick_issue(issues, f"sm_problem_{inv_id}", "Tick a problem to see what it applies to.")
        if picked:
            applies = issues[(issues["Severity"] == picked[0]) & (issues["Issue"] == picked[1])].iloc[0]["Applies To"]
            if applies == "URLs":
                hit = urls[urls["_issues"].map(lambda items: picked in items)]
                st.dataframe(hit.drop(columns=["_issues"]), width="stretch", hide_index=True, height=300,
                             column_config={"URL": LINK("URL", pinned=True, width="large"), "Sitemap File": LINK("Sitemap File")})
            elif applies == "Sitemap files":
                st.dataframe(files[files["Problems"] != ""], width="stretch", hide_index=True,
                             column_config={"Sitemap File": LINK("Sitemap File", width="large")})
            else:
                st.info(SITE_ADVICE.get(picked[1], "This applies to the site as a whole."))

    info = {"Site": inv["origin"]}
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download URL list (CSV)", lambda: core.to_csv_bytes(urls), "sitemap-urls.csv", "text/csv",
                "sm_inv_csv", inv_id)
    ui.download(row, "⬇ Download sitemap report (Excel)", lambda: core.inventory_excel_bytes(inv, info),
                "sitemap-inventory.xlsx", core.XLSX_MIME, "sm_inv_xlsx", inv_id, heavy=True)


def choose_and_check(inv: dict, settings: dict):
    """Step 2: choose which listed URLs to check, then run the page checks."""
    urls, sections = inv["urls"], inv["sections"]
    inv_id = st.session_state.get("sm_inv_id")
    st.subheader("Page checks")
    if urls.empty:
        st.info("The sitemap lists no URLs, so there is nothing to check yet.")
        return
    counts = dict(zip(sections["Section"], sections["URLs"]))
    with st.container(key="deck_pages"):
        chosen = st.multiselect(
            "Sections to check", list(counts), default=[], key=f"sm_sections_{inv_id}",
            format_func=lambda s: f"{s}  ({counts[s]:,})", placeholder="All sections",
            help="Leave empty to include every section.",
        )
        c1, c2, c3 = st.columns([2, 2, 3])
        include = c1.text_input("Only URLs containing", placeholder="/blog/", key=f"sm_inc_{inv_id}")
        exclude = c2.text_input("Skip URLs containing", placeholder="/tag/, /author/", key=f"sm_exc_{inv_id}")
        scope = c3.radio("How many", ["Every URL", "A sample from each section"], horizontal=True, key=f"sm_scope_{inv_id}")
        per_section = 0
        if scope != "Every URL":
            per_section = c3.number_input("URLs per section", 1, 5000, 100, step=10, key=f"sm_per_{inv_id}",
                                          help="Picked evenly through each section, so old and new URLs are both covered.")
        t1, t2 = st.columns(2)
        check_targets = t1.checkbox("Check canonical and hreflang targets", value=True, key=f"sm_targets_{inv_id}",
                                    help="Requests each canonical target and hreflang alternate that is not in the list.")
        add_score = t2.checkbox("Add the on-page score", value=True, key=f"sm_score_{inv_id}",
                                help="A score out of 100 for every page, from the same checks as the Page audit tool. "
                                     "Turn off for very large sitemaps to finish faster.")
        picked = ui.extra_checks([t1, t2, t1], f"sm_{inv_id}")
        selected = core.select_urls(urls, chosen or list(counts), include, exclude, int(per_section), settings["max_urls"])
        matching = len(core.select_urls(urls, chosen or list(counts), include, exclude, int(per_section), len(urls)))
        note = f"{len(selected):,} of {len(urls):,} listed URLs will be checked."
        if matching > len(selected):
            note += f" {matching:,} match, and the sidebar limit is {settings['max_urls']:,}."
        st.caption(note)
        go = st.button(f"Check {len(selected):,} pages", type="primary", disabled=not selected, key="sm_check")

    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            disc = st.session_state.get("sm_disc", {})
            robots = ui.robots(settings)
            if disc.get("origin"):
                robots.store(disc["origin"], disc["robots_status"], disc["robots_text"], disc["robots_error"])
            results = {}
            st.session_state["sm_results"] = results
            st.session_state["sm_run_id"] = time.time()
            st.session_state["sm_total"] = len(selected)
            st.session_state["sm_info"] = {"Site": inv["origin"], **ui.run_info(settings)}
            st.session_state.pop("sm_final", None)
            extras = {"score": add_score, **picked}
            st.session_state["sm_extras"] = extras
            session = ui.session(settings)
            ui.run_checks(selected, settings, results, robots, ui.check_opts(extras, settings, robots) or None,
                          session, toast=False)
            rows = [results[i] for i in sorted(results)]
            if check_targets:
                ui.run_target_checks(rows, settings, robots, session)
            st.session_state["sm_dup"], st.session_state["sm_images"] = ui.finish_checks(rows, settings, session, extras)
            st.toast("Check complete", icon="✅")

    if st.session_state.get("sm_results"):
        extras = st.session_state.get("sm_extras", {})
        groups = core.with_extras(core.SITEMAP_GROUPS, **extras)
        df = ui.results_table("sm", groups, lambda rows: core.sitemap_extra(urls))
        dup, img_df = st.session_state.get("sm_dup"), st.session_state.get("sm_images")
        info = st.session_state.get("sm_info", {})

        def pages():
            ui.render_results(df, "sm", groups, ui.overview_cols(core.SITEMAP_OVERVIEW_COLS, extras), info,
                              "sitemap-audit", "Sitemap audit", [("Sitemap files", inv["files"])], site=inv["origin"],
                              report_sections=lambda: sitemap_report_sections(inv) + [
                                  s for s in (tech.duplicates_section(dup) if dup else {}, ui.image_section(img_df)) if s])
        extra_tabs = []
        if dup is not None:
            extra_tabs.append((ui.dup_tab_label(dup),
                               lambda: ui.duplicates_view(dup, "sm", "sitemap-audit", info)))
        if img_df is not None:
            extra_tabs.append((f"Images ({crawl.image_summary(img_df)['Broken']:,} broken)",
                               lambda: ui.images_view(img_df, "sm", "sitemap-audit", info)))
        if not extra_tabs:
            pages()
            return
        tabs = st.tabs(["Pages"] + [name for name, _ in extra_tabs])
        with tabs[0]:
            pages()
        for tab, (_, show) in zip(tabs[1:], extra_tabs):
            with tab:
                show()


def sitemap_report_sections(inv: dict) -> list:
    issues = inv["issues"]
    if issues.empty:
        return []
    return [{"title": "Problems in the sitemap itself",
             "intro": "Found while reading the sitemap files, before any page was checked.",
             "header": ["Problem", "Severity", "Count", "Applies to", "How to fix"],
             "rows": [[r["Issue"], r["Severity"], f"{r['Count']:,}", r["Applies To"], report.advice_for(r["Issue"])[1]]
                      for r in issues.to_dict("records")]}]


def main():
    settings = ui.crawl_settings(default_max=10_000, limit=100_000)
    ui.page_header("sitemap-audit", "Sitemap audit", DESCRIPTION)

    with st.container(key="deck_sitemap"):
        with st.form("sm_find", border=False):
            c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
            target = c1.text_input("Sitemap URL or domain",
                                   placeholder="example.com   or   https://example.com/sitemap.xml")
            go = c2.form_submit_button("Find URLs", type="primary", width="stretch")
    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            find_urls(target, settings)

    inv = st.session_state.get("sm_inv")
    if not inv:
        ui.covers("What the audit covers", COVERS)
        return
    show_inventory(inv)
    choose_and_check(inv, settings)


if __name__ == "__main__":
    main()
