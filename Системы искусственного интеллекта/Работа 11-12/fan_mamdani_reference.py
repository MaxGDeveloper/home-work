"""Эталонный расчёт нечёткого вывода Мамдани для модели «Вентилятор ПК».

Реализует тот же вывод, что настроен в FisPro: min-импликация,
max-аккумуляция, дефаззификация центром тяжести (метод area).

Запуск: py fan_mamdani_reference.py
"""

# Функции принадлежности: (тип, параметры)
# трапеция: a, b, c, d; треугольник: a, b, c
TEMP_MF = {
    "низкая": ("trap", 30, 30, 45, 55),
    "средняя": ("tri", 45, 60, 75),
    "высокая": ("trap", 65, 75, 90, 90),
}
LOAD_MF = {
    "низкая": ("trap", 0, 0, 25, 40),
    "средняя": ("tri", 25, 50, 75),
    "высокая": ("trap", 60, 75, 100, 100),
}
FAN_MF = {
    "низкие": ("trap", 0, 0, 25, 40),
    "средние": ("tri", 30, 50, 70),
    "высокие": ("trap", 60, 75, 100, 100),
}

TEMP_NAMES = ["низкая", "средняя", "высокая"]
LOAD_NAMES = ["низкая", "средняя", "высокая"]
FAN_NAMES = ["низкие", "средние", "высокие"]

# Правила: (индекс терма температуры, индекс терма нагрузки, индекс терма оборотов)
RULES = [
    (0, 0, 0),  # R1  Т низкая  И Н низкая  -> низкие
    (0, 1, 0),  # R2  Т низкая  И Н средняя -> низкие
    (0, 2, 1),  # R3  Т низкая  И Н высокая -> средние
    (1, 0, 0),  # R4  Т средняя И Н низкая  -> низкие
    (1, 1, 1),  # R5  Т средняя И Н средняя -> средние
    (1, 2, 2),  # R6  Т средняя И Н высокая -> высокие
    (2, 0, 1),  # R7  Т высокая И Н низкая  -> средние
    (2, 1, 2),  # R8  Т высокая И Н средняя -> высокие
    (2, 2, 2),  # R9  Т высокая И Н высокая -> высокие
]

TEMP_RANGE = (30.0, 90.0)
LOAD_RANGE = (0.0, 100.0)
FAN_RANGE = (0.0, 100.0)
STEP = 0.001


def mf_value(term, x):
    """Степень принадлежности точки x нечёткому терму term."""
    kind = term[0]
    if kind == "trap":
        _, a, b, c, d = term
        if x < a or x > d:
            return 0.0
        if b <= x <= c:
            return 1.0
        if x < b:
            return (x - a) / (b - a) if b > a else 1.0
        return (d - x) / (d - c) if d > c else 1.0
    _, a, b, c = term
    if x <= a or x >= c:
        return 0.0
    if x == b:
        return 1.0
    if x < b:
        return (x - a) / (b - a)
    return (c - x) / (c - b)


def degrees(values, mfs, names):
    return [(name, mf_value(mfs[name], v)) for name, v in zip(names, values)]


def infer(temp, load, verbose=False):
    """Нечёткий вывод для пары (температура, нагрузка).

    Возвращает (обороты, сведения о правилах).
    """
    mu_t = [mf_value(TEMP_MF[n], temp) for n in TEMP_NAMES]
    mu_l = [mf_value(LOAD_MF[n], load) for n in LOAD_NAMES]

    fired = []
    for i, (ti, li, fi) in enumerate(RULES, start=1):
        strength = min(mu_t[ti], mu_l[li])
        if strength > 0:
            fired.append((i, f"R{i}", strength, FAN_NAMES[fi]))

    if not fired:
        return -1.0, [], mu_t, mu_l

    # Аккумуляция: для каждой точки оси оборотов берём максимум из
    # подрезанных термов (min-импликация -> уровень среза равен степени правила)
    total, moment = 0.0, 0.0
    n_steps = int(round((FAN_RANGE[1] - FAN_RANGE[0]) / STEP))
    for k in range(n_steps + 1):
        x = FAN_RANGE[0] + k * STEP
        agg = 0.0
        for _, _, strength, term_name in fired:
            agg = max(agg, min(strength, mf_value(FAN_MF[term_name], x)))
        total += agg
        moment += agg * x
    fan = moment / total if total > 0 else -1.0
    return fan, fired, mu_t, mu_l


def fmt(x, digits=2):
    return f"{x:.{digits}f}".replace(".", ",")


TEST_POINTS = [
    (35, 15), (35, 50), (35, 85),
    (60, 15), (60, 50), (60, 85),
    (80, 15), (80, 50), (80, 85),
    (50, 50), (70, 45),
]


def main():
    print("Точка | mu(T) низ/сред/выс | mu(Н) низ/сред/выс | Правила | Обороты")
    print("-" * 110)
    rows = []
    for temp, load in TEST_POINTS:
        fan, fired, mu_t, mu_l = infer(temp, load)
        rules = " + ".join(
            f"R{i}({fmt(s)})" for i, _, s, _ in fired
        ) if fired else "нет"
        mu_ts = "/".join(f"{v:.2f}" for v in mu_t).replace(".", ",")
        mu_ls = "/".join(f"{v:.2f}" for v in mu_l).replace(".", ",")
        print(f"{temp:>4} {load:>4} | {mu_ts:>18} | {mu_ls:>18} | {rules:<28} | {fmt(fan)}")
        rows.append((temp, load, fmt(fan)))

    print()
    print("Проверка на фактических значениях, введённых в FisPro:")
    test = [
        (36.0, 15.0, 16.538),
        (60.6, 50.0, 50.0),
        (80.4, 86.0, 83.462),
        (50.4, 50.0, 31.395),
        (70.2, 45.0, 70.27),
    ]
    print("T | L | FisPro | эталон")
    for t, l, got in test:
        fan, fired, _, _ = infer(t, l)
        print(f"{t} | {l} | {got} | {fmt(fan)}")


if __name__ == "__main__":
    main()
