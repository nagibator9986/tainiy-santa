"""Распределение «Тайного Санты».

Цель — одна общая цепочка на всех (гамильтонов цикл): А → Б → В → … → А.
Так никто не дарит «в ответ» тому, кто дарит ему, и компания связана одним
кругом. Исключения (пары, семьи, соседи) — запрещённые рёбра графа.

Если одной цепочки не существует (слишком много исключений), берём любое
допустимое распределение — совершенное паросочетание — и из нескольких
случайных вариантов выбираем тот, где меньше всего взаимных пар.
"""
from __future__ import annotations

import random
from typing import Hashable, Iterable

Id = Hashable


class DrawError(ValueError):
    """Распределить нельзя. code: few | stuck | impossible."""

    def __init__(self, code: str, pid: Id | None = None):
        super().__init__(code)
        self.code = code
        self.pid = pid

    def human(self, names: dict) -> str:
        if self.code == "few":
            return "Для жеребьёвки нужно хотя бы три участника."
        if self.code == "stuck":
            name = names.get(self.pid, "?")
            return (f"Участнику «{name}» некому дарить: каждый из остальных попал "
                    "в исключения или носит ту же пометку пары/семьи.")
        return ("С такими исключениями и группами распределить подарки нельзя. "
                "Уберите одно-два исключения или разделите большую группу.")


def _allowed(ids: list, forbidden: set) -> dict:
    return {g: [r for r in ids if r != g and (g, r) not in forbidden] for g in ids}


def _single_chain(ids: list, allowed: dict, rng: random.Random, budget: int) -> dict | None:
    """Случайный поиск в глубину гамильтонова цикла.

    Следующего кандидата берём по правилу Варнсдорфа (сначала того, у кого
    меньше всего дальнейших вариантов), а среди равных — случайно. Если за
    budget шагов цикл не нашёлся, возвращаем None — вызывающий перезапустит.
    """
    n = len(ids)
    can_close = {g: set(opts) for g, opts in allowed.items()}
    start = rng.choice(ids)
    path, used = [start], {start}

    def onward(x):
        return sum(1 for y in allowed[x] if y not in used)

    def candidates(cur):
        opts = [x for x in allowed[cur] if x not in used]
        rng.shuffle(opts)
        opts.sort(key=onward)  # сортировка стабильная — порядок среди равных случайный
        return iter(opts)

    stack = [candidates(start)]
    steps = 0
    while stack:
        steps += 1
        if steps > budget:
            return None
        if len(path) == n:
            if start in can_close[path[-1]]:
                return {path[i]: path[(i + 1) % n] for i in range(n)}
            stack.pop()
            used.discard(path.pop())
            continue
        nxt = next(stack[-1], None)
        if nxt is None:
            stack.pop()
            used.discard(path.pop())
            continue
        path.append(nxt)
        used.add(nxt)
        stack.append(candidates(nxt))
    return None


def _matching(ids: list, allowed: dict, rng: random.Random) -> dict | None:
    """Алгоритм Куна со случайным порядком: любое допустимое распределение."""
    owner: dict = {}  # получатель -> даритель

    def place(giver, seen):
        opts = allowed[giver][:]
        rng.shuffle(opts)
        for r in opts:
            if r in seen:
                continue
            seen.add(r)
            if r not in owner or place(owner[r], seen):
                owner[r] = giver
                return True
        return False

    order = ids[:]
    rng.shuffle(order)
    for giver in order:
        if not place(giver, set()):
            return None
    return {g: r for r, g in owner.items()}


def cycle_count(assignment: dict) -> int:
    seen, cycles = set(), 0
    for start in assignment:
        if start in seen:
            continue
        cycles += 1
        cur = start
        while cur not in seen:
            seen.add(cur)
            cur = assignment[cur]
    return cycles


def mutual_count(assignment: dict) -> int:
    return sum(1 for g, r in assignment.items() if assignment.get(r) == g) // 2


def draw(ids: Iterable[Id], forbidden: Iterable[tuple] = (), rng: random.Random | None = None) -> dict:
    """Вернуть {даритель: получатель}. forbidden — направленные пары (кто, кому нельзя)."""
    ids = list(dict.fromkeys(ids))
    if len(ids) < 3:
        raise DrawError("few")
    rng = rng or random.SystemRandom()
    forbidden = set(forbidden)
    allowed = _allowed(ids, forbidden)

    for giver, opts in allowed.items():
        if not opts:
            raise DrawError("stuck", giver)
    receivers = {r for opts in allowed.values() for r in opts}
    for pid in ids:
        if pid not in receivers:
            raise DrawError("stuck", pid)

    budget = max(5_000, 400 * len(ids))
    for _ in range(40):
        chain = _single_chain(ids, allowed, rng, budget)
        if chain:
            return chain

    best, best_score = None, None
    for _ in range(80):
        found = _matching(ids, allowed, rng)
        if found is None:
            raise DrawError("impossible")
        score = (mutual_count(found), cycle_count(found))
        if best_score is None or score < best_score:
            best, best_score = found, score
            if score[0] == 0:
                break
    return best
