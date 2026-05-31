from __future__ import annotations

import argparse
import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol


PASSWORD_ENV = "DRONES_HEADLESS_P12_PASSWORD"
JAVA_CLASS_NAME = "drones.mir.HeadlessBatchSigner"


@dataclass(frozen=True)
class JarSpec:
    filename: str
    url: str
    expected_sha256: str

    def with_sha256(self, expected_sha256: str) -> "JarSpec":
        return replace(self, expected_sha256=expected_sha256)


@dataclass(frozen=True)
class HeadlessSignerConfig:
    p12_path: Path
    password: str
    insecure: bool = False
    alias: str | None = None
    java_executable: str = "java"
    javac_executable: str = "javac"
    timeout_seconds: int = 240


class BatchRequest(Protocol):
    batch_xml_b64: str
    pre_sign_url: str
    post_sign_url: str


AFIRMA_JARS = (
    JarSpec(
        filename="afirma-core-1.9.1.jar",
        url="https://repo1.maven.org/maven2/es/gob/afirma/afirma-core/1.9.1/"
        "afirma-core-1.9.1.jar",
        expected_sha256="1e2af31ff1962ccccfd35568b154262a8e632558695412e0e95e076c3eb4be2b",
    ),
    JarSpec(
        filename="afirma-crypto-batch-client-1.9.1.jar",
        url="https://repo1.maven.org/maven2/es/gob/afirma/afirma-crypto-batch-client/1.9.1/"
        "afirma-crypto-batch-client-1.9.1.jar",
        expected_sha256="e28c9a946d6d6e2165dea7e7e925d7f6f51961e047daacfc3d041cf667453083",
    ),
    JarSpec(
        filename="json-20240303.jar",
        url="https://repo1.maven.org/maven2/org/json/json/20240303/json-20240303.jar",
        expected_sha256="3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="drones-headless-signer",
        description="Prepara el puente Java de firma headless sin firmar ningun lote.",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=default_build_dir(),
        help="Directorio de cache para JARs oficiales y clases compiladas",
    )
    args = parser.parse_args()

    class_dir, jar_paths = ensure_headless_signer(args.build_dir)
    print(f"Java bridge: {class_dir}")
    print(f"JARs: {len(jar_paths)}")


def sign_batch_headless(
    request: BatchRequest,
    *,
    p12_path: Path,
    password: str,
    insecure: bool,
    alias: str | None = None,
    build_dir: Path | None = None,
    java_executable: str = "java",
    javac_executable: str = "javac",
    timeout_seconds: int = 240,
) -> str:
    config = HeadlessSignerConfig(
        p12_path=p12_path,
        password=password,
        insecure=insecure,
        alias=alias,
        java_executable=java_executable,
        javac_executable=javac_executable,
        timeout_seconds=timeout_seconds,
    )
    class_dir, jar_paths = ensure_headless_signer(
        default_build_dir() if build_dir is None else build_dir,
        javac_executable=javac_executable,
    )

    with tempfile.TemporaryDirectory(prefix="drones-headless-batch-") as temp_dir:
        temp_path = Path(temp_dir)
        os.chmod(temp_path, 0o700)
        batch_file = temp_path / "batch.b64"
        batch_file.write_text(request.batch_xml_b64, encoding="utf-8")
        os.chmod(batch_file, 0o600)

        command, secret_env = build_java_command(
            class_dir=class_dir,
            jar_paths=jar_paths,
            config=config,
            batch_file=batch_file,
            pre_sign_url=request.pre_sign_url,
            post_sign_url=request.post_sign_url,
        )
        env = os.environ.copy()
        env.update(secret_env)

        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )

    if result.returncode != 0:
        raise RuntimeError(
            "Firma headless fallida: "
            + scrub_process_output(result.stderr or result.stdout or "sin salida")
        )

    result_b64 = result.stdout.strip()
    validate_headless_batch_result(result_b64)
    return result_b64


