# Bundled fonts

The files live in `app/src/main/res/font/` — that directory accepts font
files only, which is why these notes sit here.

The redesign's three faces, all bundled rather than fetched, so the app renders
identically offline and no font request leaves the phone.

| Family | Files | Used for | Licence |
| --- | --- | --- | --- |
| Inter | `inter_regular`, `inter_medium`, `inter_semibold` | body copy | OFL 1.1 |
| Barlow Condensed | `barlow_condensed_semibold/bold/black` | `.font-display` — headings, scores, buttons | OFL 1.1 |
| JetBrains Mono | `jetbrains_mono_regular/medium/semibold` | `.font-mono-data` — eyebrows, counts, timestamps | OFL 1.1 |

The SIL Open Font License requires the licence to travel with the font, so the
full texts ship inside the APK at `assets/licenses/`. If a face is ever removed
from `Display`/`MonoData` in `ui/theme/Tracker.kt`, drop its file and its
licence together.
