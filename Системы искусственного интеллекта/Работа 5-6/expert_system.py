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

# Шаблон -> слот, значение которого показывается в протоколе.
TEMPLATES = {
    "симптом": "описание",
    "обследование": "результат",
    "причина": "статус",
}

# Заголовки групп фактов для блока «Исходные данные».
TEMPLATE_PLURALS = {
    "симптом": "Симптомы",
    "обследование": "Результаты обследований",
    "причина": "Возможные причины",
}

# Человекочитаемые названия причин и действий для итогового отчёта.
CAUSE_LABELS = {
    "блок_питания": "неисправность блока питания",
    "перегрев": "перегрев процессора",
    "память": "неисправность оперативной памяти",
}

ACTION_LABELS = {
    "заменить_блок_питания": "Заменить блок питания",
    "очистить_охлаждение": "Очистить систему охлаждения (вентилятор, радиатор)",
}


def human(text):
    return str(text).replace("_", " ")


def describe_fact(fact):
    label = human(fact.template).capitalize()
    ident = human(fact.id)
    primary = TEMPLATES.get(fact.template)
    if primary and primary in fact.slots:
        return f"{label} «{ident}»: {human(fact.slots[primary])}"
    if fact.slots:
        parts = ", ".join(f"{k} = {human(v)}" for k, v in fact.slots.items())
        return f"{label} «{ident}» ({parts})"
    return f"{label} «{ident}»"


@dataclass
class Fact:
    template: str
    id: str
    slots: dict


class WorkingMemory:
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
        key = (fact.template, fact.id)
        if key in self._facts:
            return False
        self._facts[key] = fact
        return True

    def modify(self, template, ident, slots):
        """Возвращает {слот: (старое, новое)} либо None, если менять нечего."""
        fact = self._facts.get((template, ident))
        if fact is None:
            return None
        changes = {k: (fact.slots.get(k), v) for k, v in slots.items()
                   if fact.slots.get(k) != v}
        if not changes:
            return None
        fact.slots.update(slots)
        return changes

    def delete(self, template, ident):
        return self._facts.pop((template, ident), None) is not None


@dataclass(frozen=True)
class Condition:
    template: str
    id: str
    slots: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
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
    number: str
    name: str
    conditions: list
    actions: list
    description: str = ""

    def is_applicable(self, wm):
        return all(wm.match(c.template, c.id, c.slots) for c in self.conditions)


def build_rules():
    return [
        Rule("П1", "Неисправность блока питания",
             [cond("симптом", "не_включается"),
              cond("обследование", "блок_питания", результат="неисправно"),
              cond("причина", "блок_питания", статус="возможна")],
             [change_fact("причина", "блок_питания", статус="подтверждена"),
              add_fact("обследование", "заменить_блок_питания",
                       результат="требуется")],
             "Если ПК не включается, а блок питания неисправен, "
             "то причина «блок питания» подтверждается."),
        Rule("П2", "Перегрев процессора",
             [cond("симптом", "шум_вентилятора"),
              cond("симптом", "перегрев_корпуса"),
              cond("обследование", "температура_процессора",
                   результат="выше_нормы"),
              cond("причина", "перегрев", статус="возможна")],
             [change_fact("причина", "перегрев", статус="подтверждена"),
              add_fact("обследование", "очистить_охлаждение",
                       результат="требуется")],
             "Если вентилятор шумит, корпус горячий и температура процессора "
             "выше нормы, то причина «перегрев» подтверждается."),
        Rule("П3", "Память исправна",
             [cond("обследование", "оперативная_память", результат="исправно"),
              cond("причина", "память", статус="возможна")],
             [change_fact("причина", "память", статус="опровергнута"),
              drop_fact("обследование", "тест_памяти")],
             "Если оперативная память исправна, то причина «память» "
             "опровергается, а запланированный тест памяти отменяется."),
    ]


