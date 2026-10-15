"""
Staging vs live - the same pages on the live site and the new (staging) site, compared field by field,
with a launch checklist. The comparison is in seo_tech.py; the shared look is in seo_ui.py.
"""

import time
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

import seo_core as core
import seo_crawl as crawl
import seo_tech as tech
import seo_ui as ui

DESCRIPTION = (
    "Before a redesign or migration goes live, check the new site against the live one page by page: missing pages, "
    "changed titles, metas, H1s and canonicals, lost content and schema, and staging settings to remove at launch."
)
COVERS = [
    ("Launch checklist", "The problems that matter at launch first: missing pages, noindex, robots.txt, staging links."),
    ("Missing pages", "Live pages that answer 404 or an error on staging, which need the page or a 301 redirect."),
    ("Changed SEO elements", "Title, meta description, H1, canonical, indexability and hreflang, live next to staging."),
    ("Lost content", "Pages with much less text, fewer headings or schema types removed on staging."),
    ("Staging leftovers", "Staging pages whose HTML mentions the staging address, and a robots.txt that blocks everything."),
    ("Password-protected staging", "Works with staging sites behind a browser login box (user name and password)."),
]
SOURCES = ["The live sitemap", "Crawl the live site", "A list of live URLs"]
SEV_ICON = {**core.SEV_ICON, "OK": "✅ Same"}
LINK = st.column_config.LinkColumn


def live_urls(source: str, live_base: str, text: str, settings: dict):
    """(live URLs, explicit staging addresses by live URL, note, error)."""
    if source == SOURCES[0]:
        urls, note, rb = ui.urls_from_sitemap(live_base, settings)
        return (urls, {}, note, "") if rb is not None else ([], {}, "", note)
    if source == SOURCES[1]:
        sess = ui.session(settings)
        start, notes, error = crawl.resolve_start(sess, live_base, settings["timeout"])
        if error:
            return [], {}, "", error
        status = st.empty()
        result = crawl.crawl_site(sess, start, settings, ui.robots(settings), settings["max_urls"], 50, True, True,
                                  lambda n, d, e: status.caption(f"Crawling the live site: {n:,} pages found"))
        status.empty()
        urls = [r["URL"] for r in result["rows"] if r["Final Status Code"] == 200 and not r["Redirect Hops"]]
        return urls, {}, f"{len(urls):,} live pages found by the crawl.", ""
    pairs = {}
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip()]
        if parts and core.looks_like_url(parts[0]):
            live = core.normalize_url(parts[0])
            if live:
                pairs[live] = core.normalize_url(parts[1]) if len(parts) > 1 and core.looks_like_url(parts[1]) else ""
    return list(pairs), {k: v for k, v in pairs.items() if v}, f"{len(pairs):,} live URLs in the list.", ""


def fetch_robots(session, base: str, timeout) -> str:
    try:
        res = core.fetch_raw(session, core.origin_of(base) + "/robots.txt", timeout, max_bytes=500_000)
    except ValueError:
        return ""
    return res["body"].decode("utf-8", "replace") if res["status"] == 200 else ""


def only_on_staging(stage_session, stage_base: str, live_base: str, back: list, live_set: set, timeout) -> pd.DataFrame:
    """Pages in the staging sitemap whose live address is not among the live pages compared."""
    disc = core.discover_sitemaps(stage_session, stage_base, timeout)
    if disc["error"] or disc["fallback"]:
        return pd.DataFrame(columns=["URL", "Live Address After Launch"])
    _, entries = core.read_sitemaps(stage_session, disc, timeout)
    out = []
    for e in entries:
        live = tech.map_url(e["URL"], stage_base, live_base, back)
        if crawl.crawl_key(live) not in live_set:
            out.append({"URL": e["URL"], "Live Address After Launch": live})
    return pd.DataFrame(out, columns=["URL", "Live Address After Launch"]).drop_duplicates("URL").reset_index(drop=True)


