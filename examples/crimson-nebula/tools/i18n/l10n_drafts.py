#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# l10n_drafts.py
# Purpose : Machine drafts for the localization round trip (l10n.py draft) from a model on this machine, through a
#           pluggable backend: any OpenAI-compatible local server (LM Studio, llama.cpp's llama-server, Ollama's
#           /v1, vLLM ...) or any command that reads a JSON request on stdin and prints the draft.
# Usage   : import l10n_drafts as drafts
#           be = drafts.make_backend("openai", url="http://127.0.0.1:1234/v1", model="<id>")
#           be = drafts.make_backend("command", command=["python", "my_translator.py"])
#           text = be.translate({"text": "Play", "source": "en", "target": "fr", "note": "", "max": 12, "key": ...})
# Notes   : Presets: lmstudio = openai at 127.0.0.1:1234/v1, ollama = openai at 127.0.0.1:11434/v1 (Ollama's
#           OpenAI-compatible endpoint, not tried on the test machine: verify), llamacpp = openai at
#           127.0.0.1:8080/v1. The URL must be this machine (127.0.0.1, localhost, ::1) unless allow_remote: the
#           strings leave the machine otherwise, and a hosted API may cost money. Without a model name the openai
#           backend asks the server's /models and takes the first. A reply's <think>...</think> block (reasoning
#           models), wrapping quotes and a "Translation:" label are stripped. The draft is checked by the caller
#           (placeholders, length); this module only fetches text. Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   openai : POST <url>/chat/completions {model, messages: [system rules, user text], temperature} -> content
#   command: run argv, stdin = JSON request, stdout = {"text": ...} or plain text
#   clean  : drop <think> blocks, quotes, labels; strip
import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request

# ---- constants -------------------------------------------------------------------------------------------------
PRESETS = {"lmstudio": "http://127.0.0.1:1234/v1", "ollama": "http://127.0.0.1:11434/v1",
           "llamacpp": "http://127.0.0.1:8080/v1"}
BACKENDS = ("openai", "command") + tuple(PRESETS)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TEMPERATURE = 0.2
TIMEOUT_S = 120
# a reasoning model thinks before it answers (its reasoning_content is not the answer): enough room for that, but
# a cap, so one line cannot run for minutes. A reply cut off before any answer comes back empty and is rejected.
MAX_TOKENS = 2048
SYSTEM_PROMPT = (
    "You translate short user-interface and dialogue strings of a video game from {src} to {dst}. Rules: reply "
    "with the translation only, no quotes, no explanation. Keep every placeholder exactly as written, such as "
    "{{name}} or %d, and add none. Keep the tone and the punctuation style. If a maximum length is given, stay "
    "within it.")


class DraftError(RuntimeError):
    pass


def make_backend(name, url=None, model=None, command=None, allow_remote=False, timeout=TIMEOUT_S):
    if name == "command":
        if not command:
            raise DraftError("the command backend needs --command (the program that prints a draft)")
        return CommandBackend(command, timeout)
    if name in PRESETS or name == "openai":
        url = url or PRESETS.get(name)
        if not url:
            raise DraftError("the openai backend needs --url (for example http://127.0.0.1:1234/v1)")
        host = urllib.parse.urlparse(url).hostname or ""
        if host not in LOCAL_HOSTS and not allow_remote:
            raise DraftError(f"{url} is not this machine: drafts come from a local model (add --allow-remote "
                             "only if you mean to send the game's strings elsewhere)")
        return OpenAIBackend(url.rstrip("/"), model, timeout)
    raise DraftError(f"unknown backend {name!r} (have: {', '.join(BACKENDS)})")


def user_prompt(req):
    lines = [req["text"]]
    extra = []
    if req.get("note"):
        extra.append(f"Context: {req['note']}")
    if req.get("max"):
        extra.append(f"Maximum length: {req['max']} characters")
    # the string id is left out on purpose: a small local model translated ids like settings.tab.controls into
    # the text (K01, a 1B model in the first live run). The context note carries what the id would have said.
    return "\n".join(lines + ([""] + extra if extra else []))


def clean(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^(translation|traduction|перевод)\s*:\s*", "", text, flags=re.I)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“«":
        text = text[1:-1]
    elif len(text) >= 2 and (text[0], text[-1]) in (("“", "”"), ("«", "»")):
        text = text[1:-1].strip()
    return text.strip()


class OpenAIBackend(object):
    def __init__(self, url, model, timeout):
        self.url, self.model, self.timeout = url, model, timeout

    def _call(self, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raise DraftError(f"{self.url}{path}: HTTP {e.code} {e.read()[:200].decode('utf-8', 'replace')}")
        except socket.timeout:
            raise DraftError(f"{self.url}: no answer in {self.timeout} s (a slow or reasoning model: raise "
                             "--timeout, or pick a smaller model)")
        except (urllib.error.URLError, OSError) as e:
            if isinstance(getattr(e, "reason", None), socket.timeout):
                raise DraftError(f"{self.url}: no answer in {self.timeout} s (a slow or reasoning model: raise "
                                 "--timeout, or pick a smaller model)")
            raise DraftError(f"{self.url}: no model server answering ({getattr(e, 'reason', e)}); start it "
                             "(LM Studio: lms server start; Ollama: ollama serve) and load a model")
        except ValueError as e:
            raise DraftError(f"{self.url}{path}: the reply is not JSON ({e})")

    def pick_model(self):
        if not self.model:
            got = self._call("/models")
            ids = [m.get("id") for m in got.get("data", []) if isinstance(m, dict) and m.get("id")]
            ids = [i for i in ids if "embed" not in i.lower()] or ids
            if not ids:
                raise DraftError(f"{self.url} lists no model: load one, or pass --model")
            self.model = ids[0]
        return self.model

    def translate(self, req):
        system = SYSTEM_PROMPT.format(src=req["source_name"], dst=req["target_name"])
        body = {"model": self.pick_model(), "temperature": TEMPERATURE, "stream": False, "max_tokens": MAX_TOKENS,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_prompt(req)}]}
        got = self._call("/chat/completions", body)
        try:
            choice = got["choices"][0]
            text = clean(choice["message"].get("content") or "")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise DraftError(f"{self.url}: unexpected reply {json.dumps(got)[:200]}")
        return text


class CommandBackend(object):
    def __init__(self, argv, timeout):
        self.argv, self.timeout, self.model = list(argv), timeout, "command"

    def pick_model(self):
        return " ".join(self.argv)

    def translate(self, req):
        try:
            # UTF-8 both ways; PYTHONUTF8 makes a Python translator script print UTF-8 on Windows too
            env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            p = subprocess.run(self.argv, input=json.dumps(req, ensure_ascii=False), capture_output=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout, env=env)
        except FileNotFoundError:
            raise DraftError(f"{self.argv[0]}: not found")
        except subprocess.TimeoutExpired:
            raise DraftError(f"{' '.join(self.argv)}: no answer in {self.timeout} s")
        if p.returncode != 0:
            raise DraftError(f"{' '.join(self.argv)} exited {p.returncode}: {p.stderr.strip()[:200]}")
        out = p.stdout.strip()
        try:
            data = json.loads(out)
            if isinstance(data, dict) and "text" in data:
                return clean(str(data["text"]))
        except ValueError:
            pass
        return clean(out)