class InferenceEngine:
    def __init__(self, rules, facts, log=None):
        self.wm = WorkingMemory(facts)
        self.rules = rules
        self.log = log or sys.stdout
        self.fired = set()
        self.stats = {"fired": 0, "add": 0, "modify": 0, "delete": 0}
        self.step = 0

    def write(self, text=""):
        print(text, file=self.log)

    def _describe_condition(self, condition, matched):
        if matched:
            return describe_fact(matched[0])
        label = human(condition.template).capitalize()
        ident = human(condition.id)
        if condition.slots:
            parts = ", ".join(f"{k} = {human(v)}"
                              for k, v in condition.slots.items())
            return f"{label} «{ident}» ({parts}) — НЕ найдено"
        return f"{label} «{ident}» — НЕ найдено"

    def _describe_action_result(self, action, ok, changes):
        label = human(action.template).capitalize()
        ident = human(action.id)
        if action.op == "add":
            text = describe_fact(
                Fact(action.template, action.id, dict(action.slots)))
            return f"+ Добавлено: {text}" if ok else f"· Уже в памяти: {text}"
        if action.op == "modify":
            if not changes:
                return f"· {label} «{ident}» не изменено"
            parts = "; ".join(
                f"{k}: «{human(old)}» → «{human(new)}»"
                for k, (old, new) in changes.items())
            return f"→ {label} «{ident}»: {parts}"
        if ok:
            return f"− Удалено: {label} «{ident}»"
        return f"· {label} «{ident}» — не найдено, удалять нечего"

    def run(self):
        while True:
            applicable = None
            for rule in self.rules:
                if rule.number in self.fired:
                    continue
                self.step += 1
                self.write(f"Шаг {self.step}. Правило {rule.number} «{rule.name}»")
                if rule.description:
                    self.write(f"  Смысл: {rule.description}")
                self.write("  Проверка условий:")
                all_ok = True
                for condition in rule.conditions:
                    matched = self.wm.match(
                        condition.template, condition.id, condition.slots)
                    mark = "✓" if matched else "✗"
                    self.write(f"    {mark} "
                               f"{self._describe_condition(condition, matched)}")
                    if not matched:
                        all_ok = False
                if not all_ok:
                    self.write("  → Условия не выполнены, правило пропускается.\n")
                    continue
                applicable = rule
                break
            if applicable is None:
                return
            self.write("  → Все условия выполнены. Выполняем действия:")
            self.fired.add(applicable.number)
            self.stats["fired"] += 1
            for action in applicable.actions:
                self.apply(action)
            self.write()

    def apply(self, action):
        changes = None
        if action.op == "add":
            ok = self.wm.add(Fact(action.template, action.id,
                                  dict(action.slots)))
        elif action.op == "modify":
            changes = self.wm.modify(action.template, action.id,
                                     dict(action.slots))
            ok = changes is not None
        else:
            ok = self.wm.delete(action.template, action.id)
        self.stats[action.op] += int(ok)
        self.write("    " + self._describe_action_result(action, ok, changes))


def scenario():
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
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)


def write_initial_state(engine, out):
    out.write("ИСХОДНЫЕ ДАННЫЕ (рабочая память)\n")
    out.write("-" * 60 + "\n")
    for template in TEMPLATES:
        facts = engine.wm.all(template)
        if not facts:
            continue
        out.write(f"{TEMPLATE_PLURALS.get(template, template)}:\n")
        for fact in facts:
            out.write("  • " + describe_fact(fact) + "\n")
    out.write("\n")


def write_result(engine, out):
    out.write("=" * 60 + "\n")
    out.write("РЕЗУЛЬТАТ ДИАГНОСТИКИ\n")
    out.write("=" * 60 + "\n\n")

    causes = engine.wm.all("причина")
    confirmed = [f for f in causes if f.slots.get("статус") == "подтверждена"]
    refuted = [f for f in causes if f.slots.get("статус") == "опровергнута"]

    out.write("Подтверждённые причины:\n")
    if confirmed:
        for f in confirmed:
            out.write(f"  ⚠  {CAUSE_LABELS.get(f.id, human(f.id))}\n")
    else:
        out.write("  — нет\n")
    out.write("\n")

    out.write("Опровергнутые причины:\n")
    if refuted:
        for f in refuted:
            out.write(f"  ✓ {CAUSE_LABELS.get(f.id, human(f.id))}\n")
    else:
        out.write("  — нет\n")
    out.write("\n")

    recs = [f for f in engine.wm.all("обследование")
            if f.slots.get("результат") == "требуется"]
    out.write("Рекомендуемые действия:\n")
    if recs:
        for i, f in enumerate(recs, 1):
            out.write(f"  {i}. {ACTION_LABELS.get(f.id, human(f.id))}\n")
    else:
        out.write("  — нет\n")
    out.write("\n")

    out.write(
        "Статистика: сработало правил — {fired}, "
        "добавлено фактов — {add}, изменено — {modify}, удалено — {delete}\n"
        .format(**engine.stats))


def main():
    log_path = Path(__file__).with_name("Трассировка.txt")
    with io.open(log_path, "w", encoding="utf-8") as log:
        out = Tee(sys.stdout, log)
        engine = InferenceEngine(build_rules(), scenario(), log=out)
        out.write("=" * 60 + "\n")
        out.write("ЭКСПЕРТНАЯ СИСТЕМА ДИАГНОСТИКИ НЕИСПРАВНОСТЕЙ ПК\n")
        out.write("=" * 60 + "\n\n")
        write_initial_state(engine, out)
        out.write("=" * 60 + "\n")
        out.write("ЛОГИЧЕСКИЙ ВЫВОД (прямая цепочка рассуждений)\n")
        out.write("=" * 60 + "\n\n")
        engine.run()
        write_result(engine, out)


if __name__ == "__main__":
    main()