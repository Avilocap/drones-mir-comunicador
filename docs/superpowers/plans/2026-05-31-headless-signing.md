# Headless Signing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an experimental headless signing path that can replace native AutoFirma for the MIR FIRe batch, without presenting a real communication unless `--sign` is explicitly used.

**Architecture:** Keep the Python HTTP/JSF flow as-is and add a small Java bridge around the official Cliente @firma `BatchSigner`. Python downloads pinned JARs, compiles the bridge with `javac`, writes the sensitive batch XML to a temporary file, passes the P12 password via environment, and receives the base64 `<signs>` result on stdout.

**Tech Stack:** Python stdlib + existing `httpx`; Java `javac/java`; official Maven Central JARs `afirma-core`, `afirma-crypto-batch-client`, and `org.json`.

---

### Task 1: Test the Headless Wrapper Boundaries

**Files:**
- Create: `tests/test_headless_signer.py`
- Create later: `src/drones_mir_comunicador/headless_signer.py`

- [ ] **Step 1: Write failing tests**

```python
import base64
import os
import tempfile
import unittest
from pathlib import Path

from drones_mir_comunicador.headless_signer import (
    HeadlessSignerConfig,
    JarSpec,
    build_java_command,
    verify_jar_hash,
)


class HeadlessSignerTests(unittest.TestCase):
    def test_build_java_command_keeps_password_and_batch_out_of_arguments(self):
        config = HeadlessSignerConfig(
            p12_path=Path("/tmp/cert.p12"),
            password="secret-password",
            insecure=True,
            alias="my-alias",
        )
        command, env = build_java_command(
            class_dir=Path("/tmp/classes"),
            jar_paths=[Path("/tmp/a.jar"), Path("/tmp/b.jar")],
            config=config,
            batch_file=Path("/tmp/batch.txt"),
            pre_sign_url="https://example.test/presign",
            post_sign_url="https://example.test/postsign",
        )

        joined = " ".join(command)
        self.assertIn("drones.mir.HeadlessBatchSigner", command)
        self.assertIn("--batch-b64-file", command)
        self.assertIn("--insecure", command)
        self.assertIn("--alias", command)
        self.assertNotIn("secret-password", joined)
        self.assertEqual(env["DRONES_HEADLESS_P12_PASSWORD"], "secret-password")

    def test_verify_jar_hash_accepts_matching_sha256(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jar_path = Path(temp_dir) / "sample.jar"
            jar_path.write_bytes(b"official bytes")
            spec = JarSpec("sample.jar", "https://example.test/sample.jar", expected_sha256="")
            expected = verify_jar_hash(jar_path, expected_sha256=None)
            self.assertEqual(len(expected), 64)
            self.assertEqual(verify_jar_hash(jar_path, expected_sha256=expected), expected)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `rtk proxy uv run python -m unittest tests.test_headless_signer -v`

Expected: FAIL because `drones_mir_comunicador.headless_signer` does not exist.

### Task 2: Add Java Bridge and Python Wrapper

**Files:**
- Create: `java/headless-signer/src/main/java/drones/mir/HeadlessBatchSigner.java`
- Create: `src/drones_mir_comunicador/headless_signer.py`
- Modify: `.gitignore`

- [ ] **Step 1: Implement `HeadlessBatchSigner.java`**

The Java class must:
- load PKCS12 from `--p12`;
- read password only from `DRONES_HEADLESS_P12_PASSWORD`;
- read batch base64 from `--batch-b64-file`;
- call `BatchSigner.signXML(decodedBatch, preSignUrl, postSignUrl, certChain, privateKey)`;
- print only base64 result XML to stdout;
- support `--insecure` by setting Java property `disableSslChecks=true`.

- [ ] **Step 2: Implement `headless_signer.py`**

The Python module must:
- pin JAR URLs and SHA-256 hashes;
- download missing JARs into `.java-build/headless-signer/lib`;
- compile Java into `.java-build/headless-signer/classes`;
- build commands without password or batch in process arguments;
- validate the returned batch result with existing `validate_batch_result`.

- [ ] **Step 3: Run tests and confirm GREEN**

Run: `rtk proxy uv run python -m unittest tests.test_headless_signer -v`

Expected: PASS.

### Task 3: Wire Communication CLI

**Files:**
- Modify: `src/drones_mir_comunicador/communication_cli.py`
- Modify: `README.md`
- Modify: `lessons.md`

- [ ] **Step 1: Add CLI option**

Add `--sign-mode {autofirma,headless}` defaulting to `autofirma`. It is only meaningful with `--sign`; without `--sign`, the command must remain validation-only unless `--start-signature` is explicitly used.

- [ ] **Step 2: Branch the signing path**

After parsing `mini_applet.html`, call:

```python
sign_batch_headless(
    request,
    p12_path=p12_path,
    password=password,
    insecure=args.insecure,
)
```

only when `--sign --sign-mode headless` is used. Reuse the existing `miniappletSuccessService`, `/firmaOk`, registration AJAX, and `/resultado` code.

- [ ] **Step 3: Verify compile and CLI help**

Run:

```bash
rtk proxy uv run python -m compileall src/drones_mir_comunicador
rtk proxy uv run drones-communication --help
```

Expected: compile succeeds and help shows `--sign-mode`.

### Task 4: Final Verification

**Files:**
- All touched files

- [ ] **Step 1: Build Java bridge without live signing**

Run a Python import/build command that calls the wrapper build path only. Expected: JARs verify and Java compiles.

- [ ] **Step 2: Do not run live headless signing**

Because `--sign --sign-mode headless` can present a real communication, do not run it until the user explicitly authorizes a real filing in the current turn.