def ensure_headless_signer(
    build_dir: Path | None = None,
    *,
    javac_executable: str = "javac",
) -> tuple[Path, list[Path]]:
    target_dir = default_build_dir() if build_dir is None else build_dir
    jar_paths = ensure_jars(target_dir / "lib")
    class_dir = compile_java_bridge(
        target_dir / "classes",
        jar_paths=jar_paths,
        javac_executable=javac_executable,
    )
    return class_dir, jar_paths


def ensure_jars(lib_dir: Path) -> list[Path]:
    lib_dir.mkdir(parents=True, exist_ok=True)
    jar_paths: list[Path] = []
    for spec in AFIRMA_JARS:
        jar_path = lib_dir / spec.filename
        if jar_path.exists():
            try:
                verify_jar_hash(jar_path, spec)
            except RuntimeError:
                jar_path.unlink()
        if not jar_path.exists():
            download_jar(spec, jar_path)
        verify_jar_hash(jar_path, spec)
        jar_paths.append(jar_path)
    return jar_paths


def compile_java_bridge(
    class_dir: Path,
    *,
    jar_paths: list[Path],
    javac_executable: str = "javac",
) -> Path:
    source_path = (
        project_root()
        / "java/headless-signer/src/main/java/drones/mir/HeadlessBatchSigner.java"
    )
    class_file = class_dir / "drones/mir/HeadlessBatchSigner.class"
    if class_file.exists() and class_file.stat().st_mtime >= source_path.stat().st_mtime:
        return class_dir

    class_dir.mkdir(parents=True, exist_ok=True)
    command = [
        javac_executable,
        "-encoding",
        "UTF-8",
        "-cp",
        classpath(jar_paths),
        "-d",
        str(class_dir),
        str(source_path),
    ]
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("No se pudo compilar el firmador headless: " + result.stderr.strip())
    return class_dir


def build_java_command(
    *,
    class_dir: Path,
    jar_paths: list[Path],
    config: HeadlessSignerConfig,
    batch_file: Path,
    pre_sign_url: str,
    post_sign_url: str,
) -> tuple[list[str], dict[str, str]]:
    command = [
        config.java_executable,
        "-cp",
        classpath([class_dir, *jar_paths]),
        JAVA_CLASS_NAME,
        "--p12",
        str(config.p12_path),
        "--batch-b64-file",
        str(batch_file),
        "--pre-sign-url",
        pre_sign_url,
        "--post-sign-url",
        post_sign_url,
    ]
    if config.alias:
        command.extend(["--alias", config.alias])
    if config.insecure:
        command.append("--insecure")
    return command, {PASSWORD_ENV: config.password}


def verify_jar_hash(
    path: Path,
    expected_sha256: str | JarSpec | None,
) -> str:
    actual = sha256_file(path)
    expected = (
        expected_sha256.expected_sha256
        if isinstance(expected_sha256, JarSpec)
        else expected_sha256
    )
    if expected and actual != expected:
        raise RuntimeError(f"Hash SHA-256 inesperado para {path.name}")
    return actual


def download_jar(spec: JarSpec, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    try:
        with urllib.request.urlopen(spec.url, timeout=60) as response:
            with temp_path.open("wb") as writable:
                shutil.copyfileobj(response, writable)
        verify_jar_hash(temp_path, spec)
        temp_path.replace(target)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def validate_headless_batch_result(result_b64: str) -> None:
    padding = "=" * (-len(result_b64) % 4)
    try:
        decoded = base64.b64decode(result_b64 + padding)
    except Exception as exc:
        raise RuntimeError("La firma headless no devolvio base64 valido") from exc
    if b"<signs" not in decoded or b"DONE_AND_SAVED" not in decoded:
        raise RuntimeError("La firma headless no devolvio un lote DONE_AND_SAVED")


def scrub_process_output(output: str, *, limit: int = 2000) -> str:
    compact = output.strip().replace("\r", "\n")
    return compact[-limit:] if len(compact) > limit else compact


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as readable:
        for chunk in iter(lambda: readable.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classpath(paths: list[Path]) -> str:
    return os.pathsep.join(str(path) for path in paths)


def default_build_dir() -> Path:
    return project_root() / ".java-build/headless-signer"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    main()
