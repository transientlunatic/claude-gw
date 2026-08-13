#!/usr/bin/env python3
"""Fetch LIGO Hanford (LHO) and Livingston (LLO) aLOG entries for the last N days.

Queries the public aLOG search interface directly (no login required) and
prints a JSON list of entries to stdout. Does not read or write any local
files -- every run is a fresh, stateless fetch from the source.
"""
import argparse
import datetime
import html
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SITES = {
    "LHO": "https://alog.ligo-wa.caltech.edu/aLOG",
    "LLO": "https://alog.ligo-la.caltech.edu/aLOG",
}

USER_AGENT = "Mozilla/5.0 (compatible; alog-digest-script/1.0)"

# A trailing "(tag1, tag2)" is present for some sites/categories but not
# others (e.g. LLO includes it, LHO often doesn't) -- captured as raw text
# and split apart in Python rather than in the regex itself.
REPORT_RE = re.compile(
    r'<div id="sectTask_(?P<id>\d+)" class="sectionTask">\s*'
    r'<a name="\d+" id="\d+"></a>\s*(?P<rawlabel>.*?)\s*'
    r'<!-- Output break div\. -->',
    re.S,
)
AUTH_RE = re.compile(
    r'<div id="authHdr_(?P<id>\d+)" class="authorDetails">\s*'
    r'(?P<author>[^\s<][^<]*?)\s*-\s*<span class="datePost">posted (?P<posted>[^<]+)</span>',
    re.S,
)
TITLE_RE = re.compile(
    r'<div id="titleHdr_(?P<id>\d+)" class="reportDetails">\s*<strong>(?P<title>.*?)</strong>',
    re.S,
)
# The "break div" marker is followed by an actual `<div class="break"></div>`
# element (which itself contains a `</div>`) before the real closing tag, so
# both stray `</div>`s have to be matched explicitly.
BODY_RE = re.compile(
    r'<div id="repHdr_(?P<id>\d+)" class="reportDetails">\s*(?P<body>.*?)\s*'
    r'<!-- Output break div\. -->\s*<div class="break"></div>\s*'
    r'<!--- Close reportHdr_\1 div -->\s*</div>',
    re.S,
)
COMMENT_AUTH_RE = re.compile(
    r'<div id="comment_author_(?P<id>\d+)" class="commentAuthor">\s*'
    r'<strong>(?P<author>[^<]+)</strong>\s*-\s*(?P<time>\d{1,2}:\d{2}),'
    r'\s*[A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\s*\(\d+\)(?P<tags>[^<]*)<div class="report_link">',
    re.S,
)
COMMENT_BODY_RE = re.compile(
    r'<div id="comment_(?P<id>\d+)" class="comment">\s*(?P<body>.*?)\s*'
    r'<!-- Output break div\. -->\s*<div class="break"></div>\s*'
    r'<!--- Close comment_\1 div -->\s*</div>',
    re.S,
)
TIME_PREFIX_RE = re.compile(r"(\d{1,2}:\d{2})")
LABEL_TAGS_RE = re.compile(r"^(?P<label>.*?)\s*\((?P<tags>[^)]*)\)\s*$", re.S)


def strip_html(fragment):
    text = fragment.replace("\r", "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_entries(doc, site_key, base_url, day_iso):
    reports = {}
    for m in REPORT_RE.finditer(doc):
        rawlabel = m.group("rawlabel").strip()
        tm = LABEL_TAGS_RE.match(rawlabel)
        if tm:
            label, tags = tm.group("label").strip(), tm.group("tags").strip()
        else:
            label, tags = rawlabel, ""
        reports[m.group("id")] = {"label": label, "tags": tags}
    for m in AUTH_RE.finditer(doc):
        rid = m.group("id")
        if rid in reports:
            reports[rid]["author"] = m.group("author").strip()
            tmatch = TIME_PREFIX_RE.match(m.group("posted").strip())
            reports[rid]["time"] = tmatch.group(1) if tmatch else ""
    for m in TITLE_RE.finditer(doc):
        rid = m.group("id")
        if rid in reports:
            reports[rid]["title"] = strip_html(m.group("title"))
    for m in BODY_RE.finditer(doc):
        rid = m.group("id")
        if rid in reports:
            reports[rid]["body"] = strip_html(m.group("body"))

    entries = {}
    for rid, r in reports.items():
        if "author" not in r:
            # Matched sectTask but not authHdr -- not a real top-level report
            # (defensive; shouldn't normally happen).
            continue
        entries[rid] = {
            "id": rid,
            "site": site_key,
            "date": day_iso,
            "time": r.get("time", ""),
            "type": "report",
            "author": r.get("author", ""),
            "category": r.get("label", ""),
            "tags": r.get("tags", ""),
            "title": r.get("title", ""),
            "body": r.get("body", ""),
            "url": f"{base_url}/index.php?callRep={rid}",
        }

    comment_meta = {}
    for m in COMMENT_AUTH_RE.finditer(doc):
        comment_meta[m.group("id")] = {
            "author": m.group("author").strip(),
            "time": m.group("time"),
            "tags": m.group("tags").strip(),
        }
    for m in COMMENT_BODY_RE.finditer(doc):
        rid = m.group("id")
        if rid in comment_meta and rid not in entries:
            c = comment_meta[rid]
            entries[rid] = {
                "id": rid,
                "site": site_key,
                "date": day_iso,
                "time": c["time"],
                "type": "comment",
                "author": c["author"],
                "category": "",
                "tags": c["tags"],
                "title": "",
                "body": strip_html(m.group("body")),
                "url": f"{base_url}/index.php?callRep={rid}",
            }

    return list(entries.values())


def fetch_day(site_key, base_url, day, opener, retries=2):
    date_str = day.strftime("%d-%m-%Y")
    data = urllib.parse.urlencode(
        {
            "srcDateFrom": date_str,
            "srcDateTo": date_str,
            "srcKeywordType": "1",
            "srcAuthorType": "2",
        }
    ).encode()

    last_err = None
    for attempt in range(retries + 1):
        try:
            opener.open(f"{base_url}/index.php", timeout=30).read()
            req = urllib.request.Request(
                f"{base_url}/includes/search.php?adminType=search", data=data
            )
            opener.open(req, timeout=30).read()
            doc = (
                opener.open(f"{base_url}/iframeSrc.php?content=1", timeout=30)
                .read()
                .decode("utf-8", "replace")
            )
            return parse_entries(doc, site_key, base_url, day.isoformat())
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
    print(
        f"warning: failed to fetch {site_key} {date_str}: {last_err}",
        file=sys.stderr,
    )
    return []


def make_opener():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=7, help="Number of trailing days to fetch (default: 7)"
    )
    parser.add_argument(
        "--sites",
        default="LHO,LLO",
        help="Comma-separated site keys to fetch (default: LHO,LLO)",
    )
    args = parser.parse_args()

    site_keys = [s.strip().upper() for s in args.sites.split(",") if s.strip()]
    for s in site_keys:
        if s not in SITES:
            print(f"error: unknown site {s!r}, choose from {list(SITES)}", file=sys.stderr)
            sys.exit(1)

    today = datetime.date.today()
    days = [today - datetime.timedelta(days=i) for i in range(args.days)]

    all_entries = []
    for site_key in site_keys:
        base_url = SITES[site_key]
        opener = make_opener()
        for day in days:
            all_entries.extend(fetch_day(site_key, base_url, day, opener))

    def sort_key(e):
        return (e["date"], e["time"], e["site"], e["id"])

    all_entries.sort(key=sort_key)
    json.dump(all_entries, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
