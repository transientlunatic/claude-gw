---
name: debug-pe-run
description: Debug a bilby PE run in the GWTC-4.0 threshold project. Use when asked to investigate, check, or diagnose a parameter estimation run for a specific event and analysis.
argument-hint: "[event e.g. GW230615_160825] [analysis e.g. bilby-IMRPhenomXPHM-SpinTaylor-3]"
allowed-tools: Read, Grep, Glob, Bash
---

Debug the PE run for $ARGUMENTS.

The working directory for runs is:
`project/working/<event>/<analysis>/`

Work through the following steps in order, reporting findings at each stage before moving to the next.

## Step 1 — Triage parallel runs

In `log_data_analysis/`, there will be one `.out` and one `.err` file per parallel job (par0, par1, par2, …).

- Check file sizes with `wc -l` on all `.out` and `.err` files. Very large `.err` files (>10k lines) are a red flag.
- For each par, grep the `.out` file for `"Run completed"` or `"Summary of results"` to determine if it finished.
- Count and classify errors in `.err` files: `grep -c "ERROR\|RuntimeError\|Traceback" <file>`.

## Step 2 — DAG health

Check `submit/dag_*.dagman.out` (tail last ~30 lines):
- How many rescue files exist? (`ls submit/*.rescue* | wc -l`). 100 = DAG has hit the maximum and aborted.
- Look for `STATUS_ERROR`, `Node return val: 1`, and `DAG status:` lines.
- Check `final_result/` — if empty, the merge step hasn't run.

## Step 3 — Diagnose failures

**Waveform errors** (`RuntimeError: Internal function call failed`):
- Find the failing parameter combination in the `.err` file (look for `Exception while calling loglikelihood function: params:`).
- The params order is: chirp_mass, mass_ratio, a_1, a_2, tilt_1, tilt_2, phi_12, phi_jl, dec, ra, theta_jn, psi, phase, geocent_time.
- Compute the implied total mass: `M_total = chirp_mass / (q/(1+q)^2)^(3/5)` where `q = mass_ratio`.
- If M_total >> 500 Msun (extreme chirp_mass + low mass_ratio combination), the waveform model is outside its calibration range. This is NOT a prior railing issue.
- Check whether the posterior in completed chains actually has support near that region (it likely doesn't — zero posterior probability).

**Prior railing**: Check the completed chain posteriors. Extract max/percentiles for chirp_mass and mass_ratio using:
```python
import h5py, numpy as np
fname = "project/working/<event>/<analysis>/result/<label>_par0_result.hdf5"
with h5py.File(fname, 'r') as f:
    mc = f['posterior']['chirp_mass'][:]
    q  = f['posterior']['mass_ratio'][:]
print(f"chirp_mass: max={mc.max():.1f}, 99th={np.percentile(mc,99):.1f}, median={np.median(mc):.1f}")
print(f"mass_ratio: min={q.min():.3f}, 1st={np.percentile(q,1):.3f}")
```
Use `/home/daniel/gwtc4/environment/bin/python` for this.
If the posterior max is within ~5 Msun of the prior boundary, the prior is genuinely railing and needs expanding.

**Corrupted resume file**: Appears as a WARNING at the start of the `.err` file. Dynesty restarts from scratch — not a failure, just slower.

## Step 4 — Check spectrograms for glitches

The spectrogram report is at:
`/data/www.astro/daniel/asimov/gwtc4-threshold/<event>/get-data/index.html`

Images are base64-embedded. Extract and view them:
```python
from bs4 import BeautifulSoup
import base64
with open('/data/www.astro/daniel/asimov/gwtc4-threshold/<event>/get-data/index.html') as f:
    soup = BeautifulSoup(f, 'html.parser')
for i, img in enumerate(soup.find_all('img')):
    data = img['src'].split(',', 1)[1]
    with open(f'/tmp/spectrogram_{i}.png', 'wb') as out:
        out.write(base64.b64decode(data))
# Image 0 = H1, Image 1 = L1
```
Then use the Read tool to view both images.

**Glitch indicators**:
- Bright, concentrated (in time and frequency) power in one detector with no corresponding feature in the other at the same time.
- A real signal produces correlated power in both detectors.
- For heavy BBH (high chirp mass), the signal is very short — any bright power >0.5 s after the trigger is likely a glitch, not signal.
- Common type: "blip" glitch — isolated, broadband, ~0.1 s duration.

## Step 5 — Determine the fix

| Problem | Fix |
|---------|-----|
| Waveform failure at extreme q+Mc (zero posterior support there) | Merge completed chains manually, or new run — the prior range is probably fine |
| Posterior railing at chirp_mass upper boundary | New blueprint with expanded `chirp_mass maximum` |
| Posterior railing at mass_ratio lower boundary | Consider whether a total mass constraint is needed |
| Glitch in post-merger window | Reduce `post trigger time` in event blueprint |
| Glitch before merger (pre-trigger) | Different segment or flag as contaminated |

## Step 6 — Implementing the fix

**Asimov commands** (always run from `project/` directory, using `/home/daniel/gwtc4/environment/bin/asimov`):

```bash
# Cancel an analysis
asimov production set <event> <analysis-name> -s cancelled

# Update event blueprint
asimov apply -f ../blueprints/events/<event>.yaml --update

# Add new analysis (auto-increments suffix)
asimov apply --iterate -f ../blueprints/bilby-IMRPhenomXPHM-SpinTaylor.yaml --event <event>
```

**Critical notes on the event blueprint** (`blueprints/events/<event>.yaml`):
- The key for post-trigger window is `post trigger time` (NOT `post trigger duration`) — the latter is silently ignored.
- The `segment start` stored in the ledger is cosmetic (hardcoded to `event_time - segment_length + 2`); it does NOT reflect `post trigger time`.
- The `post trigger time` value flows into the bilby.ini via the template at `asimov/configs/bilby.ini`.

**Never manually edit the ledger** (`project/.asimov/ledger.yml`).

**Standard prior ranges** for this project:
- `chirp_mass`: typically `[35, 180]`; expand upper bound if posterior rails
- `mass_ratio`: `[0.05, 1.0]` standard
- Numbered suffixes (`-2`, `-3`, …) on blueprint names = rerun attempts

## What to report

After completing the investigation, summarise:
1. Which parallel runs completed / failed and why
2. The key posterior statistics from completed chains (chirp_mass median, 95th pct, max; ln_BF)
3. Any data quality concerns (glitches, contamination)
4. Recommended action
