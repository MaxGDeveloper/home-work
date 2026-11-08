# -*- coding: utf-8 -*-
"""Простая экспертная система диагностики неисправностей персонального компьютера.

Реализованы продукционная модель знаний и машина прямого логического вывода:
факты хранятся в рабочей памяти, правила вида "ЕСЛИ <условия> ТО <действия>"
проверяются по порядку, при срабатывании правило добавляет, изменяет или
удаляет факты. Работа машины вывода протоколируется.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Модель знаний: шаблоны фактов
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, list[str]] = {
    "симптом": ["описание"],
    "обследование": ["результат"],
    "гипотеза": ["статус"],
    "рекомендация": ["приоритет"],
}


@dataclass
class Fact:
    """Факт рабочей памяти: экземпляр шаблона с набором слотов."""

    template: str
    id: str
    slots: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        details = ", ".join(f"{k}={v}" for k, v in self.slots.items())
        if not details:
            return f"{self.template}({self.id})"
        return f"{self.template}({self.id}; {details})"


# ---------------------------------------------------------------------------
# Рабочая память
# ---------------------------------------------------------------------------


class WorkingMemory:
    """База фактов (рабочая память) экспертной системы."""

    def __init__(self, facts: list[Fact] | None = None) -> None:
        self._facts: dict[tuple[str, str], Fact] = {}
        for fact in facts or []:
            self._facts[(fact.template, fact.id)] = fact

    def get(self, template: str, ident: str) -> Fact | None:
        return self._facts.get((template, ident))

    def all(self, template: str | None = None) -> list[Fact]:
        return [f for f in self._facts.values()
                if template is None or f.template == template]

    def match(
        self,
        template: str,
        ident: str | None = None,
        slots: dict[str, str] | None = None,
    ) -> list[Fact]:
        """Факты, подходящие под образец: шаблон, идентификатор, слоты."""
        found = []
        for fact in self.all(template):
            if ident is not None and fact.id != ident:
                continue
            if slots and any(fact.slots.get(k) != v for k, v in slots.items()):
                continue
            found.append(fact)
        return found

    def add(self, fact: Fact) -> tuple[bool, str]:
        key = (fact.template, fact.id)
        if key in self._facts:
            return False, f"факт уже есть в рабочей памяти: {fact}"
        self._facts[key] = fact
        return True, f"добавлен факт {fact}"

    def modify(self, template: str, ident: str, slots: dict[str, str]) -> tuple[bool, str]:
        fact = self._facts.get((template, ident))
        if fact is None:
            return False, f"не найден факт {template}({ident}) для изменения"
        old = {k: fact.slots.get(k) for k in slots}
        fact.slots.update(slots)
        changes = ", ".join(f"{k}: {old[k]} -> {fact.slots[k]}"
                            for k in slots if old[k] != fact.slots[k])
        if not changes:
            return False, f"факт {fact} не изменился"
        return True, f"изменён факт {template}({ident}): {changes}"

    def delete(self, template: str, ident: str) -> tuple[bool, str]:
        fact = self._facts.pop((template, ident), None)
        if fact is None:
            return False, f"не найден факт {template}({ident}) для удаления"
        return True, f"удалён факт {fact}"


# ---------------------------------------------------------------------------
# Продукционные правила
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    """Условие правила: наличие в рабочей памяти факта под образец."""

    template: str
    id: str | None = None
    slots: dict[str, str] = field(default_factory=dict)
    negate: bool = False

    def describe(self) -> str:
        details = ", ".join(f"{k}={v}" for k, v in self.slots.items())
        if self.id and details:
            args = f"{self.id}; {details}"
        elif self.id:
            args = self.id
        else:
            args = details
        text = f"{self.template}({args})"
        return f"НЕ {text}" if self.negate else text


def cond(template: str, ident: str | None = None, negate: bool = False,
         **slots: str) -> Condition:
    """Короткая запись условия правила."""
    return Condition(template, ident, slots, negate)


@dataclass(frozen=True)
class Action:
    """Действие правила над рабочей памятью."""

    op: str
    template: str
    id: str
    slots: dict[str, str] = field(default_factory=dict)


def add_fact(template: str, ident: str, **slots: str) -> Action:
    return Action("add", template, ident, slots)


def change_fact(template: str, ident: str, **slots: str) -> Action:
    return Action("modify", template, ident, slots)


def drop_fact(template: str, ident: str) -> Action:
    return Action("delete", template, ident)


@dataclass
class Rule:
    """Продукция "ЕСЛИ ... ТО ..." с номером и пояснением."""

    number: str
    name: str
    conditions: list[Condition]
    actions: list[Action]

    def is_applicable(self, wm: WorkingMemory) -> bool:
        for condition in self.conditions:
            found = bool(wm.match(condition.template, condition.id, condition.slots))
            if found == condition.negate:
                return False
        return True

    def signature(self, wm: WorkingMemory) -> str:
        """Отпечаток условий: на тех же фактах правило повторно не срабатывает."""
        parts = []
        for condition in self.conditions:
            found = wm.match(condition.template, condition.id, condition.slots)
            state = ";".join(f"{f.id}:{sorted(f.slots.items())}"
                             for f in sorted(found, key=lambda f: f.id))
            parts.append(f"{condition.template}|{state}")
        return "#".join(parts)

    def describe(self, wm: WorkingMemory) -> list[str]:
        lines = []
        for condition in self.conditions:
            found = bool(wm.match(condition.template, condition.id, condition.slots))
            lines.append(("  " if found != condition.negate else "! ")
                         + condition.describe())
        return lines


# ---------------------------------------------------------------------------
# База знаний
# ---------------------------------------------------------------------------


def build_rules() -> list[Rule]:
    """База правил: порядок в списке задаёт стратегию разрешения конфликтов."""
    return [
        Rule(
            number="П1",
            name="Проверка питания при отсутствии запуска",
            conditions=[
                cond("симптом", "не_включается"),
                cond("обследование", "блок_питания", результат="не_проверено"),
            ],
            actions=[
                change_fact("обследование", "блок_питания", результат="в_процессе"),
                add_fact("рекомендация", "измерить_напряжения_бп", приоритет="высокий"),
            ],
        ),
        Rule(
            number="П2",
            name="Подтверждение неисправности блока питания",
            conditions=[
                cond("симптом", "не_включается"),
                cond("обследование", "блок_питания", результат="неисправно"),
                cond("гипотеза", "блок_питания", статус="возможна"),
            ],
            actions=[
                change_fact("гипотеза", "блок_питания", статус="подтверждена"),
                add_fact("рекомендация", "заменить_блок_питания", приоритет="высокий"),
                drop_fact("рекомендация", "измерить_напряжения_бп"),
            ],
        ),
        Rule(
            number="П3",
            name="Снятие гипотезы о блоке питания",
            conditions=[
                cond("обследование", "блок_питания", результат="исправно"),
                cond("гипотеза", "блок_питания", статус="возможна"),
            ],
            actions=[
                change_fact("гипотеза", "блок_питания", статус="опровергнута"),
                drop_fact("рекомендация", "измерить_напряжения_бп"),
            ],
        ),
        Rule(
            number="П4",
            name="Перегрев по внешним признакам",
            conditions=[
                cond("симптом", "шум_вентилятора"),
                cond("симптом", "перегрев_корпуса"),
                cond("гипотеза", "перегрев", статус="возможна"),
            ],
            actions=[
                change_fact("гипотеза", "перегрев", статус="вероятна"),
                add_fact("рекомендация", "очистить_охлаждение", приоритет="высокий"),
            ],
        ),
        Rule(
            number="П5",
            name="Подтверждение перегрева по температуре процессора",
            conditions=[
                cond("обследование", "температура_процессора", результат="выше_нормы"),
                cond("гипотеза", "перегрев", статус="вероятна"),
            ],
            actions=[
                change_fact("гипотеза", "перегрев", статус="подтверждена"),
                change_fact("рекомендация", "заменить_термопасту", приоритет="высокий"),
                add_fact("рекомендация", "проверить_радиатор", приоритет="средний"),
            ],
        ),
        Rule(
            number="П6",
            name="Снятие гипотезы о перегреве",
            conditions=[
                cond("обследование", "температура_процессора", результат="в_норме"),
                cond("гипотеза", "перегрев", статус="вероятна"),
            ],
            actions=[
                change_fact("гипотеза", "перегрев", статус="опровергнута"),
                drop_fact("рекомендация", "заменить_термопасту"),
            ],
        ),
        Rule(
            number="П7",
            name="Назначение теста памяти при синих экранах",
            conditions=[
                cond("симптом", "синий_экран"),
                cond("обследование", "оперативная_память", результат="не_проверено"),
            ],
            actions=[
                change_fact("обследование", "оперативная_память",
                            результат="тестируется"),
                add_fact("рекомендация", "запустить_тест_памяти", приоритет="высокий"),
            ],
        ),
        Rule(
            number="П8",
            name="Подтверждение неисправности памяти",
            conditions=[
                cond("обследование", "оперативная_память", результат="неисправно"),
                cond("гипотеза", "память", статус="возможна"),
            ],
            actions=[
                change_fact("гипотеза", "память", статус="подтверждена"),
                add_fact("рекомендация", "заменить_планку", приоритет="высокий"),
                drop_fact("рекомендация", "запустить_тест_памяти"),
            ],
        ),
        Rule(
            number="П9",
            name="Снятие гипотезы о неисправности памяти",
            conditions=[
                cond("обследование", "оперативная_память", результат="исправно"),
                cond("гипотеза", "память", статус="возможна"),
            ],
            actions=[
                change_fact("гипотеза", "память", статус="опровергнута"),
                add_fact("рекомендация", "обновить_драйверы", приоритет="средний"),
            ],
        ),
        Rule(
            number="П10",
            name="Совместный вывод по питанию и перегреву",
            conditions=[
                cond("гипотеза", "блок_питания", статус="подтверждена"),
                cond("гипотеза", "перегрев", статус="подтверждена"),
            ],
            actions=[
                add_fact("рекомендация", "проверить_мощность_бп", приоритет="средний"),
                add_fact("рекомендация", "проверить_вентиляторы", приоритет="низкий"),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Машина логического вывода
# ---------------------------------------------------------------------------


class InferenceEngine:
    """Машина прямого вывода: цикл «распознавание — действие»."""

    def __init__(self, rules: list[Rule], facts: list[Fact],
                 log: io.TextIOBase | None = None) -> None:
        self.wm = WorkingMemory(facts)
        self.rules = rules
        self.log = log or sys.stdout
        self.step = 0
        self.fired: set[tuple[str, str]] = set()
        self.stats = {"fired": 0, "add": 0, "modify": 0, "delete": 0}

    def _write(self, text: str = "") -> None:
        print(text, file=self.log)

    def dump_memory(self, title: str) -> None:
        self._write(title)
        for template in TEMPLATES:
            self._write(f"  {template}:")
            for fact in self.wm.all(template):
                self._write(f"    - {fact}")

    def step_once(self) -> Rule | None:
        """Один шаг цикла: первое применимое правило, ещё не срабатывавшее."""
        for rule in self.rules:
            if not rule.is_applicable(self.wm):
                continue
            signature = (rule.number, rule.signature(self.wm))
            if signature in self.fired:
                continue
            self.fired.add(signature)
            self.step += 1
            self.stats["fired"] += 1
            self._write(f"ШАГ {self.step}. Сработало правило "
                        f"{rule.number} «{rule.name}»")
            self._write("  Условия:")
            for line in rule.describe(self.wm):
                self._write("    " + line)
            self._write("  Действия:")
            for action in rule.actions:
                self._apply(action)
            self._write()
            return rule
        return None

    def _apply(self, action: Action) -> None:
        if action.op == "add":
            ok, message = self.wm.add(Fact(action.template, action.id,
                                           dict(action.slots)))
        elif action.op == "modify":
            ok, message = self.wm.modify(action.template, action.id,
                                         dict(action.slots))
        elif action.op == "delete":
            ok, message = self.wm.delete(action.template, action.id)
        else:
            raise ValueError(f"неизвестная операция: {action.op}")
        self.stats[action.op] += int(ok)
        self._write(f"    {'+' if ok else '-'} {message}")

    def run(self) -> None:
        while self.step_once() is not None:
            pass

    def assert_fact(self, fact: Fact) -> None:
        """Ввод нового результата обследования (например, от мастера)."""
        if self.wm.get(fact.template, fact.id) is None:
            ok, message = self.wm.add(fact)
        else:
            ok, message = self.wm.modify(fact.template, fact.id, fact.slots)
        self._write(f"Ввод данных: {'+' if ok else '-'} {message}")
        self._write()


# ---------------------------------------------------------------------------
# Сценарии работы
# ---------------------------------------------------------------------------


def scenario_combined() -> list[Fact]:
    """ПК не включается, вентилятор шумит, корпус горячий, были синие экраны."""
    return [
        Fact("симптом", "не_включается",
             {"описание": "при нажатии кнопки питания нет реакции"}),
        Fact("симптом", "шум_вентилятора",
             {"описание": "вентилятор работает на максимальных оборотах"}),
        Fact("симптом", "перегрев_корпуса", {"описание": "корпус ощутимо горячий"}),
        Fact("симптом", "синий_экран",
             {"описание": "перед отказом появлялся синий экран"}),
        Fact("обследование", "блок_питания", {"результат": "неисправно"}),
        Fact("обследование", "температура_процессора", {"результат": "выше_нормы"}),
        Fact("обследование", "оперативная_память", {"результат": "исправно"}),
        Fact("гипотеза", "блок_питания", {"статус": "возможна"}),
        Fact("гипотеза", "перегрев", {"статус": "возможна"}),
        Fact("гипотеза", "память", {"статус": "возможна"}),
        Fact("рекомендация", "измерить_напряжения_бп", {"приоритет": "высокий"}),
        Fact("рекомендация", "заменить_термопасту", {"приоритет": "низкий"}),
        Fact("рекомендация", "проверить_кабели_питания", {"приоритет": "средний"}),
    ]


def scenario_primary() -> list[Fact]:
    """Первичный приём: ПК не запускается, обследования ещё не выполнены."""
    return [
        Fact("симптом", "не_включается",
             {"описание": "при нажатии кнопки питания нет реакции"}),
        Fact("обследование", "блок_питания", {"результат": "не_проверено"}),
        Fact("обследование", "температура_процессора", {"результат": "в_норме"}),
        Fact("обследование", "оперативная_память", {"результат": "не_проверено"}),
        Fact("гипотеза", "блок_питания", {"статус": "возможна"}),
        Fact("гипотеза", "перегрев", {"статус": "возможна"}),
        Fact("гипотеза", "память", {"статус": "возможна"}),
        Fact("рекомендация", "заменить_термопасту", {"приоритет": "низкий"}),
    ]


PRIORITY_ORDER = {"высокий": 0, "средний": 1, "низкий": 2}


def print_summary(engine: InferenceEngine) -> None:
    engine._write("РЕЗУЛЬТАТ ДИАГНОСТИКИ")
    engine._write("  Гипотезы:")
    for fact in engine.wm.all("гипотеза"):
        engine._write(f"    - {fact.id}: {fact.slots['статус']}")
    engine._write("  Рекомендации:")
    recs = sorted(engine.wm.all("рекомендация"),
                  key=lambda f: PRIORITY_ORDER[f.slots["приоритет"]])
    for fact in recs:
        engine._write(f"    - {fact.id} (приоритет: {fact.slots['приоритет']})")
    engine._write()
    engine._write(
        "ИТОГО: срабатываний правил — {fired}, добавлено фактов — {add}, "
        "изменено — {modify}, удалено — {delete}".format(**engine.stats)
    )
    engine._write()


class Tee:
    """Вывод одновременно в консоль и в файл протокола."""

    def __init__(self, *streams: io.TextIOBase) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def main() -> None:
    log_path = Path(__file__).with_name("Трассировка.txt")
    with io.open(log_path, "w", encoding="utf-8") as log:
        out = Tee(sys.stdout, log)
        rules = build_rules()

        out.write("=" * 78 + "\n")
        out.write("ЭКСПЕРТНАЯ СИСТЕМА ДИАГНОСТИКИ НЕИСПРАВНОСТЕЙ ПК\n")
        out.write("=" * 78 + "\n\n")
        out.write(f"Шаблонов фактов: {len(TEMPLATES)}, правил в базе: {len(rules)}\n\n")

        out.write("СЦЕНАРИЙ 1. ПК не включается, вентилятор шумит, корпус горячий, "
                  "были синие экраны\n")
        out.write("-" * 78 + "\n")
        engine = InferenceEngine(rules, scenario_combined(), log=out)
        engine.dump_memory("Рабочая память до запуска машины вывода:")
        out.write("\n")
        engine.run()
        print_summary(engine)

        out.write("СЦЕНАРИЙ 2. Первичный приём: ПК не запускается, "
                  "обследования не выполнены\n")
        out.write("-" * 78 + "\n")
        engine2 = InferenceEngine(rules, scenario_primary(), log=out)
        engine2.dump_memory("Рабочая память до запуска машины вывода:")
        out.write("\n")
        engine2.run()
        engine2.assert_fact(Fact("обследование", "блок_питания",
                                 {"результат": "неисправно"}))
        engine2.run()
        print_summary(engine2)


if __name__ == "__main__":
    main()
