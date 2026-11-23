import random

import pytest

from santa.draw import DrawError, cycle_count, draw, mutual_count


def check(result, ids, forbidden=()):
    assert sorted(result) == sorted(ids), "каждый дарит"
    assert sorted(result.values()) == sorted(ids), "каждый получает ровно один подарок"
    for giver, recipient in result.items():
        assert giver != recipient
        assert (giver, recipient) not in forbidden


@pytest.mark.parametrize("n", [3, 4, 5, 8, 13, 40, 120])
def test_single_chain_without_exclusions(n):
    ids = list(range(1, n + 1))
    for seed in range(20):
        result = draw(ids, rng=random.Random(seed))
        check(result, ids)
        assert cycle_count(result) == 1
        assert mutual_count(result) == 0


def test_couples_never_draw_each_other():
    ids = list(range(1, 11))
    couples = [(1, 2), (3, 4), (5, 6), (7, 8)]
    forbidden = {p for a, b in couples for p in ((a, b), (b, a))}
    for seed in range(200):
        result = draw(ids, forbidden, rng=random.Random(seed))
        check(result, ids, forbidden)
        assert cycle_count(result) == 1


def test_big_family_group():
    ids = list(range(1, 9))
    family = [1, 2, 3, 4]
    forbidden = {(a, b) for a in family for b in family if a != b}
    for seed in range(100):
        result = draw(ids, forbidden, rng=random.Random(seed))
        check(result, ids, forbidden)
        assert cycle_count(result) == 1


def test_falls_back_when_one_chain_is_impossible():
    # 1 может дарить только 2, 2 только 1 → одна цепочка невозможна,
    # но 3,4,5 спокойно образуют свой круг.
    ids = [1, 2, 3, 4, 5]
    forbidden = {(1, x) for x in (3, 4, 5)} | {(2, x) for x in (3, 4, 5)}
    forbidden |= {(x, 1) for x in (3, 4, 5)} | {(x, 2) for x in (3, 4, 5)}
    result = draw(ids, forbidden, rng=random.Random(1))
    check(result, ids, forbidden)
    assert result[1] == 2 and result[2] == 1
    assert cycle_count(result) == 2


def test_errors():
    with pytest.raises(DrawError) as err:
        draw([1, 2])
    assert err.value.code == "few"

    with pytest.raises(DrawError) as err:
        draw([1, 2, 3], {(1, 2), (1, 3)})
    assert err.value.code == "stuck" and err.value.pid == 1

    # 1 и 2 могут дарить только 3 — двоим одного не поделить
    forbidden = {(1, 2), (2, 1), (1, 4), (2, 4)}
    with pytest.raises(DrawError) as err:
        draw([1, 2, 3, 4], forbidden)
    assert err.value.code == "impossible"


def test_distribution_is_not_trivially_biased():
    ids = [1, 2, 3, 4, 5]
    seen = {i: set() for i in ids}
    rng = random.Random(42)
    for _ in range(300):
        for g, r in draw(ids, rng=rng).items():
            seen[g].add(r)
    assert all(len(v) == 4 for v in seen.values())
