"""Self-check for the demo WAF regexes: real payloads block, benign searches pass.

Run: python demo/web_shop/test_waf.py  (no framework; asserts only).
"""

from app import _SQLI, _XSS

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


def _blocked(q: str) -> bool:
    return bool(_SQLI.search(q) or _XSS.search(q))


def main() -> None:
    for q in BLOCK:
        assert _blocked(q), f"should block: {q!r}"
    for q in PASS:
        assert not _blocked(q), f"should NOT block: {q!r}"
    print(f"ok: {len(BLOCK)} blocked, {len(PASS)} passed")


if __name__ == "__main__":
    main()
