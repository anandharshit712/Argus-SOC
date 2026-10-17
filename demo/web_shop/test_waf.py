"""Self-check for the demo shop: WAF regexes block real payloads, and pool-account matching is
exact (ATTACK_BOT_PASS_FAIL_DESIGN.md §6 -- only pool####@shop.example logs in on a pass).

Run: python demo/web_shop/test_waf.py  (no framework; asserts only).
"""

from app import _POOL_ACCOUNT, _SQLI, _XSS

BLOCK = [
    "1' OR '1'='1",
    "1' UNION SELECT NULL,NULL--",
    "1' UNION SELECT username,password FROM users--",
    "<script>alert(1)</script>",
    '"><svg onload=alert(1)>',
    "<img src=x onerror=alert(1)>",
]
PASS = [
    "shoes",
    "o'brien jacket",  # lone apostrophe is not an injection
    "order by price",  # everyday words, no SQL shape
    "select a gift card",
    "european union flags",
]

POOL_OK = ["pool0001@shop.example", "pool0500@shop.example", "pool9999@shop.example"]
POOL_BAD = [
    "demo@shop.example",  # the real account, not a pool one
    "pool1@shop.example",  # too few digits
    "pool00001@shop.example",  # too many digits
    "pool0001@mail.example",  # wrong domain
    "victim1@mail.example",  # a brute-force target, must never log in
]


def _blocked(q: str) -> bool:
    return bool(_SQLI.search(q) or _XSS.search(q))


def main() -> None:
    for q in BLOCK:
        assert _blocked(q), f"should block: {q!r}"
    for q in PASS:
        assert not _blocked(q), f"should NOT block: {q!r}"
    for u in POOL_OK:
        assert _POOL_ACCOUNT.match(u), f"should be a pool account: {u!r}"
    for u in POOL_BAD:
        assert not _POOL_ACCOUNT.match(u), f"should NOT be a pool account: {u!r}"
    print(
        f"ok: {len(BLOCK)} blocked, {len(PASS)} passed, "
        f"{len(POOL_OK)} pool-ok, {len(POOL_BAD)} pool-rejected"
    )


if __name__ == "__main__":
    main()
