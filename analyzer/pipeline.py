"""Rebuild everything from the newest DATA/sms-export*.csv: ledger -> flows -> categories -> dashboard.

Run: python3 pipeline.py   (reconcile.py only runs when DATA/statements/ has the bank CSVs)
"""
import subprocess
import sys

from config import CODE, DATA
from reconcile import BANKS


def run():
    steps = ["parse.py"]
    if all((DATA / "statements" / f"{b}.csv").exists() for b in BANKS):
        steps.append("reconcile.py")
    steps += ["categorize.py", "build_dashboard.py"]
    for s in steps:
        subprocess.run([sys.executable, str(CODE / s)], cwd=CODE, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True)  # stderr: the error the dashboard shows
    return steps


if __name__ == "__main__":
    print("ran", " -> ".join(run()))
