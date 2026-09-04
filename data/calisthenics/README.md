# Calisthenics trick dataset

40 clips, 4 per trick: `muscle_up pull_up dip push_up squat handstand
front_lever planche back_lever human_flag` (see `metadata.csv`).

Regenerate / extend (no API keys needed):

```bash
python3 scripts/scrape_calisthenics.py --per-trick 4
python3 scripts/scrape_calisthenics.py --tricks planche --per-trick 6 --max-duration 600
```

## Provenance and license

Every clip is openly licensed; `metadata.csv` is the attribution ledger
(`source_url`, `license`, `author` columns — keep it with any redistribution).

- `wikimedia_commons`: Public Domain / CC (author in `author`, file page in `page_url`).
- `youtube_cc`: Creative Commons Attribution (reuse allowed) — credit the
  `author` and link `page_url` when reusing.

Footage under `videos/` is never committed to git (see `.gitignore`).
