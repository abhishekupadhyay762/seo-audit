"""
SEO Audit Toolkit - shared screen code (look, sidebar, results view)

Used by both tools so they look and behave the same:
  page_sitemap.py   Sitemap audit
  page_bulk.py      Bulk URL check

The colours and fonts come from .streamlit/config.toml. The CSS below only styles
the parts Streamlit has no setting for (page header, input panel, status bar).
"""

import time
from datetime import datetime

import pandas as pd
import streamlit as st

import seo_checks as checks
import seo_core as core
import seo_crawl as crawl
import seo_report as report

APP_NAME = "SEO Audit Toolkit"     # shown in the sidebar and the browser tab
APP_SLUG = "seo-audit-toolkit"     # shown in the breadcrumb line above each page title

# Status colours for the stacked bars (always shown with a label and a count, never colour alone)
GOOD, WARN, SERIOUS, BAD, GREY = "#0ca30c", "#fab219", "#ec835a", "#d03b3b", "#898781"
STATUS_COLORS = {"200 OK": GOOD, "Redirect": WARN, "4xx": BAD, "5xx or failed": SERIOUS, "Other": GREY}

CSS = """
<style>
/* ---- sidebar brand */
.tk-brand { display: flex; align-items: center; gap: .65rem; padding: .1rem 0 .35rem; }
.tk-mark { flex: none; width: 30px; height: 30px; border-radius: 7px; background: PRIMARY; display: flex;
           flex-direction: column; justify-content: center; gap: 3px; padding: 0 7px; box-sizing: border-box; }
.tk-mark span { display: block; height: 3px; border-radius: 2px; background: #fff; }
.tk-mark span:nth-child(1) { width: 16px; }
.tk-mark span:nth-child(2) { width: 12px; margin-left: 4px; }
.tk-mark span:nth-child(3) { width: 8px; margin-left: 4px; }
.tk-brand-name { font-weight: 600; font-size: 1.05rem; line-height: 1.2; letter-spacing: -.01em; }
.tk-brand-sub { font-size: .8rem; line-height: 1.3; opacity: .7; }

/* ---- page header, laid out like a search result: address line, title, description */
.tk-snippet { max-width: 46rem; margin: 0 0 .5rem; }
.tk-crumb { font-family: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace; font-size: .8rem; opacity: .7; margin: 0 0 .2rem; }
.tk-title { font-size: 2rem; line-height: 1.2; font-weight: 500; letter-spacing: -.015em; margin: 0 0 .4rem; padding: 0; color: PRIMARY; }
.tk-desc { font-size: 1rem; line-height: 1.55; opacity: .82; margin: 0; }

/* ---- input panel: st.container(key="deck...") */
[class*="st-key-deck"] { background: PANEL; border: 1px solid BORDER; border-radius: .75rem; padding: 1.1rem 1.25rem 1.25rem; }

/* ---- "what the report covers": a two-column list of names with one-line descriptions */
.tk-covers-title { font-size: 1.05rem; font-weight: 600; margin: 1.25rem 0 .9rem; }
.tk-links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.1rem 3rem; max-width: 56rem; }
.tk-link-t { font-size: 1rem; font-weight: 600; line-height: 1.3; margin: 0 0 .15rem; }
.tk-link-d { font-size: .9rem; line-height: 1.5; opacity: .78; margin: 0; }
@media (max-width: 760px) { .tk-links { grid-template-columns: 1fr; } .tk-title { font-size: 1.6rem; } }

/* ---- status bar: one stacked bar, 2px gaps, legend with counts */
.tk-status { margin: .35rem 0 .25rem; }
.tk-status-label { font-size: .875rem; opacity: .75; margin: 0 0 .45rem; }
.tk-bar { display: flex; gap: 2px; height: 12px; }
.tk-bar span { display: block; min-width: 4px; height: 100%; }
.tk-bar span:first-child { border-radius: 4px 0 0 4px; }
.tk-bar span:last-child { border-radius: 0 4px 4px 0; }
.tk-bar span:only-child { border-radius: 4px; }
.tk-legend { display: flex; flex-wrap: wrap; gap: .35rem 1.5rem; margin: .6rem 0 0; font-size: .875rem; }
.tk-legend span { display: inline-flex; align-items: center; gap: .45rem; white-space: nowrap; }
.tk-legend i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.tk-legend b { font-weight: 600; }
.tk-legend .tk-zero { opacity: .5; }

/* ---- sidebar section names */
.tk-nav-group { font-size: .78rem; font-weight: 600; opacity: .6; margin: .6rem 0 .1rem .5rem; }
</style>
"""

