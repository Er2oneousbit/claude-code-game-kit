#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# tripo.py
# Purpose : Everything Bozzetto says to the Tripo3D API, in one place, for both of its paid routes: `make --with tripo`
#           (a model from a picture, several views or a sentence) and `rig make --with tripo` (rig.py). The client,
#           the price quote, the --max-credits cap with the balance check, and the tasks.json journal that lets a
#           re-run reuse paid work live here; rig.py keeps only its own steps.
# Usage   : A module, not a command. bozzetto.py binds itself (bind) and calls run_make(); rig.py uses Client, Journal
#           and Budget. The commands:
#             python tools/bozzetto/bozzetto.py make prop_crate --with tripo --image art_src/crate.png
#             python tools/bozzetto/bozzetto.py make npc_guard --with tripo --class npc --front f.png --back b.png
#             python tools/bozzetto/bozzetto.py make prop_lamp --with tripo --prompt "a brass ship's lantern"
# Needs   : Python 3.8+ (standard library), TRIPO_API_KEY with paid API credits (a Tripo Studio plan adds none).
# Notes   : API facts, read from https://developers.tripo3d.ai/en/docs on 2026-11-11 (the API itself not called since
#           the 2026-11-05 test, E153): base https://openapi.tripo3d.ai/v3, Bearer key; POST /files (multipart "file",
#           PNG or JPEG up to 20 MB) -> file_token; POST /generation/image-to-model {input, model}, /multiview-to-model
#           {inputs: [{"front": tok}, ...], front required, 2 views at least}, /text-to-model {prompt <= 1024 chars};
#           models P1-20260311 and P2-20260801; GET /tasks/{id} (poll every 1-2 s; credits_consumed, error_code,
#           error_message; banned and expired come back as failed); GET /account/balance {balance, frozen}. Credits are
#           frozen when a task is created and charged only when it succeeds (failed and cancelled tasks cost nothing).
#           There is no price or estimate endpoint, so the quote is MAKE_QUOTE below: conservative, and only the P2
#           image-to-model figure is measured (110 credits, E153; the public table says 30). Each task's actual
#           cost is read back from credits_consumed and checked against --max-credits before the next paid call.
#           Result links expire after about 5 minutes (E153, verify): the finished task is asked again for a fresh
#           link each run. The key is sent only to the API, never to the download host, and never written down.
#           Outputs bought with paid credits are the user's and not used for training (Tripo terms 5.2.2); outputs
#           from free credits stay Tripo's (5.2.1).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   Client:  call (JSON in, {code, data} out; 401/403 -> ToolError) | upload | create task -> journal it running ->
#            wait (poll; failed/cancelled -> JobError with Tripo's reason) | download (no key sent)
#   Journal: tasks.json in the work folder; reused only when every input fact matches (and not --no-reuse); a task
#            left running is asked how it ended before anything new is paid for
#   Budget:  actual spend so far + the next step <= --max-credits, and <= the balance; else stop before paying
#   run_make: pictures stripped of metadata and kept -> journal -> quote, balance, cap -> upload -> one task ->
#            actual cost -> the finished task asked again for a fresh link -> download -> raw.glb (extras stripped)
import json
import os
import time
import urllib.error
import urllib.request
import uuid

bz = None   # bozzetto.py binds itself here (bind): its errors, DEBUG flag, SLEEP and helpers

TRIPO_ENV = "TRIPO_API_KEY"
BASE = "https://openapi.tripo3d.ai/v3"       # the exam points this at its stand-in server
OPENER = urllib.request.urlopen              # the exam may replace it too
POLL_S = 2                                   # the docs ask for one query every 1 to 2 seconds
FAILED = ("failed", "cancelled", "banned", "expired")   # banned/expired: legacy names Tripo now reports as failed
JOURNAL = "tasks.json"
NO_STUDIO = "API credits are bought separately: a Tripo Studio plan adds none"
TERMS = ("outputs made with paid API credits are the user's and are not used for training (Tripo terms 5.2.2); "
         "outputs from free credits stay Tripo's (5.2.1); a Tripo Studio plan adds no API credits")
LICENSE = "Tripo3D terms (paid output, 5.2.2)"
CREDIT_MAKE = "3D model generated with the Tripo3D API (paid credits; outputs owned by the paying user, Tripo terms 5.2.2)."

def bind(module):
    global bz
    bz = module


def key():
    return os.environ.get(TRIPO_ENV, "")


