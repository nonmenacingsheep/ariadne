import unittest

from ariadne2.adapters.redact import REDACTED, note, redact, redact_secrets


class RedactTests(unittest.TestCase):
    def caught(self, text, secret):
        out, n = redact_secrets(text)
        self.assertNotIn(secret, out, text)
        self.assertGreaterEqual(n, 1, text)
        self.assertIn(REDACTED, out)

    def test_vendor_token_shapes(self):
        for tok in ("sk-ant-api03-abcdefghijklmnopqrstuvwx", "sk-abcdefghijklmnopqrstuvwxyz012345",
                    "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789", "sk_live_abcdefghijklmnop1234",
                    "ghp_abcdefghijklmnopqrstuvwxyz", "github_pat_11ABCDEFG0abcdefghijkl_mnop",
                    "glpat-abcdefghijklmnopqrst", "xoxb-1234567890-abcdefghij", "AKIAABCDEFGHIJKLMNOP",
                    "AIzaSyA-abcdefghijklmnopqrstuvwxyz01234", "GOCSPX-abcdefghijklmnopqrstuv",
                    "npm_abcdefghijklmnopqrstuvwxyz0123456789"):
            self.caught(f"here: {tok} thanks", tok)

    def test_jwt_discord_token_and_bearer(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
        self.caught(f"cookie {jwt}", jwt)
        disc = "MTAyNDU2Nzg5MDEyMzQ1Njc4OQ.GabcDe.abcdefghijklmnopqrstuvwxyz1234567"
        self.caught(f"token {disc}", disc)
        self.caught("Authorization: Bearer abcdefghijklmnop1234567890", "abcdefghijklmnop1234567890")

    def test_pem_private_key(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----"
        out, n = redact_secrets("before\n" + pem + "\nafter")
        self.assertNotIn("MIIEow", out)
        self.assertIn("after", out)
        self.assertEqual(n, 1)

    def test_passwords_in_urls(self):
        out, n = redact_secrets("clone https://bob:hunter22@git.example.com/repo.git now")
        self.assertEqual(out, f"clone https://{REDACTED}@git.example.com/repo.git now")
        self.assertEqual(n, 1)
        self.assertEqual(redact("https://example.com/a@b"), "https://example.com/a@b")

    def test_named_secrets_in_pairs_json_and_query_strings(self):
        self.assertEqual(redact("password: hunter2222"), f"password: {REDACTED}")
        self.assertEqual(redact("PASSWORD=hunter2222"), f"PASSWORD={REDACTED}")
        self.assertEqual(redact('{"api_key": "abcd1234efgh"}'), f'{{"api_key": "{REDACTED}"}}')
        self.assertEqual(redact('{"refresh_token":"abcdefghijklmnop"}'), f'{{"refresh_token":"{REDACTED}"}}')
        self.assertEqual(redact("https://x.example/cb?token=abc123def456&page=2"),
                         f"https://x.example/cb?token={REDACTED}&page=2")
        self.assertEqual(redact("client_secret = 's3cr3tvalue99'"), f"client_secret = '{REDACTED}'")

    def test_ordinary_text_is_left_alone(self):
        for t in ("the password is something he forgot", "token count is 5", "I like sk-8 skis",
                  "key: short", "see https://example.com/page?id=12", "", "password:"):
            self.assertEqual(redact_secrets(t), (t, 0))
        self.assertEqual(redact_secrets(None), ("", 0))

    def test_counts_and_note(self):
        out, n = redact_secrets("ghp_abcdefghijklmnopqrstuvwxyz and password=hunter2222 and AKIAABCDEFGHIJKLMNOP")
        self.assertEqual(n, 3)
        self.assertEqual(note(3), "[3 credentials removed before you saw this]")
        self.assertEqual(note(1), "[1 credential removed before you saw this]")
        self.assertEqual(note(0), "")

    def test_already_redacted_text_is_not_counted_twice(self):
        once, n = redact_secrets("Authorization: Bearer abcdefghijklmnop1234567890")
        self.assertEqual(n, 1)
        self.assertEqual(redact_secrets(once), (once, 0))


if __name__ == "__main__":
    unittest.main()
