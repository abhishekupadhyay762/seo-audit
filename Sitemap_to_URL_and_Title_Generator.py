"""
SEO Audit Toolkit - main file (this is the file Streamlit runs)

It only sets up the page, the sidebar and the list of tools. The tools themselves are in:
  page_sitemap.py     Sitemap audit
  page_crawl.py       Site crawl
  page_bulk.py        Bulk URL check
  page_keywords.py    Keyword check
  page_redirects.py   Redirect check (site migrations)
  page_compare.py     Compare runs
Shared code:
  seo_core.py         fetching, reading pages, issue rules, sitemap reading, exports
  seo_crawl.py        site crawl and link checks
  seo_checks.py       canonical / hreflang targets, keywords, redirects, comparisons, XML sitemap
  seo_report.py       the Word client report and the advice for every issue
  seo_ui.py           look, sidebar and the results view

Run locally:  python -m streamlit run Sitemap_to_URL_and_Title_Generator.py
"""

import streamlit as st

import seo_ui as ui

st.set_page_config(page_title=ui.APP_NAME, page_icon="🔎", layout="wide")

TOOLS = {
    "Audit": [
        st.Page("page_sitemap.py", title="Sitemap audit", icon=":material/account_tree:", url_path="sitemap-audit", default=True),
        st.Page("page_crawl.py", title="Site crawl", icon=":material/travel_explore:", url_path="site-crawl"),
        st.Page("page_bulk.py", title="Bulk URL check", icon=":material/checklist:", url_path="bulk-url-check"),
        st.Page("page_keywords.py", title="Keyword check", icon=":material/key:", url_path="keyword-check"),
    ],
    "Check and compare": [
        st.Page("page_redirects.py", title="Redirect check", icon=":material/alt_route:", url_path="redirect-check"),
        st.Page("page_compare.py", title="Compare runs", icon=":material/compare_arrows:", url_path="compare-runs"),
    ],
}

current = st.navigation([page for pages in TOOLS.values() for page in pages], position="hidden")
ui.frame(TOOLS)
current.run()
