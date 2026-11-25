"""Running one PowerShell script as administrator, safely.

Used for everything that needs rights: installing Windows Update offers,
cleaning system folders, running DISM, updating Defender's definitions.

**Why the script is verified before it runs.** The script is too long for
ShellExecute's parameter string, so it is written to a file and a short
bootstrap -- passed with `-EncodedCommand` -- runs it. The file lives under
`%ProgramData%\\SoftwareUpdater\\jobs` because the administrator who answers
the prompt may be a different account that cannot read this user's profile.
But ProgramData lets any local user create folders: someone could create
`SoftwareUpdater\\jobs` first, own it, and swap the script between this
application writing it and the administrator's PowerShell running it. That
would be code of theirs run with administrator rights.

So the bootstrap carries the SHA-256 of the script as written. It reads the
file's bytes once, hashes *those bytes*, and runs *those bytes* only if the
hash matches; there is no second read for anyone to race. Everything the
script acts on -- update ids, folders to clean -- is written into the script
text before it is hashed, so no separate data file can be tampered with.
0.1.0 passed the request in a separate file and did not check the script;
this replaced it in 0.2.0.

The result file comes back the same way and is only ever *displayed*; a
forged result could mislead the window, never make it do anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass

from app.io import elevate, powershell, scripts

#: The bootstrap's exit code when the script on disk is not the one written.
TAMPERED = 99


@dataclass
class Outcome:
    ok: bool
    data: dict | None = None
    error: str = ""


def jobs_folder() -> str:
    base = os.environ.get("ProgramData") or r"C:\ProgramData"
    return os.path.join(base, "SoftwareUpdater", "jobs")


def bootstrap(body_path: str, digest: str, result_path: str) -> str:
    return (
        "$ErrorActionPreference = 'Stop'\n"
        f"$b = [IO.File]::ReadAllBytes({scripts.quote(body_path)})\n"
        "$h = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create()"
        ".ComputeHash($b)).Replace('-', '')\n"
        f"if ($h -ne '{digest.upper()}') {{ exit {TAMPERED} }}\n"
        "$t = [Text.Encoding]::UTF8.GetString($b)\n"
        f"& ([scriptblock]::Create($t)) {scripts.quote(result_path)}\n"
    )


def run(script: str, *, timeout: float, cancel: threading.Event | None = None) -> Outcome:
    """Run `script` elevated. It receives the result file's path as
    `$args[0]` and writes one JSON object there."""
    folder = jobs_folder()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        return Outcome(False, error=f"Could not prepare {folder}: {exc}")
    # A jobs folder (or its parent) that is a junction or link sends what
    # the administrator writes somewhere else. Refuse rather than follow.
    from app.io import files

    if files.is_link(folder) or files.is_link(os.path.dirname(folder)):
        return Outcome(False, error=f"Refused: {folder} is a link to somewhere else. "
                                    "Delete it and try again.")
    name = uuid.uuid4().hex
    body = os.path.join(folder, f"{name}.ps1")
    result = os.path.join(folder, f"{name}.result.json")
    payload = script.encode("utf-8")     # no byte order mark: hashed as written
    try:
        with open(body, "wb") as handle:
            handle.write(payload)
        digest = hashlib.sha256(payload).hexdigest()
        boot = bootstrap(body, digest, result)
        parameters = " ".join([*powershell.ARGS, "-EncodedCommand", powershell.encode(boot)])
        ran = elevate.run(powershell.executable(), parameters, timeout=timeout, cancel=cancel)
        if not ran.started or ran.declined or ran.cancelled or ran.timed_out:
            return Outcome(False, error=ran.error or "Not started.")
        if ran.code == TAMPERED:
            return Outcome(False, error="Stopped: the script on disk was changed before it ran. "
                                        "Nothing was done.")
        try:
            with open(result, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return Outcome(False, error=f"Finished (exit {ran.code}) without writing a result.")
        if not isinstance(data, dict):
            return Outcome(False, error="The result was not readable.")
        return Outcome(True, data)
    finally:
        for path in (body, result):
            try:
                os.remove(path)
            except OSError:
                pass

