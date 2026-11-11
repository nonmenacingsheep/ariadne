"""shell: the escape hatch. Any command, vetted, timed out and captured.

Ported from 1.x run_command. The hard refusals are copied exactly: approval
means "I meant this", not "I thought through every consequence", and this
account can be root. Two 1.x fixes carry over:

* Output goes to files, not pipes. A daemon the command leaves behind inherits
  its output; with pipes that held the call open until the timeout and the
  daemon got blamed. With files the call ends when the command does.
* A build, install or download that takes minutes starts detached with its
  output in a log, instead of running until the timeout kills it and being
  retried. Commands that launch something (&, nohup, setsid) are checked two
  seconds later for what's still alive, so "it's up" is never assumed.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from ...adapters import consent, redact
from . import common
from .common import ToolError, audit, data_dir, is_sensitive, need_him, outside, resolve, short

DEFAULT_TIMEOUT = 20.0
SETTLE_S = 2.0           # how long after a launch to look at what survived

# Refused even when he says yes. Copied exactly from 1.x.
_BLOCKED: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|[\s;&|(])(sudo|pkexec|doas|su)(\s|$)"),
     "runs as another user"),
    (re.compile(r"\brm\b[^;|&]*\s-[a-zA-Z]*[rR][a-zA-Z]*[fF]|\brm\b[^;|&]*\s-[a-zA-Z]*[fF][a-zA-Z]*[rR]"),
     "is a recursive forced delete — move things to the trash instead"),
    (re.compile(r"\b(mkfs(\.\w+)?|fdisk|sfdisk|parted|wipefs|badblocks)\b"),
     "formats or repartitions a disk"),
    (re.compile(r"\bdd\b[^;|&]*\bof=\s*/dev/"), "writes directly to a device"),
    (re.compile(r">\s*/dev/(sd|nvme|vd|hd|mmcblk)"), "overwrites a raw device"),
    (re.compile(r":\s*\(\s*\)\s*\{.*\}\s*;?\s*:"), "is a fork bomb"),
    (re.compile(r"\b(shutdown|reboot|poweroff|halt|init\s+[06])\b"),
     "powers off or reboots the machine"),
    (re.compile(r"\bsystemctl\s+(poweroff|reboot|halt|isolate)\b"),
     "powers off or reboots the machine"),
    (re.compile(r"\b(curl|wget)\b[^;|&]*\|\s*\w*sh\b"),
     "pipes a download straight into a shell"),
    (re.compile(r"\bchmod\b[^;|&]*\s777\s+/(\s|$)"), "opens up the whole filesystem"),
    (re.compile(r"\b(rm|mv|chown|chmod|truncate)\b[^;|&]*\s/(etc|boot|bin|sbin|lib\d*|usr|var|dev|sys|proc)(/|\s|$)"),
     "modifies a system directory"),
    (re.compile(r"\b(useradd|userdel|usermod|passwd|visudo)\b"),
     "changes user accounts"),
    (re.compile(r"\b(iptables|nft|ufw|firewall-cmd)\b"), "changes the firewall"),
    (re.compile(r"\bcrontab\b|\bat\s+now\b"), "schedules background work"),
    (re.compile(r"/dev/tcp/|\bnc\b\s+-[a-z]*l|\bncat\b\s+-[a-z]*l"),
     "opens a network listener"),
]


def vet_command(command: str) -> str | None:
    """The reason a command is refused, or None."""
    text = " " + command.strip()
    for pattern, reason in _BLOCKED:
        if pattern.search(text):
            return reason
    return None


# Anything in a command line that looks like a path worth checking.
_PATHISH = re.compile(r"(?:[~$][\w/.${}]*|/)[\w./${}~-]*")


def sensitive_in(command: str) -> str | None:
    """The first credential-ish path named in a command, if any. read_file
    refuses credentials; a shell that can cat them makes that decorative."""
    for token in _PATHISH.findall(command or ""):
        text = token.strip("\"'`,;()")
        if len(text) < 3:
            continue
        try:
            expanded = Path(os.path.expandvars(os.path.expanduser(text)))
        except (OSError, ValueError):
            continue
        if is_sensitive(expanded):
            return short(expanded)
    return None


# Commands that send something to somebody as him: mail, chat webhooks, issues.
# They need his own words asking to send (consent.ASKS), like a message verb.
_SENDS = re.compile(
    r"\b(sendmail|mailx?|mutt|msmtp|swaks|xdg-email|signal-cli|telegram-send)\b"
    r"|\bgh\s+(?:issue|pr)\s+(?:create|comment)\b"
    r"|\b(?:curl|wget)\b[^;|&]*(?:discord(?:app)?\.com/api/webhooks|hooks\.slack\.com|api\.telegram\.org)",
    re.I)

# Builds, installs, downloads that take minutes.
LONG_JOB = re.compile(
    r"(?:^|[;&|(]\s*|\b(?:cd\s+\S+\s*&&\s*))"
    r"(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:build|install|ci|i)\b"
    r"|\b(?:cargo\s+(?:build|install)|make(?:\s|$)|cmake\s+--build|ninja\b"
    r"|pip3?\s+install|python3?\s+-m\s+pip\s+install|ui5\s+build|gradle\b|mvn\b"
    r"|docker\s+build|podman\s+build|flatpak\s+install|yt-dlp\b|git\s+clone"
    r"|wget\s|rsync\s|ffmpeg\s)", re.I)
_LAUNCH = re.compile(r"(?<![&|])&(?!&)|\bnohup\b|\bsetsid\b|\bdisown\b")

# What a shell command already has a tool for.
INSTEAD = (("find", "find_files"), ("grep", "search_text"), ("cat", "read_file"),
           ("sed", "edit_file"))


def jobs_dir() -> Path:
    return data_dir() / "jobs"


_jobs: dict[int, subprocess.Popen] = {}     # kept so poll() reaps them: no zombies, and we can tell if one died
# Every command she runs carries ARIADNE2_JOB=<token> in its environment,
# which everything it starts inherits (through nohup, setsid, a double fork),
# so core/downloads.py can find the downloads her commands start, however
# they're launched or wherever their output goes.
JOB_ENV = "ARIADNE2_JOB"
SESSIONS: dict[str, str] = {}
_tokens = __import__("itertools").count(1)


def _job_env(command: str) -> dict:
    token = f"{os.getpid()}-{next(_tokens)}"
    SESSIONS[token] = _label(command)
    while len(SESSIONS) > 200:
        del SESSIONS[next(iter(SESSIONS))]
    return dict(os.environ, **{JOB_ENV: token})


def start_background(command: str, workdir: Path) -> tuple[int, str, str]:
    """Detached in its own session, stdin closed, output in a log it ends with [exit N].
    Returns its pid, the log, and its job tag."""
    jobs_dir().mkdir(parents=True, exist_ok=True)
    log = jobs_dir() / (time.strftime("%m%d-%H%M%S") + f"-{os.getpid()}-{time.monotonic_ns() % 10**6}.log")
    env = _job_env(command)
    with open(log, "w") as fh:
        fh.write(f"$ {command}\n(in {workdir})\n\n")
        fh.flush()
        proc = subprocess.Popen(
            # The command runs in a child shell so its own `exit N` is caught and
            # $? is the command's, not the echo's (1.x always logged [exit 0]).
            ["bash", "-c", 'bash -o pipefail -c "$1"; rc=$?; echo; echo "[exit $rc]"', "_", command],
            cwd=str(workdir), stdout=fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, env=env)
    _jobs[proc.pid] = proc
    for pid in [p for p, j in _jobs.items() if j.poll() is not None and p != proc.pid]:
        del _jobs[pid]
    return proc.pid, str(log), env[JOB_ENV]


def _still_running(job: str) -> list[str]:
    """What the command started that is still alive a moment on: every process
    carrying its job tag, so one detached with setsid or nohup is found too."""
    from ..later import _procs
    time.sleep(SETTLE_S)
    return [f"{pid} {cmd[:100]}" for pid, cmd, tag in _procs() if tag == job]


# `cmd & sleep 8; check`: a guess at how long something takes, wrong both ways
# (too short: it isn't up yet; too long: he waits). A sleep inside a loop that
# tests something is a real wait and is left alone.
_GUESS_SLEEP = re.compile(r"(?:^|[;&(]|&&)\s*sleep\s+(\d+(?:\.\d+)?)\s*(?:s\b)?\s*(?:;|&&|$)")
_LOOP = re.compile(r"\b(?:while|until|for)\b")


def _guessed_wait(command: str) -> float | None:
    if _LOOP.search(command):
        return None
    secs = [float(m.group(1)) for m in _GUESS_SLEEP.finditer(command)]
    return max(secs) if secs and max(secs) >= 3 else None


def _label(command: str) -> str:
    return command[:60] + ("…" if len(command) > 60 else "")


def run(command: str, background: bool, cwd: str | None, his_words: str | None) -> str:
    command = str(command or "").strip()
    if not command:
        raise ToolError("no command was given")
    reason = vet_command(command)
    if reason:
        audit("shell", {"command": command}, "blocked", reason)
        raise ToolError(f"I won't run that — it {reason}. This one is refused no matter who "
                        f"asks. He can run it himself in a terminal if he really means it.")
    named = sensitive_in(command)
    if named:
        audit("shell", {"command": command}, "blocked", named)
        raise ToolError(f"that command names {named}, which is off limits — the same rule "
                        f"read_file follows. Going through a shell doesn't change it.")
    need_him(his_words, "running a command")
    if _SENDS.search(command) and not consent.ASKS.search(his_words or ""):
        raise ToolError("Not run: that sends something as him, and he didn't ask for anything "
                        "to be sent in his own words this turn. Tell him what you'd send and "
                        "let him say so.")

    guess = None if background else _guessed_wait(command)     # (in the background nothing waits on it)
    if guess:
        raise ToolError(
            f"Not run: `sleep {guess:g}` is a guess at how long something takes. Run the command without "
            f"the sleep (anything it leaves running gets a job tag), then wait for what you actually need: "
            f"later wait (this turn, up to 2 min) or later set (a check-in), with when=process_up, "
            f"port_open, log_says, file_ready or job_done.")
    workdir = resolve(cwd) if cwd else (common.current_project() or common.HOME)
    if not workdir.is_dir():
        workdir = common.HOME
    audit("shell", {"command": command, "cwd": str(workdir)}, "run")

    if background or (LONG_JOB.search(command) and not command.rstrip().endswith("&")):
        pid, log, job = start_background(command, workdir)
        time.sleep(min(1.0, SETTLE_S))
        alive = _jobs[pid].poll() is None
        tail = ""
        if not alive:
            try:
                tail = "\nIt has already finished; its log so far:\n" + outside(
                    Path(log).read_text("utf-8", "replace")[-1500:], "the command's output")
            except OSError:
                pass
        return (f"$ {redact.redact(command)}\nStarted in the background, detached (pid {pid}, job {job}); not "
                f"waited for. Its output goes to {log}, ending with '[exit N]' when it finishes. Tell him "
                f"it's running. Don't guess how long it takes: later set when=job_done job={job} wakes you "
                f"the moment it ends (log_says on that log, for a milestone before then). Do not start it "
                f"again.{tail}")

    limit = DEFAULT_TIMEOUT
    with tempfile.TemporaryFile("w+", errors="replace") as fout, \
            tempfile.TemporaryFile("w+", errors="replace") as ferr:
        env = _job_env(command)
        try:
            child = subprocess.Popen(["bash", "-o", "pipefail", "-c", command], stdout=fout,
                                     stderr=ferr, text=True, cwd=str(workdir),
                                     stdin=subprocess.DEVNULL, start_new_session=True,
                                     env=env)
            try:
                code = child.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                child.kill()
                raise ToolError(
                    f"the command was still running after {limit:.0f}s and was killed. Don't run "
                    f"it again the same way: a build, a scan or a download that takes minutes goes "
                    f"in the background (background=true) and gets checked on.")
        except OSError as exc:
            raise ToolError(f"couldn't run it: {exc.strerror}")
        fout.seek(0)
        ferr.seek(0)
        out_text, err_text = fout.read().strip(), ferr.read().strip()
    job = env[JOB_ENV]
    left = _still_running(job) if _LAUNCH.search(command) else None

    parts = [f"$ {redact.redact(command)}", f"(in {short(workdir)}, exit code {code})"]
    if left is not None:
        parts.append((f"Still running a moment later (job {job}): " + "; ".join(left[:6]) +
                      f". To hear the moment it ends: later set when=job_done job={job}.") if left else
                     "Nothing it started is still running: whatever was launched has exited, or was "
                     "handed to his desktop (host-spawn, flatpak), where process_up can watch for it. "
                     "Read its log before saying it's up.")
    body = []
    if out_text:
        body.append("stdout:\n" + common.clip(out_text))
    if err_text:
        body.append("stderr:\n" + common.clip(err_text))
    if body:
        parts.append(outside("\n".join(body), "the command's output"))
    else:
        parts.append("(no output)")
    head = (os.path.basename(command.split()[0].strip("()`$")) if command.split() else "")
    better = next((t for h, t in INSTEAD if h == head), None)
    if better:
        parts.append(f"[There is a tool for this: {better}.]")
    return "\n".join(parts)