MARK = '<div class="tk-mark" aria-hidden="true"><span></span><span></span><span></span></div>'


def palette() -> dict:
    """Colours for the custom parts, taken from .streamlit/config.toml so one change there restyles everything."""
    primary = st.get_option("theme.primaryColor")
    if primary:
        return {
            "PRIMARY": primary,
            "PANEL": st.get_option("theme.secondaryBackgroundColor") or "#f3f4f9",
            "BORDER": st.get_option("theme.borderColor") or "#d8dbe8",
        }
    # The theme file is missing: use values that stay readable on a light or a dark page
    return {"PRIMARY": "#4f6bed", "PANEL": "rgba(128, 128, 128, .08)", "BORDER": "rgba(128, 128, 128, .28)"}


def esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


# --------------------------------------------------------------------------
# Frame: CSS, sidebar brand and tool links (called once from the main file)
# --------------------------------------------------------------------------
def frame(groups: dict):
    """CSS, the brand and the tool links. groups = {"Section name": [st.Page, ...], ...}"""
    css = CSS
    for token, value in palette().items():
        css = css.replace(token, value)
    st.html(css)
    with st.sidebar:
        st.html(
            f'<div class="tk-brand">{MARK}<div><div class="tk-brand-name">{esc(APP_NAME)}</div>'
            '<div class="tk-brand-sub">Sitemap, crawl and page checks</div></div></div>'
        )
        for name, pages in groups.items():
            st.html(f'<p class="tk-nav-group">{esc(name)}</p>')
            for page in pages:
                st.page_link(page)
        st.divider()


def crawl_settings(default_max: int = 1000, limit: int = 20_000, show_max: bool = True) -> dict:
    """The sidebar settings every tool shares. Returns them as a dict."""
    with st.sidebar:
        st.markdown("**Crawl settings**")
        ua_name = st.selectbox(
            "Crawl as", list(core.USER_AGENTS),
            help="The User-Agent sent with each request. If a site answers 403 to the tool default, try Chrome. "
                 "Many sites block requests that only claim to be Googlebot, so use those to compare, not as a fix.",
        )
        max_urls = st.number_input("Most URLs to check", 10, limit, default_max, step=100) if show_max else default_max
        workers = st.slider("Requests at the same time", 1, 20, 10,
                            help="Higher is faster, but some sites block many requests at once.")
        timeout = st.slider("Wait per page (seconds)", 5, 60, 15)
        delay = st.number_input("Pause per request (sec)", 0.0, 5.0, 0.0, step=0.1,
                                help="Add a pause before each request for slow or sensitive servers.")
    return {"ua_name": ua_name, "user_agent": core.USER_AGENTS[ua_name], "max_urls": int(max_urls),
            "workers": workers, "timeout": timeout, "delay": delay}


def page_header(slug: str, title: str, description: str):
    st.html(
        f'<div class="tk-snippet"><p class="tk-crumb">{esc(APP_SLUG)} › {esc(slug)}</p>'
        f'<h1 class="tk-title">{esc(title)}</h1><p class="tk-desc">{esc(description)}</p></div>'
    )


def covers(title: str, items: list):
    """Empty state: what the report will contain. items = [(name, one-line description), ...]"""
    links = "".join(
        f'<div><p class="tk-link-t">{esc(name)}</p><p class="tk-link-d">{esc(text)}</p></div>' for name, text in items
    )
    st.html(f'<p class="tk-covers-title">{esc(title)}</p><div class="tk-links">{links}</div>')


def cards(numbers: dict):
    cols = st.columns(len(numbers))
    for col, (label, value) in zip(cols, numbers.items()):
        col.metric(label, f"{value:,}" if isinstance(value, int) else value)