def run(form: dict, settings: dict):
    live_base, stage_base = tech.base_of(form["live"]), tech.base_of(form["stage"])
    if not live_base or not stage_base:
        st.warning("Enter both addresses, for example https://example.com and https://staging.example.com")
        return
    if core.host_key(live_base) == core.host_key(stage_base) and urlsplit(live_base).path == urlsplit(stage_base).path:
        st.warning("The live and staging addresses are the same. Enter the staging site's own address.")
        return
    repl = tech.parse_replacements(form["replace"])
    back = [(b, a) for a, b in repl]
    auth = (form["user"].strip(), form["password"]) if form["user"].strip() else None
    with st.spinner("Finding the live pages..."):
        urls, explicit, note, error = live_urls(form["source"], live_base, form["text"], settings)
    if error:
        st.error(error)
        return
    if not urls:
        st.warning("No live pages were found to compare. " + note)
        return
    if len(urls) > settings["max_urls"]:
        note += f" The first {settings['max_urls']:,} are compared; raise Most URLs to check in the sidebar for more."
        urls = urls[: settings["max_urls"]]
    stage_urls = [explicit.get(u) or tech.map_url(u, live_base, stage_base, repl) for u in urls]

    live_session = ui.session(settings)
    stage_session = core.make_session(settings["workers"], settings["user_agent"], settings.get("headers"), auth)
    live_rows, stage_rows = {}, {}
    st.caption("Checking the live pages")
    ui.run_checks(urls, settings, live_rows, ui.robots(settings), None, live_session, toast=False)
    # staging pages are read without robots.txt: a staging robots.txt usually blocks everything on purpose
    ignore = core.RobotsCache()
    ignore.store(core.origin_of(stage_base), 404)
    st.caption("Checking the staging pages")
    host = urlsplit(stage_base).netloc
    ui.run_checks(stage_urls, settings, stage_rows, ignore, tech.staging_hook(host), stage_session, toast=False)
    robots_text = {"Live": fetch_robots(live_session, live_base, settings["timeout"]),
                   "Staging": fetch_robots(stage_session, stage_base, settings["timeout"])}
    result = tech.compare_sites([live_rows[i] for i in sorted(live_rows)], [stage_rows[i] for i in sorted(stage_rows)],
                                live_base, stage_base, back, robots_text)
    if form["new_pages"]:
        with st.spinner("Reading the staging sitemap for new pages..."):
            result["new"] = only_on_staging(stage_session, stage_base, live_base, back,
                                            {crawl.crawl_key(u) for u in urls}, settings["timeout"])
        result["numbers"]["Only on staging"] = len(result["new"])
    state = st.session_state
    state["sv_result"], state["sv_run_id"] = result, time.time()
    state["sv_info"] = {"Live site": live_base, "Staging site": stage_base, "Pages from": form["source"],
                        **ui.run_info(settings), "Staging login": "Used" if auth else "Not used"}
    state["sv_note"] = note
    st.toast("Comparison complete", icon="✅")


