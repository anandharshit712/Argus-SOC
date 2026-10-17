"""Self-check for the outcome bag (ATTACK_BOT_PASS_FAIL_DESIGN.md §14, checks 1 and 2).

Run: python demo/attack_bot/test_bag.py  (no framework; asserts only).
"""

from outcome_bag import OutcomeBag


def test_exact_ratio_per_bag() -> None:
    """Every block of 10 draws from a fresh bag has exactly 3 passes (check 1)."""
    bag = OutcomeBag(size=10, ratio=0.3)
    for _ in range(50):  # 50 bags = 500 draws
        block = [bag.draw() for _ in range(10)]
        assert block.count("pass") == 3, f"expected 3 passes per 10, got {block}"


def test_exact_ratio_per_100() -> None:
    """Size 100 gives exactly 30 passes per 100 (the §4 variant)."""
    bag = OutcomeBag(size=100, ratio=0.3)
    block = [bag.draw() for _ in range(100)]
    assert block.count("pass") == 30, f"expected 30/100, got {block.count('pass')}"


def test_random_order() -> None:
    """Two bags of the same size give a different pass order (check 2) -- not a fixed pattern."""
    a = [OutcomeBag(size=10, ratio=0.3).draw() for _ in range(10)]
    # Overwhelmingly likely to differ; retry a couple of times so a rare tie is not a flake.
    assert any([OutcomeBag(size=10, ratio=0.3).draw() for _ in range(10)] != a for _ in range(5)), (
        "two fresh bags produced the same order five times running"
    )


def main() -> None:
    test_exact_ratio_per_bag()
    test_exact_ratio_per_100()
    test_random_order()
    print("ok: bag gives exactly 3/10 and 30/100, random order")


if __name__ == "__main__":
    main()
