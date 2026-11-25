"""From chosen rows to the steps that update them. Pure.

Two ways exist to update something, and they behave differently enough that
a plan keeps them apart:

- **winget**, one package at a time, run as the user. Each step is its own
  installer; one failing does not stop the next. A per-machine package's
  installer asks for elevation itself.
- **Windows Update**, every chosen offer in one elevated run. The agent
  downloads and installs a set together and wants one administrator prompt
  for it, not one per driver.

winget steps go first. They are quick, they are what people usually mean,
and the Windows Update run can end with a request to restart.

A row with no way to update it here (old drivers, programs winget does not
know) is listed in `manual`, so the confirmation can say what will not
happen as plainly as what will.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.inventory import Action, Item
from app.core.versions import is_known


@dataclass
class Step:
    key: str
    name: str
    winget_id: str = ""
    winget_source: str = ""
    unknown_version: bool = False


@dataclass
class Plan:
    winget: list[Step] = field(default_factory=list)
    wu: list[Item] = field(default_factory=list)
    manual: list[Item] = field(default_factory=list)

    @property
    def wu_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for item in self.wu:
            for ident in item.wu_ids:
                seen.setdefault(ident, None)
        return list(seen)

    @property
    def empty(self) -> bool:
        return not self.winget and not self.wu

    def describe(self) -> list[str]:
        lines = []
        if self.winget:
            lines.append(f"{len(self.winget)} with winget, one after another:")
            lines.extend(f"    {s.name}" for s in self.winget)
        if self.wu:
            lines.append(f"{len(self.wu)} from Windows Update, together, after one "
                         "administrator prompt:")
            lines.extend(f"    {i.name}" for i in self.wu)
        if self.manual:
            lines.append(f"{len(self.manual)} cannot be updated from here and are left out:")
            lines.extend(f"    {i.name}" for i in self.manual)
        return lines


def build(items: list[Item]) -> Plan:
    plan = Plan()
    for item in items:
        if item.updatable and item.action == Action.WINGET and item.winget_id:
            source = item.winget_source if item.winget_source in ("winget", "msstore") else ""
            plan.winget.append(Step(item.key, item.name, item.winget_id, source,
                                    unknown_version=not is_known(item.installed)))
        elif item.updatable and item.action == Action.WU and item.wu_ids:
            plan.wu.append(item)
        else:
            plan.manual.append(item)
    return plan