# ---- the client --------------------------------------------------------------------------------------------------
class Client:
    def __init__(self, api_key=None, base=None):
        self.key, self.base = api_key or key(), (base or BASE).rstrip("/")

    def call(self, method, path, body=None, raw=None, ctype=None):
        h = {"Authorization": f"Bearer {self.key}"}
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        if raw is not None:
            data, h["Content-Type"] = raw, ctype
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with OPENER(req, timeout=180) as r:
                doc = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 403):
                raise bz.ToolError(f"Tripo refused the key (HTTP {e.code}): check {TRIPO_ENV}")
            if e.code == 429:
                raise bz.JobError(f"Tripo {path}: too many requests or tasks at once (HTTP 429): wait and run again")
            raise bz.JobError(f"Tripo {path}: HTTP {e.code}: {msg}")
        except (urllib.error.URLError, OSError) as e:
            raise bz.ToolError(f"cannot reach Tripo ({self.base}): {e}")
        except ValueError:
            raise bz.JobError(f"Tripo {path}: the answer is not JSON")
        if doc.get("code", 0) != 0:
            raise bz.JobError(f"Tripo {path}: {doc.get('message') or doc}")
        return doc.get("data") or {}

    def balance(self):
        return float(self.call("GET", "/account/balance").get("balance", 0))

    def upload(self, data, filename, ctype):
        b = "----bozzetto" + uuid.uuid4().hex
        raw = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
               f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        tok = self.call("POST", "/files", raw=raw, ctype=f"multipart/form-data; boundary={b}").get("file_token")
        if not tok:
            raise bz.JobError("Tripo's upload returned no file_token")
        return tok

    def task(self, path, body, what, wait, on_created=None):
        """Create a task, journal it (on_created) before anything else can fail (#210), wait for it."""
        tid = self.call("POST", path, body=body).get("task_id")
        if not tid:
            raise bz.JobError(f"Tripo {what}: no task id")
        if on_created:
            on_created(tid)
        return tid, self.wait_for(tid, what, wait)

    def wait_for(self, tid, what, wait):
        t0 = time.monotonic()
        while True:
            d = self.call("GET", f"/tasks/{tid}")
            st = d.get("status")
            if st == "success":
                print(f"[ OK ] Tripo {what}: task {tid}, {time.monotonic() - t0:.0f} s, "
                      f"{float(d.get('credits_consumed') or 0):g} credits", flush=True)
                return d
            if st in FAILED:
                why = d.get("error_message") or ""
                code = d.get("error_code")
                raise bz.JobError(f"Tripo {what}: {st} (task {tid}" + (f", error {code}" if code is not None else "")
                                  + (f": {why}" if why else "") + "); a failed task costs no credits")
            if time.monotonic() - t0 > wait:
                raise bz.JobError(f"Tripo {what} did not finish in {wait} s (task {tid}; a re-run picks it up from "
                                  f"{JOURNAL} without paying again)")
            bz.SLEEP(POLL_S)

    def download(self, url, dst):
        """The result file. The link is Tripo's CDN: no key goes with it."""
        try:
            with OPENER(urllib.request.Request(url), timeout=300) as r:
                data = r.read()
        except (urllib.error.URLError, OSError) as e:
            raise bz.JobError(f"could not download Tripo's model ({e}); its links expire after about 5 minutes: run "
                              f"again, the paid task is kept in {JOURNAL} and a fresh link is fetched without paying")
        dst.write_bytes(data)
        return data


# ---- the journal and the cap -------------------------------------------------------------------------------------
class Journal:
    """tasks.json: every paid task, written as it is created and as it finishes (#210). Reused only when each input
    fact in `want` matches the file (and reuse is on); otherwise it starts empty."""

    def __init__(self, path, want, reuse=True):
        self.path = path
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        self.data = old if (reuse and all(old.get(k) == v for k, v in want.items())) else dict(want, tasks={})
        self.tasks = self.data.setdefault("tasks", {})

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")

    def done(self, step):
        return (self.tasks.get(step) or {}).get("status") == "success"

    def running(self, step, tid):
        self.tasks[step] = {"id": tid, "status": "running"}
        self.save()

    def finished(self, step, tid, credits, **extra):
        self.tasks[step] = dict({"id": tid, "status": "success", "credits": credits}, **extra)
        self.save()

    def spent(self):
        return sum(float(v.get("credits") or 0) for v in self.tasks.values())

    def settle(self, client, steps, wait, extra=None):
        """A task journalled as running (the last run timed out or was stopped after paying): ask Tripo how it ended
        before paying for another one (#221). extra(step, result) adds facts to a finished entry."""
        for step in steps:
            entry = self.tasks.get(step) or {}
            if entry.get("status") != "running" or not entry.get("id"):
                continue
            st = client.call("GET", f"/tasks/{entry['id']}").get("status")
            if st in FAILED:
                print(f"[info] the last run's {step} task {entry['id']} ended {st}; a new one will be made")
                del self.tasks[step]
                self.save()
                continue
            try:
                d = client.wait_for(entry["id"], f"{step} (from the last run)", wait)
            except bz.JobError:
                # still running after --wait: never pay for a second one while the first may still finish
                raise bz.ToolError(f"the last run's {step} task {entry['id']} is still running at Tripo; run again "
                                   f"later (it is kept in {JOURNAL}), or pass --no-reuse to pay for a new one")
            more = extra(step, d) if extra else {}
            self.finished(step, entry["id"], float(d.get("credits_consumed") or 0), **more)

    def reused(self):
        return ", ".join(f"{k} task {v['id']}" for k, v in self.tasks.items() if v.get("status") == "success")


class Budget:
    """--max-credits counts actual charges; the balance is checked too. afford() refuses before a paid call."""

    def __init__(self, cap, balance, spent=0.0):
        self.cap, self.balance, self.spent = cap, balance, spent

    def afford(self, more):
        if self.spent + more > self.cap:
            raise bz.ToolError(f"spending {more:g} more credits would make {self.spent + more:g} in all, over "
                               f"--max-credits {self.cap}; finished tasks are kept in {JOURNAL} for a re-run")
        if more > self.balance:
            raise bz.ToolError(f"the Tripo balance ({self.balance:g} credits) is under the next step ({more:g}); "
                               f"{NO_STUDIO}")

    def charge(self, cost):
        self.spent += cost
        self.balance -= cost
