"""Build a frame-by-frame terminal transcript (ANSI text + duration) for the README terminal GIF.

The findings are produced by the real CLI (`compare`) from the fictional demo data.
    python3 docs/tools/terminal_transcript.py <demo_dir> <out.json>
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
demo, out = Path(sys.argv[1]), Path(sys.argv[2])

DIM, BOLD, RESET, GREEN = "\033[2m", "\033[1m", "\033[0m", "\033[32m"
PROMPT = f"{GREEN}➜{RESET} {BOLD}~{RESET} "
COMMAND = "ps-remote-check remote --pair ABCD-EFGH-JKMN"
STEPS = [
    "checking internet / captive portal",
    "checking PlayStation Network reachability",
    "detecting NAT type with STUN",
    "measuring UDP latency / jitter",
    "measuring speed (download + upload, ~15 s)",
    "live test: looking for the home helper",
    "contacting the home helper via the relay",
    "opening a direct connection to home (UDP hole punching)",
    "measuring round-trip time to home",
    "streaming test video traffic from home (15 Mbps for 6 s)",
]

env = {**os.environ, "FORCE_COLOR": "1", "PYTHONPATH": str(ROOT)}
result = subprocess.run([sys.executable, "-m", "ps_remote_checker", "compare",
                         str(demo / "cli" / "home.json"), str(demo / "cli" / "remote-live.json")],
                        capture_output=True, text=True, env=env, cwd=ROOT)
verdict_lines = result.stdout.rstrip("\n").split("\n")

frames, text = [], PROMPT
frames.append((text + "█", 0.8))
for i in range(0, len(COMMAND), 3):
    frames.append((text + COMMAND[:i + 3] + "█", 0.06))
text += COMMAND + "\n"
frames.append((text, 0.35))
text += f"{BOLD}PS Remote Play checker: REMOTE network (PS Portal side){RESET}\n"
frames.append((text, 0.3))
for step in STEPS:
    text += f"{DIM}  … {step}{RESET}\n"
    frames.append((text, 0.9 if "streaming" in step or "speed" in step else 0.45))

# reveal the verdict section by section (blank lines separate sections)
chunk = []
for line in verdict_lines + [""]:
    chunk.append(line)
    if line.strip() == "" and any(c.strip() for c in chunk):
        text += "\n".join(chunk) + "\n"
        frames.append((text, 0.6))
        chunk = []
frames[-1] = (frames[-1][0], 5.0)
out.write_text(json.dumps([{"text": t, "duration": d} for t, d in frames]))
print(f"{len(frames)} frames -> {out}")