def status_bar(parts: dict, colors: dict = None, label: str = None):
    """One stacked bar of parts that add up to a whole. Counts are in the legend, so colour is never alone."""
    colors = colors or STATUS_COLORS
    total = sum(parts.values())
    if not total:
        return
    label = label or f"How the {total:,} URLs answered on the first request"
    shown = {k: v for k, v in parts.items() if v > 0}
    bar = "".join(
        f'<span style="flex: {v} 1 0; background: {colors[k]}" title="{esc(k)}: {v:,} ({100 * v / total:.1f}%)"></span>'
        for k, v in shown.items()
    )
    legend = "".join(
        f'<span class="{"" if v else "tk-zero"}"><i style="background: {colors[k]}"></i>{esc(k)} <b>{v:,}</b></span>'
        for k, v in parts.items() if v or k != "Other"
    )
    summary = ", ".join(f"{k} {v}" for k, v in parts.items() if v)
    st.html(
        f'<div class="tk-status"><p class="tk-status-label">{esc(label)}</p>'
        f'<div class="tk-bar" role="img" aria-label="{esc(summary)}">{bar}</div><div class="tk-legend">{legend}</div></div>'
    )


# --------------------------------------------------------------------------
# Running a check with a progress bar
# --------------------------------------------------------------------------
def progress(what: str):
    """A progress bar. Returns (on_progress(n, total), done())."""
    bar = st.progress(0.0, text="Starting...")
    started = time.time()

    def on_progress(n, total):
        if not total:
            return
        eta = (time.time() - started) / max(n, 1) * (total - n)
        bar.progress(min(n / total, 1.0), text=f"{what}: {n:,} of {total:,}, about {int(eta // 60)}m {int(eta % 60)}s left")

    return on_progress, bar.empty


def run_checks(urls: list, settings: dict, results: dict, robots=None, opts=None, session=None, toast=True):
    on_progress, done = progress("URLs checked")
    core.run_audit(urls, settings["workers"], settings["timeout"], settings["delay"], settings["user_agent"],
                   results, on_progress, robots, opts, session)
    done()
    if toast:
        st.toast("Check complete", icon="✅")


def run_target_checks(rows: list, settings: dict, robots, session):
    """Canonical targets and hreflang alternates for the rows just checked."""
    on_progress, done = progress("Canonical and hreflang targets checked")
    checks.validate_targets(session, rows, robots, settings, on_progress)
    done()


def run_link_checks(rows: list, links: list, settings: dict, session, check_external: bool) -> pd.DataFrame:
    on_progress, done = progress("Link targets checked")
    df = crawl.check_links(session, links, rows, settings, check_external, on_progress)
    done()
    return df


def links_from_rows(rows: list) -> list:
    """The links found on checked pages, as (source, link, anchor, nofollow, internal). Frees the page copies."""
    out = []
    for r in rows:
        x = r["_x"]
        source = r["Final URL"] or r["URL"]
        site = core.host_key(source)
        for url, anchor, nofollow in x.pop("links", []):
            out.append((source, url, anchor, nofollow, core.host_key(url) == site))
    return out


def run_info(settings: dict) -> dict:
    return {"Crawled as": settings["ua_name"], "Run started (server time)": datetime.now().strftime("%Y-%m-%d %H:%M")}


def results_table(prefix: str, groups: dict = None, make_extra=None) -> pd.DataFrame:
    """Builds the results table once per run (or once per size, for a run that was stopped early).

    make_extra  optional function(rows) that returns the `extra` argument for core.finalize();
                it is only called when the table really has to be rebuilt
    """
    state = st.session_state
    results = state[f"{prefix}_results"]
    key = (state.get(f"{prefix}_run_id"), len(results))
    cached = state.get(f"{prefix}_final")
    if cached and cached[0] == key:
        return cached[1]
    rows = [results[i] for i in sorted(results)]
    df = core.finalize(rows, groups, make_extra(rows) if make_extra else None)
    state[f"{prefix}_final"] = (key, df)
    return df


# --------------------------------------------------------------------------
# Downloads and issue picking
# --------------------------------------------------------------------------
def download(col, label, build, file_name, mime, key, signature, heavy=False):
    """Download button whose file is only built when it is asked for.

    Streamlit 1.52+ builds the file when the button is clicked. Older versions cannot do
    that, so a heavy file (Excel) gets a "Prepare" button first and a light one (CSV) is
    built straight away.
    """
    # on_click="ignore": downloading must not re-run the page (keeps the other button usable)
    try:
        col.download_button(label, build, file_name, mime, key=f"{key}_on_click", on_click="ignore")
        return
    except Exception:
        pass
    if not heavy:
        col.download_button(label, build(), file_name, mime, key=f"{key}_now", on_click="ignore")
        return
    ready = st.session_state.get(f"{key}_ready")
    if ready and ready[0] == signature:
        col.download_button(label, ready[1], file_name, mime, key=f"{key}_file", on_click="ignore")
    elif col.button(label.replace("Download", "Prepare"), key=f"{key}_prepare"):
        with st.spinner("Building the file..."):
            st.session_state[f"{key}_ready"] = (signature, build())
        st.rerun()


