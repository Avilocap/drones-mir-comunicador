from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def temporary_pem_pair(p12_path: Path, password: str) -> Iterator[tuple[Path, Path]]:
    """Extract a P12 into temporary cert/key PEM files and remove them afterwards."""

    with tempfile.TemporaryDirectory(prefix="drones-cert-") as temp_dir:
        temp_path = Path(temp_dir)
        os.chmod(temp_path, 0o700)
        cert_path = temp_path / "client-cert.pem"
        key_path = temp_path / "client-key.pem"
        passin = f"pass:{password}"

        _run_openssl(
            "pkcs12",
            "-in",
            str(p12_path),
            "-clcerts",
            "-nokeys",
            "-out",
            str(cert_path),
            "-passin",
            passin,
        )
        _run_openssl(
            "pkcs12",
            "-in",
            str(p12_path),
            "-nocerts",
            "-nodes",
            "-out",
            str(key_path),
            "-passin",
            passin,
        )
        os.chmod(cert_path, 0o600)
        os.chmod(key_path, 0o600)

        yield cert_path, key_path


def _run_openssl(*args: str) -> None:
    result = subprocess.run(
        ["openssl", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("OpenSSL no pudo leer el certificado P12")

