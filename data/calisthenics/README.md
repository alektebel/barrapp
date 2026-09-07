# Calisthenics trick dataset

Open-licensed clips across the movements barra can verify plus the barbell
"big three". Every clip is in `metadata.csv` (the attribution ledger).

## Current inventory (scraped 2026-09-07)

| trick | clips | trick | clips |
|---|---|---|---|
| muscle_up | 6 | pistol_squat | 8 |
| pull_up | 10 | knee_raise | 12 |
| dip | 7 | handstand | 6 |
| push_up | 8 | front_lever | 8 |
| squat | 6 | planche | 10 |
| back_lever | 6 | human_flag | 6 |
| bench_press | 4 | deadlift | 10 |
| barbell_squat | 8 | | |

115 clips total (only short, ≤180s clips are kept; each is normalised to 720p).

## How much is available (measurement, 2026-09-07)

Pools measured live. YouTube **Creative Commons** is the dominant source
(`sp=EgIwAQ%3D%3D`); Wikimedia Commons is a small fully-Clean topping.

| movement | CC pool (one query) | Commons video files |
|---|---|---|
| push_up | 27–306 | ~3–5 |
| pull_up | 42–209 | ~2–4 |
| dip | 354 | ~1–3 |
| muscle_up | 7–233 | ~2–8 |
| knee_raise | 277 | ~0–2 |
| squat (bodyweight) | 273 | ~0–5 |
| pistol_squat | 343 | ~1 |
| handstand | 91–351 | ~0–2 |
| front_lever | 299 | ~0–1 |
| planche | 68–99 | ~0–1 |
| back_lever | 337 | ~0–1 |
| human_flag | 35–219 | ~0–7 |
| bench_press | 384 | ~15–23 |
| deadlift | 167 | ~15 |
| barbell_squat | 196 | ~1 |

Notes:
- The CC number is **query-sensitive** (muscle_up 7→233, handstand 91→351) and
  several queries hit the ~400 search cap, so each movement's true pool is a
  **multi-query aggregate** and these are lower bounds.
- Raw pool across all 15 movements ≈ **3,900+ unique candidates**. After the
  pipeline gates (≤180s, movement present, ≥6 reps in one viewpoint bin,
  ≥8 clean reference reps, dedup) usable yield is ~35–50%:
  **~700–1,200 usable clips**, ~45–90 per measurable movement.

## Regenerate / extend (no API keys needed)

```bash
python3 scripts/scrape_calisthenics.py --per-trick 12 --max-duration 180
# add/refresh the barbell big three
python3 scripts/scrape_calisthenics.py --tricks bench_press,deadlift,barbell_squat --per-trick 30
# bulk route one CC-heavy channel by title keywords (THENX, Chris Heria, ...)
python3 scripts/scrape_calisthenics.py --channel https://www.youtube.com/@ChrisHeria
```

Two guards keep the set clean:
- **Explicit-content blocklist** (`is_clean`): Wikimedia's full-text search can
  surface clearly non-training footage; any candidate whose title names such
  content is dropped before download.
- **Movement relevance filter** (`relevant_title`): Commons search is loose
  ("press", "up", "pull" match lots of clips), so a Commons candidate is only
  kept when its title actually names the movement.

## Provenance and license

Every clip is openly licensed; `metadata.csv` is the attribution ledger
(`source_url`, `license`, `author` columns — keep it with any redistribution).

- `wikimedia_commons`: Public Domain / CC (author in `author`, file page in `page_url`).
- `youtube_cc`: Creative Commons Attribution (reuse allowed) — credit the
  `author` and link `page_url` when reusing.

Footage under `videos/` is never committed to git (see `.gitignore`).
