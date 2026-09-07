# barrapp — UX Navigation Tree (verified via ADB uiautomator)

Device 1080×2400. Coordinates are tap centers (px). Legend:
✅ works · ⚠️ works with bug · 💀 dead control · ❓ untested

## Root: Bottom Navigation (always visible, y≈2140)
| Tab | Bounds | Center |
|---|---|---|
| Week | 48,2070–258,2211 | (153, 2140) ✅ |
| Calendar | 258,2070–469,2211 | (363, 2140) ✅ |
| **+ FAB** | 472,2074–607,2209 | (540, 2141) ✅ → system photo picker |
| Ladder | 610,2070–821,2211 | (715, 2140) ✅ |
| Coach | 821,2070–1032,2211 | (926, 2140) ✅ |

Header (every tab): app logo + "barrapp / Week 36 · Diego"; **"?"** 923,121–1058,250
→ center (990,185) — NOT help: navigates to **Coach** ⚠️ (misleading icon; no-op on Coach)

## Screens & edges

WEEK (root tab)
├─ stat block "703→744 reps / +703 vs last" (no controls)
├─ day bar chart M–S — bars not tappable 💀; "F" label drawn under Friday bar (B5)
├─ NEXT UNLOCK card (540,1121) → LADDER ✅ (tab shortcut)
├─ LAST SESSION card (540,1507) → SESSION DETAIL ⚠️ B1 (opens wrong/stale record)
└─ "Ask what the week actually shows →" (540,1713) → COACH ✅

CALENDAR (root tab)
├─  prev month (906,306) 💀 DEAD — no month change, clickable=false
├─ › next month (996,306) 💀 DEAD — same
├─ day cell "4 Sept" (681,659) → SESSION DETAIL ⚠️ B1 (opens Aug-14 record)
├─ day cell "5 Sept" (824,659) → SESSION DETAIL ⚠️ B1 (same Aug-14 record)
├─ empty day cells — not clickable (by design? unfillable gap vs legend)
├─ session row "Push-up 189·5 Sept" (540,1740) → SESSION DETAIL ⚠️ B1 (same stale record)
├─ session row "Push-up 514·4 Sept" (540,1905) ❓ (assumed same bug)
└─ row 28/29/30 misaligned (B6)

+ FAB → SYSTEM PHOTO PICKER (com.google.android.photopicker)
├─ grid of videos; single-select → "Hecho/Done" (882,2187) ✅
└─ → MEASURING (app)

MEASURING / QUEUE (sub-screen, "← Week" back 112,287)
├─ 4-stage pipeline: Sent → Movement recognised → Trimming → Counting
├─ "Skip ahead to the result" (540,1250) ❓
├─ IN THE WORKS list (scrolls; 3rd row starts hidden under nav)
│  ├─ per clip: Retry (236,·) ❓ · Log (410,·) → WORK LOG ✅ · Dismiss (603,·) ❓
│  └─ labels "Clip · HH:MM" ambiguous; raw errors (M3)
├─ ⚠️ one-off: job completion auto-navigated Calendar→Week mid-session (needs repro)
└─ "← Week" → WEEK ✅ (label hard-coded; context-losing, M1)

WORK LOG (sub-screen; no bottom nav)
├─ Back (126,216) → MEASURING ✅
├─ Retry / Dismiss / Copy log ❓
└─ ordered event timeline (info/warn) ✅

SESSION DETAIL (sub-screen, "← Week" 112,287)
├─ header: "THU 14 AUG · MUSCLE-UP" or "2026-09-05 · PUSH_UP" ⚠️ raw enum/ISO leak
├─ score ring (78 SOLID / — UNMEASURED) ⚠️ "Solid set" copy on UNMEASURED set
├─ "TWO THINGS TO CARRY…" ⚠️ header says TWO, list can have one
├─ "Watch the replay" (246,1310) 💀 DEAD (no clickable node)
└─ "Each rep" (791,1310) → inline rep cards ✅ (trajectory + weighted Range/Control/Smoothness)

LADDER (root tab)
├─ Pull up / Muscle up / Weighted pull-up cards — 💀 none clickable (M2)
├─ ⚠️ "Still needed: Still needed:" duplicated (B7)
└─ (arrives from NEXT UNLOCK card too)

COACH (root tab)
├─ "← Week" breadcrumb ⚠️ stale on root tab (M1)
├─ chips: "What did my last session…" (205,723) ✅ answered earlier
│         "Am I getting better…" (540,723) ⚠️ B2 no reply, no spinner, no error
│         "Why do some reps not get a score" (875,723) ❓
├─ input "Ask about your training" (277,1988) ❓ keyboard
└─ send ↑ (981,1987) — empty send correctly ignored ✅

## Untested leaves (next pass)
Success "result" screen after full measurement · Skip-ahead · Retry/Dismiss · month view
of Aug/Oct (blocked by dead arrows) · TalkBack pass · landscape · multi-select picker.