def results(result: dict):
    state = st.session_state
    run_id, info = state.get("sv_run_id"), state.get("sv_info", {})
    st.caption(state.get("sv_note", ""))
    ui.cards(result["numbers"])
    st.subheader("Launch checklist")
    checklist = result["checklist"]
    if checklist.empty:
        st.success("No launch problems were found in the pages compared.")
    else:
        st.dataframe(checklist.assign(Severity=checklist["Severity"].map(core.SEV_ICON)), width="stretch", hide_index=True,
                     height=ui.table_height(len(checklist), 400),
                     column_config={"What to do": st.column_config.TextColumn(width="large")})
    pages, changes = result["pages"], result["changes"]
    missing = pages[pages["Result"].str.startswith("Missing")]
    names = [f"Pages ({len(pages):,})", f"All changes ({len(changes):,})", f"Missing on staging ({len(missing):,})"]
    new = result.get("new")
    if new is not None:
        names.append(f"Only on staging ({len(new):,})")
    names.append("robots.txt")
    tabs = st.tabs(names)
    with tabs[0]:
        labels = {"changed": "Pages with changes", "all": "All pages"}
        show = st.radio("Show", list(labels), format_func=labels.get, horizontal=True, key=f"sv_show_{run_id}")
        view = pages[pages["Result"] != "Same"] if show == "changed" else pages
        st.dataframe(view.assign(Severity=view["Severity"].map(SEV_ICON)), width="stretch", hide_index=True,
                     height=ui.table_height(len(view), 480),
                     column_config={"Live URL": LINK("Live URL", pinned=True, width="medium"),
                                    "Staging URL": LINK("Staging URL", width="medium")})
    with tabs[1]:
        if changes.empty:
            st.success("Every compared field is the same on live and staging.")
        else:
            c1, c2 = st.columns(2)
            fields = c1.multiselect("Fields", sorted(changes["Field"].unique()), default=[], placeholder="All fields",
                                    key=f"sv_fields_{run_id}")
            sevs = c2.multiselect("Priority", [core.CRITICAL, core.WARNING, core.NOTICE], default=[],
                                  placeholder="All", key=f"sv_sev_{run_id}")
            view = changes
            if fields:
                view = view[view["Field"].isin(fields)]
            if sevs:
                view = view[view["Severity"].isin(sevs)]
            st.dataframe(view.assign(Severity=view["Severity"].map(core.SEV_ICON)), width="stretch", hide_index=True,
                         height=ui.table_height(len(view), 480),
                         column_config={"Live URL": LINK("Live URL", pinned=True, width="medium"),
                                        "Live": st.column_config.TextColumn(width="medium"),
                                        "Staging": st.column_config.TextColumn(width="medium"),
                                        "Note": st.column_config.TextColumn(width="large")})
            st.caption("Canonical tags and redirects on staging are compared after swapping the staging address back "
                       "to the live one. Word counts, headings and links count as changed only when they differ a lot.")
    with tabs[2]:
        if missing.empty:
            st.success("Every live page compared exists on staging.")
        else:
            st.dataframe(missing[["Live URL", "Staging URL", "Result"]], width="stretch", hide_index=True,
                         height=ui.table_height(len(missing), 460),
                         column_config={"Live URL": LINK("Live URL", pinned=True, width="medium"),
                                        "Staging URL": LINK("Staging URL", width="medium")})
            st.caption("Add each page to the new site, or 301 redirect it to its closest new page at launch. After "
                       "launch, test the redirects with the Redirect check tool.")
    n = 3
    if new is not None:
        with tabs[n]:
            if new.empty:
                st.info("The staging sitemap has no pages that are missing from the live site (or no staging sitemap was found).")
            else:
                st.dataframe(new, width="stretch", hide_index=True, height=ui.table_height(len(new), 460),
                             column_config={"URL": LINK("URL", pinned=True, width="medium")})
                st.caption("New pages: add them to the XML sitemap and link to them from related pages at launch.")
        n += 1
    with tabs[n]:
        rb = result.get("robots", {})
        c1, c2 = st.columns(2)
        for col, name in ((c1, "Live"), (c2, "Staging")):
            col.markdown(f"**{name} robots.txt**")
            col.code(rb.get(name) or "(not found)", language=None)
    row = st.container(horizontal=True)
    brand = ui.branding()
    ui.download(row, "⬇ Download launch report (Word)", lambda: tech.staging_report(result, info, brand),
                "staging-vs-live-report.docx", ui.DOCX_MIME, "sv_docx", run_id, heavy=True)
    ui.download(row, "⬇ Download Excel", lambda: tech.staging_excel(result, info), "staging-vs-live.xlsx",
                core.XLSX_MIME, "sv_xlsx", run_id, heavy=True)


def main():
    settings = ui.crawl_settings(default_max=500, limit=10_000)
    ui.page_header("staging-vs-live", "Staging vs live", DESCRIPTION)

    with st.container(key="deck_staging"):
        c1, c2 = st.columns(2)
        live = c1.text_input("Live site", placeholder="https://example.com")
        stage = c2.text_input("Staging site", placeholder="https://staging.example.com   or   https://example.com/new")
        l1, l2, l3 = st.columns(3)
        user = l1.text_input("Staging login: user name", help="For a staging site behind a browser login box. "
                                                               "Leave empty if staging is open.")
        password = l2.text_input("Staging login: password", type="password")
        new_pages = l3.checkbox("Also list pages only on staging", value=True,
                                help="Reads the staging sitemap and lists pages the live site does not have.")
        source = st.radio("Which pages to compare", SOURCES, horizontal=True)
        text = ""
        if source == SOURCES[2]:
            text = st.text_area("Live URLs, one per line", height=130,
                                placeholder="https://example.com/services/seo\n"
                                            "https://example.com/old-page, https://staging.example.com/new-page",
                                help="Add a comma and a staging URL when a page has a new address on staging.")
        with st.expander("Address changes on staging (optional)"):
            replace = st.text_area("Find => replace, one per line", height=90, key="sv_replace",
                                   placeholder="/blog/ => /resources/\n.html => /",
                                   help="Applied to every staging address after the domain is swapped, for sites "
                                        "where the URL structure changes with the redesign.")
        go = st.button("Compare sites", type="primary")

    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            run({"live": live, "stage": stage, "user": user, "password": password, "new_pages": new_pages,
                 "source": source, "text": text, "replace": replace}, settings)

    result = st.session_state.get("sv_result")
    if not result:
        ui.covers("What the comparison covers", COVERS)
        return
    results(result)


if __name__ == "__main__":
    main()
