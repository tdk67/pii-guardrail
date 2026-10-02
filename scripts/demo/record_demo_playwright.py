"""Automated Playwright Video Recorder for Latch 3-Minute Demo.

Launches Playwright Chromium with high-definition 1080p video recording enabled,
opens the interactive Demo Player studio, steps through the planned 3-minute
demo scenarios with accurate pacing, and exports a production-ready WebM video.

Usage:
    # Full 3-minute broadcast recording:
    python scripts/demo/record_demo_playwright.py --full

    # Fast 30-second test run:
    python scripts/demo/record_demo_playwright.py --fast
"""

import argparse
from pathlib import Path
import sys
import time
from playwright.sync_api import sync_playwright


def record_demo(fast_mode: bool = False) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    html_player = repo_root / "scripts" / "demo" / "demo_player.html"
    video_out_dir = repo_root / "artifacts" / "demo_video"
    video_out_dir.mkdir(parents=True, exist_ok=True)

    if not html_player.exists():
        raise FileNotFoundError(f"Player HTML not found: {html_player}")

    player_url = html_player.as_uri()

    # Pacing timings in seconds:
    # Total: 180s (Full) or 30s (Fast)
    if fast_mode:
        slide_durations = [6, 8, 6, 6, 6]  # 32s test run
        print("[RECORDER] Running in FAST test mode (~32 seconds total)...")
    else:
        slide_durations = [30, 45, 30, 40, 35]  # 180s full demo
        print("[RECORDER] Running in FULL broadcast mode (3 minutes / 180s total)...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(video_out_dir),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        print(f"[RECORDER] Loading demo player: {player_url}")
        page.goto(player_url)
        page.wait_for_load_state("networkidle")

        slide_names = [
            "Architecture & Introduction (0:00 - 0:30)",
            "Git Commit PII Interception (0:30 - 1:15)",
            "Clean Commit Resolution (1:15 - 1:45)",
            "Repository Scanner & Markdown Report (1:45 - 2:25)",
            "Real-Time Observability & Grafana (2:25 - 3:00)",
        ]

        for idx, (name, duration) in enumerate(zip(slide_names, slide_durations), start=1):
            print(f"[RECORDER] Playing Slide {idx}: {name} (duration: {duration}s)...")
            page.evaluate(f"setSlide({idx})")
            time.sleep(duration)

        # Allow final frame to render cleanly
        time.sleep(2)

        # Closing context flushes and finalizes video file
        page.close()
        video_path = page.video.path()
        context.close()
        browser.close()

    print(f"\n[RECORDER SUCCESS] Video saved to: {video_path}")
    return Path(video_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record Latch demo video via Playwright")
    parser.add_argument("--fast", action="store_true", help="Record accelerated 30s version for testing")
    parser.add_argument("--full", action="store_true", help="Record full 3-minute broadcast version")
    args = parser.parse_args()

    fast = not args.full if args.fast else not args.full
    record_demo(fast_mode=fast)
