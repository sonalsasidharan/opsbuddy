"""Run: .venv\\Scripts\\python.exe test_masking.py"""
from masking import mask, mask_text

MUST_MASK = {
    "db url with creds": ("connecting to postgres://admin:Hunter2pw@db.internal:5432/pay", "Hunter2pw"),
    "aws access key": ("AWS key AKIAIOSFODNN7EXAMPLE used", "AKIAIOSFODNN7EXAMPLE"),
    "bare JWT": ("session eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abc123sig failed", "abc123sig"),
    "email": ("payment failed for user jane.doe@example.com", "jane.doe"),
    "card number": ("charge declined card 4111 1111 1111 1111", "4111"),
    "json secret": ('{"client_secret": "s3cr3tvalue", "ok": true}', "s3cr3tvalue"),
    "quoted password with spaces": ('password = "my pass phrase"', "pass phrase"),
    "single-quoted secret": ("api_key: 'abcDEF123xyz'", "abcDEF123xyz"),
    "private key": ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----", "MIIEow"),
    "plain key=value": ("password=SuperSecret123", "SuperSecret123"),
    "authorization bearer": ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    "basic auth": ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
    "github token": ("push with ghp_" + "a" * 36, "a" * 36),
    "sk token": ("key sk-ant-" + "x1" * 15, "x1x1x1"),
    "env style": ("DB_PASSWORD=hunter2 DB_HOST=db", "hunter2"),
    "long opaque token": ("session=7Hk2pQ9sLm4Xv8Rt1Zc6Bn3Wd5Fy0Gj2Aq", "7Hk2pQ9sLm4Xv8Rt1Zc6Bn3Wd5Fy0Gj2Aq"),
}
MUST_KEEP = [
    "INFO starting payment-service",
    "ERROR connection refused to postgres:5432",
    "Fatal: could not connect to database",
    "Back-off restarting failed container payment in pod payment-service-5c8b",
    "State: CrashLoopBackOff; restarts: 6; exit code: None; age: 9m",
    "Image: localhost:5001/payment-service:7fd1a60",
    "order 1234567890123456 total 19.99",  # digits that fail the Luhn check are kept
]

fails = 0
for name, (text, secret) in MUST_MASK.items():
    out = mask_text(text)
    ok = secret not in out and out != text
    fails += not ok
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {out!r}"))
for text in MUST_KEEP:
    out = mask_text(text)
    ok = out == text
    fails += not ok
    print(("PASS " if ok else "FAIL ") + f"keeps: {text[:50]}" + ("" if ok else f"  -> {out!r}"))
once = mask_text("password=abc Authorization: Bearer xyz.123.456 jane@example.com")
ok = mask_text(once) == once
fails += not ok
print(("PASS " if ok else "FAIL ") + "idempotent")
print("\nreport example:", mask("password=a token=b jane@example.com")[1])
print("\nFAILURES:", fails)
raise SystemExit(1 if fails else 0)
