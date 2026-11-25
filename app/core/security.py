"""Judging this computer's security settings. Pure.

`io/scripts.SECURITY` collects facts; `evaluate` turns them into findings,
each with a level, a sentence saying what was found, why it matters, and
where to fix it. The checks are the ones that matter most on a Windows work
machine and can be read without administrator rights.

This page **never changes a security setting itself**. Each fix opens the
Windows page where the setting lives, because on a managed machine the
setting may be owned by the organization, and because turning protection
off or on is a decision a person should see being made. The one action it
runs is updating Defender's definitions, which only fetches Microsoft's own
files.

Windows support dates are Microsoft's published end-of-updates dates
(learn.microsoft.com, Windows release health, checked 2026-11-25). A build
newer than any in the table is assumed supported; add new versions here as
Microsoft publishes them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

GOOD, INFO, WARN, BAD, UNKNOWN = "good", "info", "warn", "bad", "unknown"
LEVEL_LABELS = {GOOD: "OK", INFO: "Note", WARN: "Attention", BAD: "Risk", UNKNOWN: "Unknown"}
LEVEL_ORDER = {BAD: 0, WARN: 1, UNKNOWN: 2, INFO: 3, GOOD: 4}


@dataclass
class Finding:
    id: str
    title: str
    level: str
    summary: str
    detail: str = ""
    fix_label: str = ""
    fix_target: str = ""         # a URI or program for io/system.open_target
    fix_args: str = ""
    #: Something this application does itself rather than a page it opens.
    action: str = ""


#: Windows build -> (version, end for Home/Pro, end for Enterprise/Education).
SUPPORT: dict[int, tuple[str, str, str]] = {
    19045: ("Windows 10 22H2", "2025-10-14", "2025-10-14"),
    22000: ("Windows 11 21H2", "2023-10-10", "2024-10-08"),
    22621: ("Windows 11 22H2", "2024-10-08", "2025-10-14"),
    22631: ("Windows 11 23H2", "2025-11-11", "2026-11-10"),
    26100: ("Windows 11 24H2", "2026-10-13", "2027-10-12"),
    26200: ("Windows 11 25H2", "2027-10-12", "2028-10-10"),
}

LONG_EDITIONS = ("enterprise", "education", "iot")

BROWSERS = ("google chrome", "microsoft edge", "mozilla firefox", "firefox", "brave",
            "opera", "vivaldi")


def _date(text: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(text[:10])
    except (TypeError, ValueError):
        return None


def os_support(facts: dict, today: _dt.date) -> Finding:
    os = facts.get("os") or {}
    build = int(os.get("build") or 0)
    edition = str(os.get("edition") or os.get("caption") or "").lower()
    caption = str(os.get("caption") or "Windows")
    fix = dict(fix_label="Open Windows Update", fix_target="ms-settings:windowsupdate")
    if not build:
        return Finding("os", "Windows version", UNKNOWN, "Could not read the Windows version.")
    known = [b for b in SUPPORT if b <= build]
    if not known:
        return Finding("os", "Windows version", BAD,
                       f"{caption} (build {build}) is older than any version still supported.",
                       "It no longer receives security updates.", **fix)
    if build not in SUPPORT and build > max(SUPPORT):
        return Finding("os", "Windows version", GOOD,
                       f"{caption}, build {build}: newer than the versions this check knows.")
    version, home_end, long_end = SUPPORT[max(known)]
    longer = any(word in edition for word in LONG_EDITIONS)
    end = _date(long_end if longer else home_end)
    if end is None:
        return Finding("os", "Windows version", UNKNOWN, f"{version}.")
    days = (end - today).days
    if days < 0:
        return Finding("os", "Windows version", BAD,
                       f"{version} stopped receiving security updates on {end.isoformat()}.",
                       "Install the newest Windows 11 feature update (Windows Update, or your "
                       "IT department on a managed PC).", **fix)
    if days < 90:
        return Finding("os", "Windows version", WARN,
                       f"{version} stops receiving security updates on {end.isoformat()} "
                       f"({days} days).", "Plan the feature update before then.", **fix)
    return Finding("os", "Windows version", GOOD,
                   f"{version}, supported until {end.isoformat()}.")


def evaluate(facts: dict, *, today: _dt.date, items: list | None = None) -> list[Finding]:
    out = [os_support(facts, today)]
    managed = any(w in str((facts.get("os") or {}).get("edition") or "").lower()
                  for w in LONG_EDITIONS)
    note = " On a work PC this may be set by your IT department." if managed else ""

    # Antivirus.
    defender = facts.get("defender")
    others = [n for n in facts.get("antivirus") or [] if n and "defender" not in n.lower()]
    av = dict(fix_label="Open Windows Security", fix_target="windowsdefender:")
    if isinstance(defender, dict) and defender.get("enabled") and defender.get("realtime"):
        age = int(defender.get("signatureAge") or 0)
        if age > 3:
            out.append(Finding("antivirus", "Antivirus", WARN,
                               f"Microsoft Defender is on, but its definitions are {age} days old.",
                               "Definitions normally update daily.",
                               fix_label="Update definitions", action="defender-update"))
        else:
            tamper = "" if defender.get("tamper") else " Tamper protection is off."
            out.append(Finding("antivirus", "Antivirus", GOOD if not tamper else INFO,
                               "Microsoft Defender is on with current definitions." + tamper,
                               **(av if tamper else {})))
    elif others:
        out.append(Finding("antivirus", "Antivirus", GOOD,
                           f"Protected by {', '.join(others)}."))
    elif isinstance(defender, dict):
        out.append(Finding("antivirus", "Antivirus", BAD,
                           "Real-time protection is off and no other antivirus is registered.",
                           "Files are not scanned as they arrive." + note, **av))
    else:
        out.append(Finding("antivirus", "Antivirus", UNKNOWN,
                           "Could not read the antivirus status.",
                           str(facts.get("defenderError") or ""), **av))

    # Firewall.
    profiles = facts.get("firewall")
    fw = dict(fix_label="Open firewall settings", fix_target="windowsdefender://network")
    if isinstance(profiles, list) and profiles:
        off = [p.get("name") for p in profiles if isinstance(p, dict) and not p.get("enabled")]
        if off:
            out.append(Finding("firewall", "Firewall", BAD,
                               f"The firewall is off for: {', '.join(map(str, off))}.",
                               "Other machines on that network can reach every listening "
                               "service." + note, **fw))
        else:
            out.append(Finding("firewall", "Firewall", GOOD, "On for every network profile."))
    else:
        out.append(Finding("firewall", "Firewall", UNKNOWN, "Could not read the firewall.",
                           str(facts.get("firewallError") or ""), **fw))

    # Disk encryption.
    state = facts.get("bitlocker")
    bl = dict(fix_label="Open BitLocker", fix_target="control.exe",
              fix_args="/name Microsoft.BitLockerDriveEncryption")
    if state in (1, 3, 5, 6):
        text = {1: "on", 3: "encrypting", 5: "on but suspended", 6: "on"}[state]
        level = WARN if state == 5 else GOOD
        out.append(Finding("bitlocker", "Disk encryption", level,
                           f"BitLocker on the system drive: {text}.",
                           "Suspended protection is usually resumed after the next restart."
                           if state == 5 else "", **(bl if state == 5 else {})))
    elif state == 2:
        out.append(Finding("bitlocker", "Disk encryption", WARN,
                           "The system drive is not encrypted.",
                           "Anyone holding the computer can read its disk." + note, **bl))
    else:
        out.append(Finding("bitlocker", "Disk encryption", UNKNOWN,
                           "Could not read BitLocker's state on the system drive."))

    # Secure Boot.
    secure = facts.get("secureBoot")
    if secure == 1:
        out.append(Finding("secureboot", "Secure Boot", GOOD, "On."))
    elif secure == 0:
        out.append(Finding("secureboot", "Secure Boot", WARN,
                           "Secure Boot is off.",
                           "It stops tampered boot loaders. It is turned on in the PC's UEFI "
                           "settings, not in Windows."))
    else:
        out.append(Finding("secureboot", "Secure Boot", UNKNOWN,
                           "Not reported: the PC may boot in legacy BIOS mode."))

    # UAC.
    uac = facts.get("uac") or {}
    uac_fix = dict(fix_label="Open UAC settings", fix_target="UserAccountControlSettings.exe")
    if uac.get("enableLua") == 0:
        out.append(Finding("uac", "User Account Control", BAD, "UAC is turned off.",
                           "Every program runs with full rights without asking.", **uac_fix))
    elif uac.get("consentAdmin") == 0:
        out.append(Finding("uac", "User Account Control", WARN,
                           "Administrators are elevated without being asked.", **uac_fix))
    elif uac.get("enableLua") == 1:
        out.append(Finding("uac", "User Account Control", GOOD, "On."))

    # SMBv1.
    smb = facts.get("smb1") or {}
    smb_fix = dict(fix_label="Open Windows features", fix_target="optionalfeatures.exe")
    if smb.get("server") == 1:
        out.append(Finding("smb1", "SMB version 1", BAD,
                           "This PC serves files over SMBv1.",
                           "SMBv1 is the protocol WannaCry spread through.", **smb_fix))
    elif smb.get("clientStart") not in (None, 4):
        out.append(Finding("smb1", "SMB version 1", WARN,
                           "The SMBv1 client is installed.",
                           "Needed only for very old file servers and NAS boxes.", **smb_fix))
    else:
        out.append(Finding("smb1", "SMB version 1", GOOD, "Off."))

    # Remote Desktop.
    rdp = facts.get("rdp") or {}
    rdp_fix = dict(fix_label="Open Remote Desktop settings", fix_target="ms-settings:remotedesktop")
    if rdp.get("deny") == 0:
        if rdp.get("nla") == 0:
            out.append(Finding("rdp", "Remote Desktop", BAD,
                               "Remote Desktop is on without Network Level Authentication.",
                               "The sign-in screen is exposed to anyone who can reach the port.",
                               **rdp_fix))
        else:
            out.append(Finding("rdp", "Remote Desktop", INFO,
                               "Remote Desktop is on, with Network Level Authentication.",
                               "Turn it off if nobody connects to this PC." + note, **rdp_fix))
    elif rdp.get("deny") == 1:
        out.append(Finding("rdp", "Remote Desktop", GOOD, "Off."))

    # Credentials in memory and in the registry.
    if facts.get("wdigest") == 1:
        out.append(Finding("wdigest", "WDigest", BAD,
                           "WDigest keeps sign-in passwords in memory in plain text.",
                           "Set UseLogonCredential to 0, or ask IT." + note))
    autologon = facts.get("autologon") or {}
    if str(autologon.get("enabled")) == "1" and autologon.get("storedPassword"):
        out.append(Finding("autologon", "Automatic sign-in", BAD,
                           "Windows signs in automatically with a password stored in the "
                           "registry.",
                           "Anyone with the PC, or any program, can read that password."))
    if facts.get("lsa") in (1, 2):
        out.append(Finding("lsa", "LSA protection", GOOD, "On."))
    else:
        out.append(Finding("lsa", "LSA protection", INFO,
                           "LSA protection is off.",
                           "It makes stealing sign-in secrets from memory harder.",
                           fix_label="Open Device security",
                           fix_target="windowsdefender://devicesecurity"))

    # Accounts.
    if facts.get("guest"):
        out.append(Finding("guest", "Guest account", BAD, "The Guest account is enabled.",
                           fix_label="Open accounts", fix_target="ms-settings:otherusers"))
    admins = facts.get("admins")
    if isinstance(admins, list):
        level = INFO if facts.get("userIsAdmin") or len(admins) > 2 else GOOD
        detail = ("You sign in with an administrator account. A standard account for daily "
                  "use limits what malware running as you can do." if facts.get("userIsAdmin")
                  else "")
        out.append(Finding("admins", "Administrators", level,
                           f"{len(admins)} member(s) of Administrators: "
                           f"{', '.join(map(str, admins))}.", detail))

    # Patching.
    wu_fix = dict(fix_label="Open Windows Update", fix_target="ms-settings:windowsupdate")
    if str(facts.get("updateService") or "") == "Disabled":
        out.append(Finding("wuservice", "Windows Update service", BAD,
                           "The Windows Update service is disabled.", note.strip(), **wu_fix))
    last = _date(str(facts.get("lastPatch") or ""))
    if last is not None:
        days = (today - last).days
        level = GOOD if days <= 45 else WARN if days <= 90 else BAD
        out.append(Finding("lastpatch", "Last update installed", level,
                           f"{last.isoformat()} ({days} days ago).",
                           "" if level == GOOD else "Monthly security updates are not arriving.",
                           **({} if level == GOOD else wu_fix)))
    if facts.get("pendingReboot"):
        out.append(Finding("reboot", "Restart pending", WARN,
                           "Updates are waiting for a restart to finish installing.",
                           "Until then the old, vulnerable files are still in use.", **wu_fix))

    out.extend(from_inventory(items or []))
    return sorted(out, key=lambda f: LEVEL_ORDER.get(f.level, 9))


def from_inventory(items: list) -> list[Finding]:
    """What the Software page found that matters for security."""
    from app.core.inventory import Kind, Status

    out = []
    stale = [i for i in items if i.kind == Kind.APP and i.status == Status.UPDATE
             and any(b in i.name.lower() for b in BROWSERS)]
    if stale:
        out.append(Finding("browsers", "Web browsers", BAD,
                           "Out of date: " + ", ".join(i.name for i in stale) + ".",
                           "Browsers are the most attacked programs on a PC. Update them on "
                           "the Software page.", action="show-software"))
    security_updates = [i for i in items if i.kind == Kind.WINDOWS and i.status == Status.UPDATE
                        and any("security" in str(v).lower() or "critical" in str(v).lower()
                                for _label, v in i.facts)]
    if security_updates:
        out.append(Finding("wu-security", "Windows security updates", BAD,
                           f"{len(security_updates)} security update(s) not installed.",
                           "Install them on the Software page (Windows).", action="show-software"))
    apps = [i for i in items if i.kind == Kind.APP and i.status == Status.UPDATE]
    if apps and not stale:
        out.append(Finding("apps", "Application updates", INFO,
                           f"{len(apps)} application(s) have updates.",
                           "Old versions often carry fixed security holes.",
                           action="show-software"))
    return out
