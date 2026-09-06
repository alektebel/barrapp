#!/usr/bin/env python3
"""Label every tappable element on the current phone screen with a number,
so an agent (or a human) can act by label instead of guessing pixel
coordinates. Inspired by AppAgent's exploration phase, reimplemented here
directly against adb/uiautomator with no external LLM wiring needed.

    python3 scripts/ui_probe.py snap        # screenshot + numbered boxes + legend
    python3 scripts/ui_probe.py tap 4        # tap the center of box 4 from the last snap
    python3 scripts/ui_probe.py back         # adb back button
    python3 scripts/ui_probe.py text "hello" # type text into the focused field

State (last snapshot's boxes) is kept in .ui_probe_state.json next to the
screenshots, both under out/ui_probe/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "out" / "ui_probe"
OUT.mkdir(parents=True, exist_ok=True)
STATE = OUT / "state.json"
DEVICE_DUMP = "/sdcard/ui_probe_dump.xml"


import os

SERIAL = os.environ.get("UI_PROBE_SERIAL", "eida4h4xamzhroeq")


def adb(*args: str) -> str:
    return subprocess.run(["adb", "-s", SERIAL, *args], capture_output=True, text=True, check=True).stdout


def screenshot(path: Path) -> None:
    raw = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, check=True).stdout
    path.write_bytes(raw)


def dump_hierarchy() -> ET.Element:
    adb("shell", "uiautomator", "dump", DEVICE_DUMP)
    local = OUT / "dump.xml"
    subprocess.run(["adb", "pull", DEVICE_DUMP, str(local)], capture_output=True, check=True)
    return ET.parse(local).getroot()


def parse_bounds(s: str) -> tuple[int, int, int, int]:
    # "[x1,y1][x2,y2]"
    a, b = s.split("][")
    x1, y1 = a[1:].split(",")
    x2, y2 = b[:-1].split(",")
    return int(x1), int(y1), int(x2), int(y2)


def best_label(node: ET.Element) -> str:
    desc = node.get("content-desc") or ""
    if desc:
        return desc[:40]
    text = node.get("text") or ""
    if text:
        return text[:40]
    # look at descendants for something readable
    for child in node.iter():
        t = child.get("text") or child.get("content-desc") or ""
        if t.strip():
            return t.strip()[:40]
    return f"<{node.get('class', 'view').rsplit('.', 1)[-1]}>"


def collect_clickable(root: ET.Element) -> list[dict]:
    boxes = []
    for node in root.iter("node"):
        if node.get("clickable") == "true" and node.get("enabled") == "true":
            bounds = parse_bounds(node.get("bounds"))
            x1, y1, x2, y2 = bounds
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append({
                "bounds": bounds,
                "center": [(x1 + x2) // 2, (y1 + y2) // 2],
                "label": best_label(node),
            })
    return boxes


def annotate(img_path: Path, boxes: list[dict], out_path: Path) -> None:
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = box["bounds"]
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 60), width=4)
        tag = str(i)
        tw = draw.textlength(tag, font=font)
        draw.rectangle([x1, y1, x1 + tw + 10, y1 + 34], fill=(255, 0, 60))
        draw.text((x1 + 5, y1 + 2), tag, fill=(255, 255, 255), font=font)
    img.save(out_path)


def cmd_snap() -> None:
    shot = OUT / "screen.png"
    screenshot(shot)
    root = dump_hierarchy()
    boxes = collect_clickable(root)
    annotated = OUT / "screen_labeled.png"
    annotate(shot, boxes, annotated)
    STATE.write_text(json.dumps(boxes, indent=2))
    print(f"labeled screenshot: {annotated}")
    print(f"{len(boxes)} tappable elements:")
    for i, box in enumerate(boxes):
        print(f"  [{i}] {box['label']!r} @ {box['center']}")


def cmd_tap(index: int) -> None:
    boxes = json.loads(STATE.read_text())
    x, y = boxes[index]["center"]
    print(f"tapping [{index}] {boxes[index]['label']!r} @ ({x},{y})")
    adb("shell", "input", "tap", str(x), str(y))


def cmd_back() -> None:
    adb("shell", "input", "keyevent", "4")


def cmd_text(value: str) -> None:
    adb("shell", "input", "text", value.replace(" ", "%s"))


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, *rest = sys.argv[1:]
    if cmd == "snap":
        cmd_snap()
    elif cmd == "tap":
        cmd_tap(int(rest[0]))
    elif cmd == "back":
        cmd_back()
    elif cmd == "text":
        cmd_text(rest[0])
    else:
        sys.exit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
