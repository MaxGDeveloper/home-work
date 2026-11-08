# -*- coding: utf-8 -*-
"""Простая экспертная система диагностики неисправностей ПК.

Продукционная модель знаний и прямой логический вывод: правила вида
"ЕСЛИ <условия> ТО <действия>" проверяются по порядку и при срабатывании
добавляют, изменяют или удаляют факты рабочей памяти.
"""

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATES = {"симптом": "описание", "обследование": "результат",
             "причина": "статус"}


@dataclass
class Fact:
    """Факт рабочей памяти: экземпляр шаблона со значениями слотов."""

    template: str
    id: str
    slots: dict

    def __str__(self):
        details = ", ".join(f"{k}={v}" for k, v in self.slots.items())
        return f"{self.template}({self.id}{'; ' + details if details else ''})"


class WorkingMemory:
    """Рабочая память: хранение фактов и операции над ними."""

    def __init__(self, facts):
        self._facts = {(f.template, f.id): f for f in facts}

    def all(self, template=None):
        return [f for f in self._facts.values()
                if template is None or f.template == template]

    def match(self, template, ident=None, slots=None):
        return [f for f in self.all(template)
                if (ident is None or f.id == ident)
                and not any(f.slots.get(k) != v for k, v in (slots or {}).items())]

    def add(self, fact):
        if (fact.template, fact.id) in self._facts:
            return False, f"факт уже есть: {fact}"
        self._facts[(fact.template, fact.id)] = fact
        return True, f"добавлен факт {fact}"

    def modify(self, template, ident, slots):
        fact = self._facts.get((template, ident))
        if fact is None:
            return False, f"нет факта {template}({ident})"
        changes = ", ".join(f"{k}: {fact.slots.get(k)} -> {v}"
                            for k, v in slots.items() if fact.slots.get(k) != v)
        if not changes:
            return False, f"факт {fact} не изменился"
        fact.slots.update(slots)
        return True, f"изменён факт {template}({ident}): {changes}"

    def delete(self, template, ident):
        fact = self._facts.pop((template, ident), None)
        if fact is None:
            return False, f"нет факта {template}({ident})"
        return True, f"удалён факт {fact}"


@dataclass(frozen=True)
class Condition:
    """Условие правила: образец факта."""

    template: str
    id: str
    slots: dict = field(default_factory=dict)

    def describe(self):
        details = ", ".join(f"{k}={v}" for k, v in self.slots.items())
        return f"{self.template}({self.id}{'; ' + details if details else ''})"


@dataclass(frozen=True)
class Action:
    """Действие правила: операция над фактом."""

    op: str
    template: str
    id: str
    slots: dict = field(default_factory=dict)


def cond(template, ident, **slots):
    return Condition(template, ident, slots)


def add_fact(template, ident, **slots):
    return Action("add", template, ident, slots)


def change_fact(template, ident, **slots):
    return Action("modify", template, ident, slots)


def drop_fact(template, ident):
    return Action("delete", template, ident)


@dataclass
class Rule:
    """Продукция "ЕСЛИ ... ТО ..."."""

    number: str
    name: str
    conditions: list
    actions: list

    def is_applicable(self, wm):
        return all(wm.match(c.template, c.id, c.slots) for c in self.conditions)


def build_rules():
    """База знаний: три правила, порядок задаёт разрешение конфликтов."""
    return [
        Rule("П1", "Неисправность блока питания",
             [cond("симптом", "не_включается"),
              cond("обследование", "блок_питания", результат="неисправно"),
              cond("причина", "блок_питания", статус="возможна")],
             [change_fact("причина", "блок_питания", статус="подтверждена"),
              add_fact("обследование", "заменить_блок_питания",
                       результат="требуется")]),
        Rule("П2", "Перегрев процессора",
             [cond("симптом", "шум_вентилятора"),
              cond("симптом", "перегрев_корпуса"),
              cond("обследование", "температура_процессора",
                   результат="выше_нормы"),
              cond("причина", "перегрев", статус="возможна")],
             [change_fact("причина", "перегрев", статус="подтверждена"),
              add_fact("обследование", "очистить_охлаждение",
                       результат="требуется")]),
        Rule("П3", "Память исправна",
             [cond("обследование", "оперативная_память", результат="исправно"),
              cond("причина", "память", статус="возможна")],
             [change_fact("причина", "память", статус="опровергнута"),
              drop_fact("обследование", "тест_памяти")]),
    ]


