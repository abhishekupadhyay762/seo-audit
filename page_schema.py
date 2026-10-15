"""
Schema check - required and recommended schema fields for many pages, a whole sitemap, or pasted code.
The rules are in seo_page.py (SCHEMA_RULES); the checks for many pages are in seo_content.py.
"""

import time

import streamlit as st

import seo_content as content
import seo_core as core
import seo_ui as ui

DESCRIPTION = (
    "Check structured data on many pages at once, on every page in a sitemap, or in code before it is published. "
    "Shows each schema type and the required and recommended fields it is missing."
)
COVERS = [
    ("Every schema type", "Each JSON-LD item on each page, with Microdata and RDFa types listed too."),
    ("Required fields", "The fields Google needs before a type can show as a rich result, for example offers on Product."),
    ("Recommended fields", "Fields that add detail, such as image, brand and aggregateRating."),
    ("Broken JSON-LD", "Blocks that do not parse, with the line and column of the error for pasted code."),
    ("By type", "How many pages use each type, and how many of them pass."),
    ("Before publishing", "Paste JSON-LD or a page's HTML to check it before the developer puts it live."),
]
MODES = ["Pages", "Sitemap", "Paste code"]
RESULT_ICON = {"OK": "✅ OK", "Missing required fields": "❌ Missing required fields",
               "Missing recommended fields": "⚠️ Missing recommended fields", "Invalid JSON": "❌ Invalid JSON",
               "No schema": "➖ No schema", "Not read": "➖ Not read", "Not checked": "ℹ️ Not checked"}
LINK = st.column_config.LinkColumn
CODE_EXAMPLE = '''{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Website SEO audit",
  "offers": {"@type": "Offer", "price": "4999", "priceCurrency": "INR"}
}'''


def icons(df, col):
    return df.assign(**{col: df[col].map(lambda r: RESULT_ICON.get(r, r))})


def run_pages(urls: list, settings: dict, robots, info: dict):
    state = st.session_state
    results = {}
    session = ui.session(settings)
    ui.run_checks(urls, settings, results, robots or ui.robots(settings), content.schema_hook(), session)
    rows = [results[i] for i in sorted(results)]
    state["sc_tables"] = content.schema_tables(rows)
    state["sc_run_id"] = time.time()
    state["sc_info"] = {**info, **ui.run_info(settings)}


def page_results():
    state = st.session_state
    pages_df, items_df, type_df = state["sc_tables"]
    run_id = state.get("sc_run_id")
    ui.cards(content.schema_numbers(pages_df))
    tabs = st.tabs([f"Pages ({len(pages_df):,})", f"By type ({len(type_df):,})", f"Every schema item ({len(items_df):,})"])
    with tabs[0]:
        labels = {"all": "All pages", "problems": "Pages with problems", "none": "Pages without schema"}
        show = st.radio("Show", list(labels), format_func=labels.get, horizontal=True, key=f"sc_show_{run_id}")
        view = pages_df
        if show == "problems":
            view = pages_df[pages_df["Schema Result"].isin(["Missing required fields", "Invalid JSON"])
                            | (pages_df["Invalid JSON-LD"].fillna(0) > 0)]
        elif show == "none":
            view = pages_df[pages_df["Schema Result"] == "No schema"]
        st.dataframe(icons(view, "Schema Result"), width="stretch", hide_index=True, height=ui.table_height(len(view), 460),
                     column_config={"URL": LINK("URL", pinned=True, width="medium"),
                                    "Missing Required": st.column_config.TextColumn(width="large"),
                                    "Missing Recommended": st.column_config.TextColumn(width="large")})
    with tabs[1]:
        if type_df.empty:
            st.info("No schema markup was found on these pages.")
        else:
            st.dataframe(type_df, width="stretch", hide_index=True, height=ui.table_height(len(type_df), 460))
            st.caption("Not checked counts Microdata and types Google has no rich result rules for, and broken JSON-LD.")
    with tabs[2]:
        if items_df.empty:
            st.info("No schema markup was found on these pages.")
        else:
            types = sorted(items_df["Type"].unique())
            pick = st.multiselect("Types", types, default=[], placeholder="All types", key=f"sc_types_{run_id}")
            view = items_df[items_df["Type"].isin(pick)] if pick else items_df
            st.dataframe(icons(view, "Result"), width="stretch", hide_index=True, height=ui.table_height(len(view), 460),
                         column_config={"URL": LINK("URL", pinned=True, width="medium"),
                                        "Note": st.column_config.TextColumn(width="large")})
    st.caption("The rules follow Google's structured data documentation. Confirm a page with Google's own test:")
    with_schema = pages_df[~pages_df["Schema Result"].isin(["No schema", "Not read"])]["URL"].tolist() or pages_df["URL"].tolist()
    test_url = st.selectbox("Page to test", with_schema, key=f"sc_test_{run_id}")
    if test_url:
        ui.rich_results_buttons(test_url)

    info = state.get("sc_info", {})
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download CSV", lambda: core.to_csv_bytes(pages_df), "schema-check.csv", "text/csv", "sc_csv", run_id)
    ui.download(row, "⬇ Download Excel", lambda: content.schema_excel(pages_df, items_df, type_df, info),
                "schema-check.xlsx", core.XLSX_MIME, "sc_xlsx", run_id, heavy=True)


