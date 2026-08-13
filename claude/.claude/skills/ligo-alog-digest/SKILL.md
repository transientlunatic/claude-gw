---
name: ligo-alog-digest
description: Fetch recent LIGO Hanford (LHO) and Livingston (LLO) aLOG entries and write a short weekly news-style digest of what's been happening at the detector sites. Use when the user asks for a LIGO/aLOG status update, weekly digest, or "what's going on at the detectors".
---

# LIGO aLOG weekly digest

Produces a short, readable news report summarizing recent activity at the LIGO
Hanford (LHO) and Livingston (LLO) observatories, drawn from their public
aLOG (electronic logbook) entries.

## Step 1: Fetch the raw entries

Run the bundled script, which talks directly to the public aLOG search
interfaces at `alog.ligo-wa.caltech.edu` (LHO) and `alog.ligo-la.caltech.edu`
(LLO). No login is required. The script is stateless: it does not read or
write any local files, and does not need or use any credentials.

```
python3 scripts/fetch_alog.py --days 7
```

This prints a JSON array to stdout. Each entry has: `id`, `site` (`LHO` or
`LLO`), `date`, `time`, `type` (`report` for a top-level log entry or
`comment` for a threaded reply), `author`, `category` (e.g. `"LHO General"`),
`tags` (subsystem tags, mainly populated for LLO, e.g. `"General, VE"`),
`title`, `body` (plain text, HTML stripped), and `url` (a permalink into the
aLOG).

Pass `--days N` for a different window, or `--sites LHO` / `--sites LLO` to
fetch only one site.

## Step 2: Write the digest

Read through the JSON and write a concise digest in markdown, aimed at
someone who wants to know "what's been going on" without reading every log
entry. Guidelines:

- **Structure**: one section per site (LHO, then LLO). Within each, lead with
  a one- or two-sentence overall-status line (e.g. locked/observing time,
  whether the site was mostly in commissioning, maintenance, or an
  engineering run), then a short bulleted list of the notable items.
- **What counts as notable**: commissioning progress or milestones,
  maintenance/work permits with real impact, problems or glitches and their
  resolution status, equipment failures, and anything explicitly flagged as
  urgent or unusual. Routine/recurring entries (e.g. daily shift summaries
  with no news, routine calibration sweeps, FAMIS periodic checks that came
  back nominal) should be skipped or folded into the status line rather than
  each getting their own bullet.
- **Threading**: `comment` entries are replies to an earlier `report` (they
  don't carry their own title). Use them for extra context or resolution of
  an issue raised by a report, not as standalone bullets, unless a comment
  contains genuinely new information (e.g. "issue resolved by doing X").
- **Length**: aim for something that reads in under two minutes — a handful
  of bullets per site, not a summary of every entry. This is a news report,
  not a transcript.
- **Tone**: plain English, written for a gravitational-wave researcher who
  hasn't been following the logs closely, not necessarily a specialist in
  every subsystem (SEI, SUS, CDS, etc.) — briefly gloss jargon/acronyms where
  it aids understanding, but don't over-explain things that are clear from
  context.
- **Links**: include the `url` for a handful of the most significant entries
  so the reader can click through for detail, not for every bullet.
- **No fabrication**: only report what's in the fetched entries. If a week
  was quiet, say so briefly rather than padding it out.

## Notes

- aLOG content is intended for the LIGO/Virgo/KAGRA collaboration. Even
  though it's readable without logging in, don't publish digests built from
  it anywhere public (e.g. do not commit digest output to a public git repo
  or otherwise redistribute it outside a private context for the user).
- If a site's search returns nothing for the whole window, say so plainly
  ("no activity recorded" or similar) rather than treating it as an error.