class InferenceEngine:
    """Машина прямого вывода: цикл "распознавание - действие"."""

    def __init__(self, rules, facts, log=None):
        self.wm = WorkingMemory(facts)
        self.rules = rules
        self.log = log or sys.stdout
        self.fired = set()
        self.stats = {"fired": 0, "add": 0, "modify": 0, "delete": 0}

    def write(self, text=""):
        print(text, file=self.log)

    def run(self):
        while True:
            rule = next((r for r in self.rules if r.is_applicable(self.wm)
                         and r.number not in self.fired), None)
            if rule is None:
                return
            self.fired.add(rule.number)
            self.stats["fired"] += 1
            self.write(f"Сработало правило {rule.number} «{rule.name}»")
            self.write("  Условия выполнены:")
            for condition in rule.conditions:
                self.write("    " + condition.describe())
            self.write("  Действия:")
            for action in rule.actions:
                self.apply(action)
            self.write()

    def apply(self, action):
        if action.op == "add":
            ok, message = self.wm.add(
                Fact(action.template, action.id, dict(action.slots)))
        elif action.op == "modify":
            ok, message = self.wm.modify(
                action.template, action.id, dict(action.slots))
        else:
            ok, message = self.wm.delete(action.template, action.id)
        self.stats[action.op] += int(ok)
        self.write(f"    {'+' if ok else '-'} {message}")


def scenario():
    """ПК не включается, вентилятор шумит, корпус горячий."""
    return [
        Fact("симптом", "не_включается",
             {"описание": "при нажатии кнопки питания нет реакции"}),
        Fact("симптом", "шум_вентилятора", {"описание": "вентилятор шумит"}),
        Fact("симптом", "перегрев_корпуса", {"описание": "корпус горячий"}),
        Fact("обследование", "блок_питания", {"результат": "неисправно"}),
        Fact("обследование", "температура_процессора",
             {"результат": "выше_нормы"}),
        Fact("обследование", "оперативная_память", {"результат": "исправно"}),
        Fact("обследование", "тест_памяти", {"результат": "запланировано"}),
        Fact("причина", "блок_питания", {"статус": "возможна"}),
        Fact("причина", "перегрев", {"статус": "возможна"}),
        Fact("причина", "память", {"статус": "возможна"}),
    ]


class Tee:
    """Вывод одновременно в консоль и в файл протокола."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)


def main():
    log_path = Path(__file__).with_name("Трассировка.txt")
    with io.open(log_path, "w", encoding="utf-8") as log:
        out = Tee(sys.stdout, log)
        engine = InferenceEngine(build_rules(), scenario(), log=out)
        out.write("ЭКСПЕРТНАЯ СИСТЕМА ДИАГНОСТИКИ НЕИСПРАВНОСТЕЙ ПК\n")
        out.write("-" * 60 + "\n\n")
        out.write("Рабочая память до запуска машины вывода:\n")
        for template, slot in TEMPLATES.items():
            out.write(f"  {template}:\n")
            for fact in engine.wm.all(template):
                out.write(f"    - {fact}\n")
        out.write("\n")
        engine.run()
        out.write("РЕЗУЛЬТАТ ДИАГНОСТИКИ\n  Причины:\n")
        for fact in engine.wm.all("причина"):
            out.write(f"    - {fact.id}: {fact.slots[slot]}\n")
        out.write("\nИТОГО: срабатываний правил — {fired}, добавлено — {add}, "
                  "изменено — {modify}, удалено — {delete}\n"
                  .format(**engine.stats))


if __name__ == "__main__":
    main()