def code_results(result: dict):
    for err in result["errors"]:
        st.error(err)
    for note in result["notes"]:
        st.info(note)
    table = result["table"]
    if table.empty:
        if not result["errors"]:
            st.warning("No schema items with an @type were found in the pasted code.")
        return
    bad = int((table["Result"] == "Missing required fields").sum())
    if not result["errors"] and not bad:
        st.success("Every type has its required fields." if (table["Result"] != "Not checked").any()
                   else "The code parses. None of its types have Google rich result rules to check.")
    st.dataframe(icons(table, "Result"), width="stretch", hide_index=True, height=ui.table_height(len(table)),
                 column_config={"Missing Required": st.column_config.TextColumn(width="large"),
                                "Missing Recommended": st.column_config.TextColumn(width="large"),
                                "Note": st.column_config.TextColumn(width="large")})
    st.caption("Fields are checked on the top-level items (and the items inside @graph). Test the final page with "
               "Google's Rich Results Test after it is published.")


def main():
    settings = ui.crawl_settings(default_max=500, limit=20_000)
    ui.page_header("schema-check", "Schema check", DESCRIPTION)
    state = st.session_state

    with st.container(key="deck_schema"):
        mode = st.segmented_control("Check", MODES, default=MODES[0], key="sc_mode") or MODES[0]
        if mode == "Pages":
            c1, c2 = st.columns([3, 2])
            text = c1.text_area("URLs, one per line", height=170,
                                placeholder="https://example.com/product-1\nhttps://example.com/product-2")
            file = c2.file_uploader("Or upload a file", type=["csv", "txt", "xlsx", "xls"],
                                    help="CSV, TXT or XLSX with the URLs in the first column.")
            go = st.button("Check schema", type="primary")
        elif mode == "Sitemap":
            target = st.text_input("Sitemap URL or domain", placeholder="example.com   or   https://example.com/sitemap.xml")
            c1, c2 = st.columns(2)
            include = c1.text_input("Only URLs containing", placeholder="/product/, /blog/",
                                    help="Separate several with commas. Leave empty for every URL.")
            exclude = c2.text_input("Skip URLs containing", placeholder="/tag/, /author/")
            st.caption(f"Checks up to {settings['max_urls']:,} URLs (change the limit in the sidebar).")
            go = st.button("Check schema", type="primary")
        else:
            code = st.text_area("Paste JSON-LD, a <script> block or a page's HTML", height=260, placeholder=CODE_EXAMPLE)
            go = st.button("Check code", type="primary")

    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go and mode == "Pages":
            try:
                urls = core.collect_inputs(text, file)
            except Exception as e:
                st.error(f"The uploaded file could not be read: {e}")
                urls = []
            if not urls:
                st.warning("Paste or upload at least one URL.")
            else:
                if len(urls) > settings["max_urls"]:
                    st.info(f"The first {settings['max_urls']:,} of {len(urls):,} URLs are checked. Raise the limit in the sidebar to check more.")
                run_pages(urls[: settings["max_urls"]], settings, None, {"Source": "URL list"})
        elif go and mode == "Sitemap":
            urls, note, robots = ui.urls_from_sitemap(target, settings, include, exclude)
            if robots is None:
                st.error(note)
            elif not urls:
                st.warning(note + " No URLs to check.")
            else:
                if len(urls) > settings["max_urls"]:
                    note += f" The first {settings['max_urls']:,} are checked; raise the limit in the sidebar to check more."
                st.caption(note)
                run_pages(urls[: settings["max_urls"]], settings, robots, {"Source": target.strip()})
        elif go:
            if not (code or "").strip():
                st.warning("Paste some JSON-LD or HTML to check.")
            else:
                state["sc_code"] = content.check_code(code)

    if mode == "Paste code":
        if state.get("sc_code"):
            code_results(state["sc_code"])
        else:
            ui.covers("What the check covers", COVERS)
    elif state.get("sc_tables"):
        page_results()
    else:
        ui.covers("What the check covers", COVERS)


if __name__ == "__main__":
    main()
