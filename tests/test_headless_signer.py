from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from drones_mir_comunicador.headless_signer import (
    HeadlessSignerConfig,
    JarSpec,
    build_java_command,
    verify_jar_hash,
)
from drones_mir_comunicador.communication_cli import (
    CommunicationDraft,
    apply_draft,
    option_value_by_label,
)


class HeadlessSignerTests(unittest.TestCase):
    def test_build_java_command_keeps_password_and_batch_out_of_arguments(self) -> None:
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
        self.assertNotIn("DRONES_HEADLESS_P12_PASSWORD=secret-password", joined)
        self.assertEqual(env["DRONES_HEADLESS_P12_PASSWORD"], "secret-password")

    def test_verify_jar_hash_accepts_matching_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            jar_path = Path(temp_dir) / "sample.jar"
            jar_path.write_bytes(b"official bytes")
            spec = JarSpec(
                filename="sample.jar",
                url="https://example.test/sample.jar",
                expected_sha256="",
            )

            expected = verify_jar_hash(jar_path, expected_sha256=None)

            self.assertEqual(len(expected), 64)
            self.assertEqual(verify_jar_hash(jar_path, spec.with_sha256(expected)), expected)

    def test_apply_draft_fills_empty_notification_address_from_operator(self) -> None:
        data = {
            "formCampos:pestanas:viaNotif": "",
            "formCampos:pestanas:provinciaNotif_input": "",
            "formCampos:pestanas:localidadNotif_input": "",
            "formCampos:pestanas:codPostalNotif": "",
            "formCampos:pestanas:viaoper": "Fake Street 1",
            "formCampos:pestanas:provinciaoper_input": "province-value",
            "formCampos:pestanas:localidadoper_input": "city-value",
            "formCampos:pestanas:codPostaloper": "41010",
        }
        draft = CommunicationDraft(
            date="11/06/2026",
            place="Charco de la Pava",
            height_m=120,
            ccaa_code="-860430510",
            polygon={"type": "FeatureCollection", "features": []},
        )

        result = apply_draft(data, draft)

        self.assertEqual(result["formCampos:pestanas:viaNotif"], "Fake Street 1")
        self.assertEqual(result["formCampos:pestanas:provinciaNotif_input"], "1878877445")
        self.assertEqual(result["formCampos:pestanas:localidadNotif_input"], "")
        self.assertEqual(result["formCampos:pestanas:codPostalNotif"], "41010")

    def test_option_value_by_label_reads_select_option(self) -> None:
        html = """
        <select name="formCampos:pestanas:localidadNotif_input">
          <option value="">--Seleccionar--</option>
          <option value="123">Camas</option>
          <option value="456">Sevilla</option>
        </select>
        """

        self.assertEqual(
            option_value_by_label(html, "formCampos:pestanas:localidadNotif_input", "Sevilla"),
            "456",
        )


if __name__ == "__main__":
    unittest.main()
