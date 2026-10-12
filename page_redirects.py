"""
Redirect check - for a site migration: does each old URL redirect, in one step, to the new URL you expect?
The rules are in seo_checks.py.
"""

import time

import streamlit as st

import seo_checks as checks
import seo_core as core
import seo_ui as ui

DESCRIPTION = (
    "Paste old URLs with the new URL each should land on. The check follows every redirect and reports whether "
    "it ends at the right page, in one permanent step."
)
COVERS = [
    ("Correct", "A single 301 or 308 redirect that lands on the expected URL, which answers 200."),
    ("Need attention", "The right destination, but through a temporary redirect or a chain of redirects."),
    ("Wrong or broken", "Not redirected, redirected somewhere else, redirect loops and redirects that end on an error."),
    ("Small differences", "Lands on the expected page apart from http or https, www, letter case or a trailing slash."),
    ("Expected URL status", "When a redirect misses, whether the expected new URL itself works."),
    ("Full chain", "Every hop with its status code, for each old URL."),
]
EXAMPLE = "https://example.com/old-page, https://example.com/new-page\nhttps://example.com/old-blog/post, /blog/post"
SEV_COLORS = {"Correct": ui.GOOD, "Need attention": ui.WARN, "Wrong or broken": ui.BAD}


def main():
    settings = ui.crawl_settings(default_max=5_000, limit=50_000)
    ui.page_header("redirect-check", "Redirect check", DESCRIPTION)

    with st.container(key="deck_redirects"):
        c1, c2 = st.columns([3, 2])
        text = c1.text_area("Old URL and expected new URL, one pair per line", height=170, placeholder=EXAMPLE,
                            help="Separate the two with a comma, a tab or a | sign. The new URL can be a path such as /new-page.")
        file = c2.file_uploader("Or upload a redirect map", type=["csv", "txt", "xlsx", "xls"],
                                help="CSV or XLSX with old URLs in the first column and new URLs in the second.")
        go = st.button("Check redirects", type="primary")

    state = st.session_state
    if go:
        try:
            pairs = checks.parse_pairs(text, file, second_is_url=True)
        except Exception as e:
            st.error(f"The uploaded file could not be read: {e}")
            pairs = []
        pairs = pairs[: settings["max_urls"]]
        if not pairs:
            st.warning("Add at least one old URL, ideally with the new URL it should redirect to.")
        else:
            session = core.make_session(settings["workers"], settings["user_agent"])
            on_progress, done = ui.progress("Redirects checked")
            state["rd_df"] = checks.check_redirects(session, pairs, settings, on_progress)
            done()
            state["rd_id"] = time.time()
            state["rd_info"] = ui.run_info(settings)
            st.toast("Check complete", icon="✅")

    df = state.get("rd_df")
    if df is None:
        ui.covers("What the check reports", COVERS)
        return

    numbers = checks.redirect_numbers(df)
    ui.cards(numbers)
    ui.status_bar({k: numbers[k] for k in SEV_COLORS}, SEV_COLORS, f"How the {len(df):,} old URLs redirect")

    st.subheader("Results")
    summary = checks.redirect_summary(df)
    picked = ui.pick_issue(summary, f"rd_pick_{state['rd_id']}", "Tick a result to show only those URLs.",
                           name_col="Result")
    view = df if not picked else df[df["Result"] == picked[1]]
    shown = view.assign(Severity=view["Severity"].map({**core.SEV_ICON, "OK": "✅ OK"}))
    st.dataframe(shown, width="stretch", hide_index=True, height=min(38 + 35 * (len(shown) + 1), 480),
                 column_config={"Old URL": st.column_config.LinkColumn("Old URL", pinned=True, width="medium"),
                                "Expected URL": st.column_config.LinkColumn("Expected URL"),
                                "Final URL": st.column_config.LinkColumn("Final URL")})
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download CSV", lambda: core.to_csv_bytes(view), "redirect-check.csv", "text/csv",
                "rd_csv", (state["rd_id"], picked))
    ui.download(row, "⬇ Download Excel", lambda: checks.redirects_excel_bytes(df, state.get("rd_info", {})),
                "redirect-check.xlsx", core.XLSX_MIME, "rd_xlsx", state["rd_id"], heavy=True)


if __name__ == "__main__":
    main()
