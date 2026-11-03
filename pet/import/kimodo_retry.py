"""Re-generate stance clips until kimodo_check passes (tries a few seeds).

Run with Kimodo's Python, its text encoder server already up (kimodo_batch.sh
starts one; or: GRADIO_SERVER_NAME=127.0.0.1 kimodo_textencoder &):
    kimodo_retry.py retry.txt   ("name|seconds|prompt" lines)
Each try is written as <name>_try<seed>; the first that starts and ends in
the stances its name says replaces <name>.
"""
import os
import subprocess
import sys

K = "/var/mnt/games/AI/Kimodo"
OUT = f"{K}/clips/aries"
CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kimodo_check.py")
for line in open(sys.argv[1]):
    if line.strip().startswith("#") or "|" not in line:
        continue
    name, secs, prompt = line.strip().split("|", 2)
    for seed in range(2, 7):
        stem = f"{OUT}/{name}_try{seed}"
        subprocess.run([f"{K}/.venv/bin/kimodo_gen", prompt, "--duration", secs, "--seed", str(seed),
                        "--output", stem, "--bvh", "--bvh_standard_tpose"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # the checker reads the stance from the clip's name
        probe = f"{OUT}/{name}.npz"
        os.replace(stem + ".npz", probe)
        os.replace(stem + ".bvh", f"{OUT}/{name}.bvh")
        r = subprocess.run([sys.executable, CHECK, probe], capture_output=True, text=True)
        print(f"{name} seed {seed}: {r.stdout.strip()}", flush=True)
        if r.returncode == 0:
            break
