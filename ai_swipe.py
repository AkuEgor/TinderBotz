"""
AI auto-swiper: opens Tinder in a real Chrome window, reads each profile,
asks the AI judge (tinderbotz/judge.py) like/pass against preferences.md, swipes.

First run: log in yourself in the Chrome window that opens. The session is
saved in chrome_profile/, so later runs skip login.

  .venv/bin/python ai_swipe.py --dry-run      # judge only, YOU swipe, calibrate the prompt
  .venv/bin/python ai_swipe.py --max 80       # real run, 80 profiles

Every verdict is appended to data/decisions.jsonl.
"""
import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path

from tinderbotz.session import Session
from tinderbotz.helpers.geomatch_helper import GeomatchHelper
from tinderbotz.judge import Judge

LOG = Path("data/decisions.jsonl")


def wait_for_login(session, timeout_min=10):
    session.browser.get("https://tinder.com/?lang=en")
    deadline = time.time() + timeout_min * 60
    print(">> Log in to Tinder in the Chrome window. Waiting...")
    while time.time() < deadline:
        if "tinder.com/app/" in session.browser.current_url:
            print(">> Logged in.")
            return True
        time.sleep(3)
    return False


def human_pause(i, min_delay, max_delay):
    time.sleep(random.uniform(min_delay, max_delay))
    if i and i % random.randint(15, 25) == 0:
        rest = random.uniform(30, 90)
        print(f"   (break {rest:.0f}s)")
        time.sleep(rest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=100, help="profiles to process this run")
    ap.add_argument("--prefs", default="preferences.md")
    ap.add_argument("--dry-run", action="store_true", help="judge only; you swipe, press Enter for next")
    ap.add_argument("--min-delay", type=float, default=3.0)
    ap.add_argument("--max-delay", type=float, default=9.0)
    args = ap.parse_args()

    judge = Judge(Path(args.prefs).read_text())
    session = Session(store_session=True)
    if not wait_for_login(session):
        print("Not logged in after 10 min, stopping.")
        return

    LOG.parent.mkdir(exist_ok=True)
    failures = 0
    for i in range(args.max):
        geomatch = session.get_geomatch(quickload=True)
        if not geomatch or not geomatch.name:
            failures += 1
            print("   no profile loaded (out of profiles, likes, or a popup)")
            if failures >= 5:
                print("5 misses in a row, stopping.")
                break
            session._handle_potential_popups()
            time.sleep(5)
            continue
        failures = 0

        try:
            verdict = judge.judge(geomatch)
        except Exception as e:  # judge down -> pass, never like blind
            print(f"   judge error: {e}")
            verdict = None
        decision = verdict.decision if verdict else "pass"

        print(f"[{i + 1}/{args.max}] {geomatch.name}, {geomatch.age} -> {decision.upper()}"
              + (f" ({verdict.score}/10) {verdict.reason}" if verdict else ""))
        with LOG.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"), "dry_run": args.dry_run,
                "name": geomatch.name, "age": geomatch.age, "bio": geomatch.bio,
                "decision": decision, "score": verdict.score if verdict else None,
                "reason": verdict.reason if verdict else "judge error",
                "image_urls": geomatch.image_urls,
            }, ensure_ascii=False) + "\n")

        if args.dry_run:
            input("   swipe it yourself, then Enter for next... ")
            continue

        helper = GeomatchHelper(browser=session.browser)
        if decision == "like":
            helper.like()
            session.session_data["like"] += 1
        else:
            helper.dislike()
            session.session_data["dislike"] += 1
        human_pause(i, args.min_delay, args.max_delay)


if __name__ == "__main__":
    main()