def pick_issue(summary: pd.DataFrame, key: str, hint: str, percent_col: str = None, name_col: str = "Issue"):
    """Shows an issue table where one row can be ticked. Returns (severity, issue) or None."""
    st.caption(hint)
    shown = summary.assign(Severity=summary["Severity"].map(core.SEV_ICON))
    config = {percent_col: st.column_config.NumberColumn(format="%.1f%%")} if percent_col else None
    event = st.dataframe(
        shown, width="stretch", hide_index=True, height=min(38 + 35 * len(shown), 318),
        on_select="rerun", selection_mode="single-row", key=key, column_config=config,
    )
    rows = event.selection.rows if event and event.selection else []
    if rows and rows[0] < len(summary):
        return summary.iloc[rows[0]]["Severity"], summary.iloc[rows[0]][name_col]
    return None


# --------------------------------------------------------------------------
# Results of a page check (same for both tools)
# --------------------------------------------------------------------------
def render_results(df: pd.DataFrame, prefix: str, groups: dict, overview_cols: list, info: dict,
                   file_stem: str, title: str, extra_sheets: list = None, site: str = "", report_sections=None):
    """Cards, status bar, issue summary, views by group, and the downloads.

    report_sections  optional function returning extra sections for the Word report (see seo_report.build_report)
    """
    state = st.session_state
    run_id = state.get(f"{prefix}_run_id")
    total = state.get(f"{prefix}_total", len(df))
    if len(df) < total:
        st.warning(f"Partial results: {len(df):,} of {total:,} URLs were checked before the run stopped.")

    cards(core.headline_numbers(df))
    status_bar(core.status_split(df))

    # ---- Issue summary (tick a row to filter the results)
    summary = core.issue_summary(df)
    picked = None
    st.subheader("Issues found")
    if summary.empty:
        st.success("No issues found in these URLs.")
    else:
        picked = pick_issue(summary, f"{prefix}_issue_{run_id}", "Tick an issue to show only the URLs that have it.", "% of URLs")

    # ---- Results
    st.subheader("Results by URL")
    views = ["Overview"] + list(groups) + ["All data"]
    view_name = st.segmented_control("View", views, default="Overview", key=f"{prefix}_view_{run_id}") or "Overview"
    sev_counts = df["Severity"].value_counts()
    n_crit, n_warn = int(sev_counts.get(core.CRITICAL, 0)), int(sev_counts.get(core.WARNING, 0))
    show_labels = {
        "all": f"All URLs ({len(df):,})",
        "critical": f"Critical ({n_crit:,})",
        "warning": f"Critical + Warning ({n_crit + n_warn:,})",
        "any": f"Any issue ({int((df['Issue Count'] > 0).sum()):,})",
    }
    show = st.radio("Show", list(show_labels), format_func=show_labels.get, horizontal=True, key=f"{prefix}_show_{run_id}")

    view = df
    if picked:
        view = view[view["_issues"].map(lambda items: picked in items)]
        st.info(f"Filtered to **{picked[1]}**, {len(view):,} URL(s). Untick the issue above to clear.")
    if show == "critical":
        view = view[view["Severity"] == core.CRITICAL]
    elif show == "warning":
        view = view[view["Severity"].isin([core.CRITICAL, core.WARNING])]
    elif show == "any":
        view = view[view["Issue Count"] > 0]

    all_cols = core.all_cols(groups)
    if view_name == "Overview":
        cols = overview_cols
    elif view_name == "All data":
        cols = all_cols
    else:
        cols = ["URL"] + groups[view_name]
    table = view[cols]
    if "Severity" in cols:
        table = table.assign(Severity=table["Severity"].map(core.SEV_ICON))
    st.dataframe(
        table, width="stretch", height=520, hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("URL", pinned=True, width="medium"),
            "Final URL": st.column_config.LinkColumn("Final URL"),
            "Canonical URL": st.column_config.LinkColumn("Canonical URL"),
            "Sitemap File": st.column_config.LinkColumn("Sitemap File"),
        },
    )
    st.caption(
        "For a URL that redirects, the on-page data is from the final page. Robots.txt is read as Googlebot reads it. "
        "Response time is measured from this server, so use it to compare URLs with each other."
    )

    # ---- Downloads (follow the filters above, always include every column)
    export = view.drop(columns=["_issues"]).reset_index(drop=True)
    info = dict(info)
    if picked:
        info["Filter"] = picked[1]
    elif show != "all":
        info["Filter"] = show_labels[show].rsplit(" (", 1)[0]
    view_summary = core.issue_summary(view)
    signature = (run_id, picked, show, len(export))
    row = st.container(horizontal=True)
    download(row, "⬇ Download CSV", lambda: core.to_csv_bytes(export, all_cols), f"{file_stem}.csv", "text/csv",
             f"{prefix}_csv", signature)
    download(row, "⬇ Download Excel",
             lambda: core.to_excel_bytes(export, view_summary, info, groups, title, extra_sheets),
             f"{file_stem}.xlsx", core.XLSX_MIME, f"{prefix}_xlsx", signature, heavy=True)

    # These two always cover the whole run, whatever the filters above
    full_info = dict(state.get(f"{prefix}_info", {}))
    download(row, "⬇ Download client report (Word)",
             lambda: report.build_report(title, site, full_info, df, report_sections() if report_sections else None),
             f"{file_stem}-report.docx", DOCX_MIME, f"{prefix}_docx", run_id, heavy=True)
    n_index = len(checks.sitemap_urls(df))
    if n_index:
        download(row, f"⬇ Download XML sitemap ({n_index:,} indexable URLs)", lambda: checks.sitemap_xml(df)[0],
                 "sitemap.xml" if n_index <= core.SITEMAP_URL_LIMIT else "sitemaps.zip",
                 "application/xml" if n_index <= core.SITEMAP_URL_LIMIT else "application/zip",
                 f"{prefix}_sitemap", run_id, heavy=True)
    st.caption("The Excel and CSV files follow the filters above. The client report and the XML sitemap always "
               "cover the whole run; the sitemap lists only URLs that answered 200 and are indexable.")


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def links_view(links_df: pd.DataFrame, prefix: str, file_stem: str, info: dict):
    """The link check results: summary cards, a problems-only filter and downloads."""
    if links_df is None or links_df.empty:
        st.info("No links were found on the checked pages.")
        return
    cards(crawl.link_summary(links_df))
    problem = links_df["Result"] != "OK"
    show = st.radio("Show", ["problems", "all"], horizontal=True, key=f"{prefix}_links_show",
                    format_func={"problems": f"Problems only ({int(problem.sum()):,})",
                                 "all": f"All links ({len(links_df):,})"}.get)
    view = links_df[problem] if show == "problems" else links_df
    kinds = st.multiselect("Link type", ["Internal", "External"], default=["Internal", "External"], key=f"{prefix}_links_kind")
    view = view[view["Link Type"].isin(kinds)]
    st.dataframe(view, width="stretch", hide_index=True, height=420,
                 column_config={"Source Page": st.column_config.LinkColumn("Source Page", pinned=True, width="medium"),
                                "Link URL": st.column_config.LinkColumn("Link URL", width="medium"),
                                "Final URL": st.column_config.LinkColumn("Final URL")})
    st.caption("Some sites (for example social networks) refuse automated checks; those links show as not verified "
               "rather than broken. Open them in a browser to confirm.")
    row = st.container(horizontal=True)
    download(row, "⬇ Download links (CSV)", lambda: core.to_csv_bytes(view), f"{file_stem}-links.csv", "text/csv",
             f"{prefix}_links_csv", (show, tuple(kinds)))
    download(row, "⬇ Download links (Excel)",
             lambda: checks.simple_excel("Link check", info, crawl.link_summary(links_df),
                                         [("Problem links", links_df[problem]), ("All links", links_df)]),
             f"{file_stem}-links.xlsx", core.XLSX_MIME, f"{prefix}_links_xlsx", len(links_df), heavy=True)


def broken_link_section(links_df: pd.DataFrame, limit: int = 60) -> dict:
    """Report section listing broken links."""
    if links_df is None or links_df.empty:
        return {}
    bad = links_df[links_df["Result"].map(crawl.is_broken)].head(limit)
    return {"title": "Broken links",
            "intro": f"Links that lead to an error. Showing up to {limit}; the full list is in the links download.",
            "header": ["Page", "Link", "Anchor text", "Result"],
            "rows": [[report.url_label(r["Source Page"]), r["Link URL"], r["Anchor Text"], r["Result"]]
                     for r in bad.to_dict("records")]}
