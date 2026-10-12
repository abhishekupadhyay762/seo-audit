# SEO Audit Toolkit (Streamlit)

One app, six tools (switch in the left sidebar).

**Audit**
1. **Sitemap audit** - enter a sitemap URL or a domain. Lists every URL in the sitemap, finds problems in
   the sitemap itself, then checks the pages you choose.
2. **Site crawl** - starts at the homepage and follows internal links. Checks every page found, compares
   the crawl with the sitemap (orphan pages, pages missing from the sitemap) and checks every link.
3. **Bulk URL check** - paste or upload URLs. Status, redirects, indexability, title, meta, headings,
   content, images, schema, hreflang, links and issues for each URL. Can also check every link on the pages.
4. **Keyword check** - URL plus target keyword. Shows whether the keyword is in the title, H1, meta
   description, URL, first 100 words and H2s, and flags URLs that compete for the same keyword.

**Check and compare**
5. **Redirect check** - old URL plus expected new URL (a migration redirect map). Confirms each old URL
   lands on the right page in one permanent redirect.
6. **Compare runs** - upload two downloads from this tool (before and after) to see fixed and new issues.

Every audit tool can download CSV, Excel, a client report (Word, opens in Google Docs) and an XML
sitemap of the indexable URLs it found.

## Folder structure (keep it exactly like this)

    sitemap-audit/
      Sitemap_to_URL_and_Title_Generator.py   main file (the one Streamlit runs)
      page_sitemap.py                         Sitemap audit screen
      page_crawl.py                           Site crawl screen
      page_bulk.py                            Bulk URL check screen
      page_keywords.py                        Keyword check screen
      page_redirects.py                       Redirect check screen
      page_compare.py                         Compare runs screen
      seo_core.py                             fetching, page checks, issue rules, sitemap reading, exports
      seo_crawl.py                            site crawl and link checks
      seo_checks.py                           canonical / hreflang targets, keywords, redirects, compare, XML sitemap
      seo_report.py                           Word client report and the advice text for every issue
      seo_ui.py                               look, sidebar and the results view
      requirements.txt
      .streamlit/
        config.toml                           colours and fonts

## Run on your computer

    pip install -r requirements.txt
    python -m streamlit run Sitemap_to_URL_and_Title_Generator.py

The browser opens http://localhost:8501. After replacing files, stop the tool (Ctrl+C) and start it again.

## Put it live (Streamlit Community Cloud)

Upload the same files and the `.streamlit` folder to the GitHub repo. The main file name is unchanged, so
the app redeploys by itself. If it shows an error after an update, open Manage app and choose Reboot app.

## Change the look, the wording or the limits

- Colours and fonts: `.streamlit/config.toml`
- Tool name: `APP_NAME` at the top of `seo_ui.py`
- Advice text in the client report: `ADVICE` in `seo_report.py`
- Limits and thresholds: the settings block at the top of `seo_core.py`, `seo_crawl.py` and `seo_checks.py`
