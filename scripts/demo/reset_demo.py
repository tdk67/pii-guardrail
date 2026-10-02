"""Demo Scenario: Reset environment and clean up temporary demo files.

Unstages and removes files created under demo/ to restore git status to clean.
"""

from pathlib import Path
import shutil
import subprocess


def reset_demo() -> None:
    demo_dir = Path("demo")
    if demo_dir.exists():
        # Unstage in git
        subprocess.run(["git", "reset", "HEAD", "demo"], capture_output=True)
        # Delete directory
        shutil.rmtree(demo_dir, ignore_errors=True)
        print("[DEMO] Removed temporary demo/ directory and unstaged changes.")

    # Unstage any accidental staged files under demo
    subprocess.run(["git", "checkout", "--", "demo"], capture_output=True)
    print("[DEMO] Git working tree reset successfully.")


if __name__ == "__main__":
    reset_demo()
