"""
SEO Audit Toolkit - shared screen code (look, sidebar, results view)

Used by every tool screen (page_*.py) so they all look and behave the same.

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
import seo_page as page
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

/* ---- page audit: score and area meters */
.tk-score { display: grid; grid-template-columns: minmax(180px, 240px) 1fr; gap: 2.5rem; align-items: center;
            margin: .5rem 0 1rem; }
.tk-score-num { font-size: 4rem; line-height: 1; font-weight: 600; letter-spacing: -.03em; margin: 0; }
.tk-score-num span { font-size: 1.25rem; font-weight: 500; opacity: .6; letter-spacing: 0; margin-left: .2rem; }
.tk-score-grade { font-size: 1.05rem; font-weight: 600; margin: .35rem 0 .2rem; }
.tk-score-sub { font-size: .875rem; opacity: .75; margin: 0; line-height: 1.45; }
.tk-meters { display: grid; gap: .55rem; }
.tk-meter { display: grid; grid-template-columns: 11rem 1fr 4.5rem; gap: .75rem; align-items: center; font-size: .9rem; }
.tk-meter-track { height: 10px; border-radius: 5px; background: rgba(128, 128, 128, .18); overflow: hidden; }
.tk-meter-fill { height: 100%; border-radius: 5px; }
.tk-meter-val { text-align: right; font-variant-numeric: tabular-nums; opacity: .85; }
@media (max-width: 760px) { .tk-score { grid-template-columns: 1fr; gap: 1rem; } .tk-meter { grid-template-columns: 8rem 1fr 4rem; } }

/* ---- search result preview (an approximation, set in Arial like the real thing) */
.tk-serps { display: grid; grid-template-columns: 1.3fr 1fr; gap: 1rem; margin: .25rem 0 .5rem; }
.tk-serp { border: 1px solid BORDER; border-radius: .75rem; padding: .9rem 1.1rem; font-family: Arial, Helvetica, sans-serif; }
.tk-serp-label { font-family: inherit; font-size: .75rem; opacity: .6; margin: 0 0 .45rem; }
.tk-serp-crumb { font-size: 13px; color: #4d5156; margin: 0 0 .15rem; }
.tk-serp-title { font-size: 20px; line-height: 1.3; color: #1a0dab; margin: 0 0 .2rem; }
.tk-serp.mobile .tk-serp-title { font-size: 18px; }
.tk-serp-desc { font-size: 14px; line-height: 1.58; color: #4d5156; margin: 0; }
@media (max-width: 760px) { .tk-serps { grid-template-columns: 1fr; } }

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
    branding_settings()
    st.sidebar.divider()


def branding_settings():
    """Report branding in the sidebar, under the tool list (called from frame(), so it is always in the same place).

    The values are kept under brand_saved as well as in the widgets: Streamlit drops a widget's value in
    some runs (for example while switching tools), and the branding must survive that."""
    state = st.session_state
    defaults = report.brand_defaults()
    saved = state.setdefault("brand_saved", {"agency": defaults["agency"], "client": "", "logo": b"", "logo_name": ""})

    def keep_text(field):
        saved[field] = (state.get(f"brand_{field}") or "").strip()

    def keep_logo():
        f = state.get("brand_logo")
        saved["logo"], saved["logo_name"] = (f.getvalue(), f.name) if f is not None else (b"", "")

    def drop_logo():
        saved["logo"], saved["logo_name"] = b"", ""

    with st.sidebar:
        with st.expander("Report branding"):
            st.text_input("Agency name", value=saved["agency"], key="brand_agency", on_change=keep_text, args=("agency",),
                          help="Shown in the header of every Word report. Set a permanent default in seo_report.py.")
            st.text_input("Client name", value=saved["client"], key="brand_client", on_change=keep_text, args=("client",),
                          help="Shown as 'Prepared for ...' on every Word report.")
            st.file_uploader("Logo (PNG or JPG)", type=["png", "jpg", "jpeg"], key="brand_logo", on_change=keep_logo,
                             help="For a permanent logo, save it as report_logo.png in the tool's folder.")
            if saved["logo"] and state.get("brand_logo") is None:
                st.caption(f"Logo in use: {saved['logo_name']}")
                st.button("Remove logo", key="brand_logo_remove", on_click=drop_logo)
            elif not saved["logo"] and defaults["logo"]:
                st.caption("Using report_logo.png from the tool's folder.")


def branding() -> dict:
    """The branding for Word reports: what was entered under Report branding, or the defaults in seo_report.py."""
    defaults = report.brand_defaults()
    saved = st.session_state.get("brand_saved")
    if not saved:
        return defaults
    return {"agency": saved["agency"], "client": saved["client"], "logo": saved["logo"] or defaults["logo"]}


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


MOBILE_CHOICES = {"Off": "", "As Chrome browsers": "chrome", "As Googlebot": "googlebot"}


def page_opts(score: bool, mobile: str, settings: dict, robots) -> dict:
    """Page-check options for the on-page score and the smartphone vs desktop comparison."""
    return page.row_hook(score, mobile, settings, robots)


def overview_cols(base: list, extras: dict) -> list:
    cols = core.overview_with_score(base, extras.get("score", False))
    if extras.get("mobile"):
        at = cols.index("Severity") if "Severity" in cols else len(cols)
        cols = cols[:at] + ["Mobile Match"] + cols[at:]
    return cols


def score_section(df: pd.DataFrame, site: str = "", limit: int = 25) -> dict:
    """Report section listing the pages with the lowest on-page score."""
    if "On-page Score" not in df.columns:
        return {}
    scored = df[df["On-page Score"].notna()].sort_values("On-page Score").head(limit)
    if scored.empty:
        return {}
    average = core.headline_numbers(df).get("Average on-page score")
    intro = ((f"The average score of the pages that answered 200 is {average} out of 100. " if average is not None else "")
             + "Each score comes from the same checks as the Page audit tool, without the link checks. "
               "Run a Page audit on a page for its full list of fixes.")
    return {"title": "Pages with the lowest on-page score", "intro": intro,
            "header": ["Page", "Score", "Grade", "Weakest area"],
            "rows": [[report.url_label(r["URL"], site), str(int(r["On-page Score"])), r["Grade"], r["Weakest Area"]]
                     for r in scored.to_dict("records")]}


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
# Results of a page check (same for every tool)
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
            "On-page Score": st.column_config.ProgressColumn("On-page Score", min_value=0, max_value=100, format="%d"),
        },
    )
    if "On-page Score" in cols:
        st.caption("The on-page score uses the same checks as the Page audit tool, without the link checks. "
                   "Run a Page audit on one page for its full list of fixes.")
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
    brand = branding()

    def build_word():
        sections = list(report_sections() if report_sections else [])
        scores = score_section(df, site)
        if scores:
            sections.insert(0, scores)
        return report.build_report(title, site, full_info, df, sections or None, brand=brand)
    download(row, "⬇ Download client report (Word)", build_word,
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


def level_color(pct: float) -> str:
    return GOOD if pct >= 80 else (WARN if pct >= 50 else BAD)


def check_counts(counts: dict) -> str:
    """'27 checks passed, 3 need attention, 8 failed' with the right singular and plural."""
    passed, warn, fail = counts.get("Pass", 0), counts.get("Warning", 0), counts.get("Fail", 0)
    return (f"{passed} check{'' if passed == 1 else 's'} passed, {warn} need{'s' if warn == 1 else ''} attention, "
            f"{fail} failed")


def score_block(score: int, grade: str, counts: dict, areas: pd.DataFrame, blocked: bool, loaded: bool = True):
    """The page score as a large number, with one meter per area. Every meter shows its points as text."""
    meters = "".join(
        f'<div class="tk-meter"><span>{esc(a)}</span><div class="tk-meter-track" role="img" '
        f'aria-label="{esc(a)}: {pts:g} of {out:g} points"><div class="tk-meter-fill" '
        f'style="width: {pct}%; background: {level_color(pct)}"></div></div>'
        f'<span class="tk-meter-val">{pts:g} / {out:g}</span></div>'
        for a, pts, out, pct in zip(areas["Area"], areas["Points"], areas["Out Of"], areas["Score (%)"])
    )
    words = {"A": "Strong", "B": "Good", "C": "Needs work", "D": "Weak", "F": "Poor"}
    sub = check_counts(counts) + "."
    if not loaded:
        sub += " The page did not load."
    elif blocked:
        sub += " A blocker caps the score."
    st.html(
        f'<div class="tk-score"><div><p class="tk-score-num">{score}<span>/ 100</span></p>'
        f'<p class="tk-score-grade">Grade {esc(grade)}, {words.get(grade, "")}</p><p class="tk-score-sub">{esc(sub)}</p></div>'
        f'<div class="tk-meters">{meters}</div></div>'
    )


def serp_block(prev: dict):
    cards = "".join(
        f'<div class="tk-serp {kind}"><p class="tk-serp-label">{label}</p><p class="tk-serp-crumb">{esc(prev["breadcrumb"])}</p>'
        f'<p class="tk-serp-title">{esc(prev[kind + "_title"])}</p><p class="tk-serp-desc">{esc(prev[kind + "_desc"])}</p></div>'
        for kind, label in (("desktop", "Desktop"), ("mobile", "Mobile"))
    )
    st.html(f'<div class="tk-serps">{cards}</div>')


def table_height(n: int, most: int = 420) -> int:
    return min(38 + 35 * max(n, 1), most)


def content_view(read: dict, content: dict, headings: list, empty_headings: str = "The page has no headings (H1 to H6)."):
    """Readability, content numbers, top words and phrases, and the heading outline (Page audit, Content check)."""
    st.markdown("**Readability**")
    if read.get("Reading ease") is not None:
        cards({f"Reading ease ({read['Level'].lower()})": f"{read['Reading ease']:g}",
               "Words per sentence": f"{read['Average words per sentence']:g}",
               "Long sentences": f"{read['Long sentences']} ({read['Long sentences (%)']:g}%)",
               "Long paragraphs": read["Long paragraphs"]})
        st.caption(f"Flesch reading ease, 0 to 100: higher is easier, and 60 or more suits most audiences. "
                   f"Long means more than {page.LONG_SENTENCE_WORDS} words in a sentence or "
                   f"{page.LONG_PARAGRAPH_WORDS} in a paragraph. The score is an estimate for English text.")
    else:
        st.info(read.get("status") or "Not scored.")
    if read.get("examples"):
        with st.expander(f"The longest sentences to shorten ({len(read['examples'])} shown)"):
            for sentence in read["examples"]:
                st.text(sentence)

    st.markdown("**Content**")
    cards(content["numbers"])
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Most used words (common words such as 'the' and 'and' are left out)")
        st.dataframe(content["words"], width="stretch", hide_index=True, height=table_height(len(content["words"]), 390),
                     column_config={"Density (%)": st.column_config.NumberColumn(format="%.2f%%")})
    with c2:
        st.caption("Phrases of two and three words used at least twice")
        if content["phrases"].empty:
            st.info("No phrase is used more than once.")
        else:
            st.dataframe(content["phrases"], width="stretch", hide_index=True,
                         height=table_height(len(content["phrases"]), 390))

    st.markdown("**Heading outline**")
    if not headings:
        st.info(empty_headings)
    else:
        def indent(level):
            return "\u2003" * (int(level[1]) - 1) if len(level) == 2 and level[1].isdigit() else ""
        outline = pd.DataFrame([{"Level": h["Level"], "Heading": indent(h["Level"]) + (h["Heading"] or "(empty)")}
                                for h in headings])
        st.dataframe(outline, width="stretch", hide_index=True, height=table_height(len(outline), 420))


def advice_list(advice: list, all_good: str = "No problems found."):
    """[(short label, advice), ...] as a short list."""
    if not advice:
        st.success(all_good)
        return
    st.markdown("\n".join(f"- **{esc(label)}.** {esc(text)}" for label, text in advice))


def urls_from_sitemap(target: str, settings: dict, include: str = "", exclude: str = ""):
    """The URLs in a site's sitemap (found from a domain or a sitemap URL). Returns (urls, note, robots or None)."""
    session = core.make_session(6, settings["user_agent"])
    with st.spinner("Reading the sitemap..."):
        disc = core.discover_sitemaps(session, target, settings["timeout"])
        if disc["error"]:
            return [], disc["error"], None
        files, entries = core.read_sitemaps(session, disc, settings["timeout"])
    inv = core.build_inventory(disc, files, entries)
    found = inv["urls"]["URL"].tolist()
    inc = [p.strip() for p in (include or "").split(",") if p.strip()]
    exc = [p.strip() for p in (exclude or "").split(",") if p.strip()]
    urls = [u for u in found if (not inc or any(p in u for p in inc)) and not any(p in u for p in exc)]
    source = f"the {inv['fallback'].lower()} (no XML sitemap was found)" if inv["fallback"] else "the sitemap"
    note = f"{len(found):,} URLs found in {source}" + (f", {len(urls):,} match the filter." if (inc or exc) else ".")
    robots = core.RobotsCache()
    robots.store(disc["origin"], disc["robots_status"], disc["robots_text"], disc["robots_error"])
    return urls, note, robots


def rich_results_buttons(url: str):
    from urllib.parse import quote
    row = st.container(horizontal=True)
    row.link_button("Test in Google's Rich Results Test", f"https://search.google.com/test/rich-results?url={quote(url, safe='')}")
    row.link_button("Open in the Schema Markup Validator", f"https://validator.schema.org/#url={quote(url, safe='')}")


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
