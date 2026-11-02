"""Host-only checks for metadata collection; no phone or hardware is tested."""

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "collect_cityman.py"
SPEC = importlib.util.spec_from_file_location("collect_cityman", SCRIPT)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

NODE = "/sys/firmware/devicetree/base/soc/cci@fda0c000/camera@2"
VALID_NODE = (
    "PROPERTY compatible\n71 63 6f 6d 2c 63 61 6d 65 72 61 00\nEND 0\n"
    "PROPERTY qcom,cci-master\n00 00 00 01\nEND 0\n"
)


def record(stdout="", *, status="ok", exit_code=0, stderr="", **extra):
    return dict(status=status, exit_code=exit_code, stdout=stdout,
                stderr=stderr, truncated=False, **extra)


class FakeAdb:
    """Finite, explicit responses make unexpected device requests fail tests."""

    def __init__(self):
        values = {
            "ro.product.device": "cityman",
            "ro.product.board": "msm8994",
            "ro.board.platform": "msm8994",
            "ro.build.version.release": "16",
            "ro.build.version.sdk": "36",
            "ro.lineage.version": "23.2-fixture",
            "ro.build.fingerprint": "fixture/cityman/test",
        }
        self.responses = {
            ("run", "get-state"): record("device\n"),
            ("shell", "uname -r"): record("3.10-fixture\n"),
            ("shell", collector.DEVICE_NAMES): record("/sys/class/video4linux/video0: fixture\n"),
            ("shell", collector.FIND_TREE): record(NODE + "\n"),
            ("shell", collector.read_node_command(NODE)): record(VALID_NODE),
            ("shell", collector.PLATFORM_DEVICES): record(
                "DEVICE /sys/bus/platform/devices/soc:qcom,camera@0\n"
                "OF_NAME=qcom,camera\nOF_FULLNAME=/soc/cci@fda0c000/qcom,camera@0\nEND 0\n"),
        }
        self.responses.update({("shell", "getprop " + key): record(value + "\n")
                               for key, value in values.items()})
        self.calls = []

    def _respond(self, call):
        self.calls.append(call)
        if call not in self.responses:
            raise AssertionError("Unexpected ADB request: " + repr(call))
        return copy.deepcopy(self.responses[call])

    def run(self, *args):
        return self._respond(("run",) + args)

    def shell(self, command):
        return self._respond(("shell", command))


class CollectionTests(unittest.TestCase):
    def test_legacy_kernel_fallback_preserves_original_failure_and_registered_nodes(self):
        adb = FakeAdb()
        adb.responses[("shell", collector.FIND_TREE)] = record(
            status="error", exit_code=66, stderr="No readable live device-tree directory\n")
        report, code = collector.collect(adb)
        self.assertEqual((code, report["status"]), (1, "incomplete"))
        self.assertEqual(report["device_tree"]["discovery"]["exit_code"], 66)
        self.assertEqual(report["device_tree"]["nodes"], {})
        self.assertEqual(report["platform_devices"]["status"], "ok")
        self.assertIn("OF_FULLNAME=", report["platform_devices"]["stdout"])
        self.assertIn("not full DT properties", report["device_tree"]["fallback_scope"])
        self.assertIn("registered-node metadata only", report["limitations"][0])

    def test_platform_fallback_permission_denial_remains_an_error(self):
        adb = FakeAdb()
        adb.responses[("shell", collector.FIND_TREE)] = record(status="error", exit_code=66)
        adb.responses[("shell", collector.PLATFORM_DEVICES)] = record(
            status="error", exit_code=1, stderr="permission denied")
        report, code = collector.collect(adb)
        self.assertEqual((code, report["status"]), (1, "incomplete"))
        self.assertEqual(report["platform_devices"]["status"], "error")

    def test_full_collection_preserves_evidence_without_claiming_hardware_works(self):
        adb = FakeAdb()
        report, code = collector.collect(adb)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "collected")
        self.assertIn("not a sensor or biometric test", report["purpose"])
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["device_tree"]["camera_nodes_visible"])
        props = report["device_tree"]["nodes"][NODE]["properties"]
        self.assertEqual(props["compatible"]["strings"], ["qcom,camera"])
        self.assertEqual(props["qcom,cci-master"]["cells_be32"], [1])
        self.assertEqual(report["kernel"]["stdout"], "3.10-fixture\n")
        self.assertFalse({"sensor_verified", "iris_working", "biometric_pass"} & report.keys())
        self.assertEqual(adb.calls[-1], ("shell", collector.read_node_command(NODE)))

    def test_wrong_device_or_android_sdk_stops_before_hardware_metadata_reads(self):
        for key, value in (("ro.product.device", "talkman"),
                           ("ro.product.device", ""),
                           ("ro.build.version.sdk", "35")):
            with self.subTest(key=key, value=value):
                adb = FakeAdb()
                adb.responses[("shell", "getprop " + key)] = record(value + "\n")
                report, code = collector.collect(adb)
                self.assertEqual(code, 3)
                self.assertEqual(report["status"], "target_mismatch")
                self.assertEqual(report["device_tree"], {})
                self.assertNotIn("kernel", report)
                self.assertEqual(adb.calls, [("run", "get-state")] +
                                 [("shell", "getprop " + prop) for prop in collector.PROPERTIES])

    def test_failed_property_read_does_not_count_as_target_mismatch_or_continue(self):
        adb = FakeAdb()
        adb.responses[("shell", "getprop ro.product.device")] = record(
            status="error", exit_code=1, stderr="permission denied")
        report, code = collector.collect(adb)
        self.assertEqual((code, report["status"]), (1, "incomplete"))
        self.assertEqual(report["identity"]["ro.product.device"]["stderr"], "permission denied")
        self.assertNotIn(("shell", collector.FIND_TREE), adb.calls)
        self.assertNotIn(("shell", "uname -r"), adb.calls)

    def test_offline_unauthorized_or_transport_failure_stops_immediately(self):
        for state in (record("offline\n"), record("unauthorized\n"),
                      record(status="error", exit_code=None, stderr="ADB command timed out")):
            with self.subTest(state=state):
                adb = FakeAdb()
                adb.responses[("run", "get-state")] = state
                report, code = collector.collect(adb)
                self.assertEqual((code, report["status"]), (2, "incomplete"))
                self.assertEqual(adb.calls, [("run", "get-state")])
                self.assertEqual(report["identity"], {})

    def test_failure_of_each_required_metadata_read_makes_report_incomplete(self):
        for command in ("uname -r", collector.DEVICE_NAMES, collector.FIND_TREE):
            with self.subTest(command=command):
                adb = FakeAdb()
                adb.responses[("shell", command)] = record(
                    status="error", exit_code=13, stderr="permission denied")
                report, code = collector.collect(adb)
                self.assertEqual((code, report["status"]), (1, "incomplete"))
                if command == collector.FIND_TREE:
                    self.assertEqual(report["device_tree"]["nodes"], {})

    def test_node_parse_permission_and_transport_errors_remain_failures(self):
        responses = (
            record("PROPERTY reg\n00 00\n"),
            record("PROPERTY reg\n\nEND 13\n"),
            record(VALID_NODE, status="error", exit_code=1, stderr="connection closed"),
            record(""),
        )
        for response in responses:
            with self.subTest(response=response):
                adb = FakeAdb()
                adb.responses[("shell", collector.read_node_command(NODE))] = response
                report, code = collector.collect(adb)
                self.assertEqual((code, report["status"]), (1, "incomplete"))
                self.assertEqual(report["device_tree"]["nodes"][NODE]["status"], "error")

    def test_no_visible_camera_nodes_is_an_observation_not_driver_diagnosis(self):
        adb = FakeAdb()
        adb.responses[("shell", collector.FIND_TREE)] = record(
            "/sys/firmware/devicetree/base/soc/serial@1\n")
        report, code = collector.collect(adb)
        self.assertEqual((code, report["status"]), (0, "collected"))
        self.assertFalse(report["device_tree"]["camera_nodes_visible"])
        self.assertEqual(report["device_tree"]["nodes"], {})
        self.assertNotIn("driver_absent", report["device_tree"])

    def test_discovery_node_limit_is_reported_and_read_limit_enforced(self):
        adb = FakeAdb()
        nodes = [f"/proc/device-tree/soc/camera@{number:02d}" for number in range(65)]
        adb.responses[("shell", collector.FIND_TREE)] = record("\n".join(nodes))
        for node in nodes:
            adb.responses[("shell", collector.read_node_command(node))] = record(VALID_NODE)
        report, code = collector.collect(adb)
        self.assertEqual((code, report["status"]), (1, "incomplete"))
        self.assertTrue(report["device_tree"]["node_limit_reached"])
        self.assertEqual(list(report["device_tree"]["nodes"]), nodes[:64])
        self.assertNotIn(("shell", collector.read_node_command(nodes[64])), adb.calls)


class DeviceTreeParsingTests(unittest.TestCase):
    def test_strings_cells_and_noncell_bytes_preserve_raw_evidence(self):
        props = collector.decode_node(
            "PROPERTY compatible\n76 65 6e 64 6f 72 2c 69 72 00 71 63 6f 6d 2c 63 61 6d 65 72 61 00\nEND 0\n"
            "PROPERTY reg\n00 00 00 20 12 34 56 78\nEND 0\n"
            "PROPERTY gpios\n01 02 03\nEND 0\n")
        self.assertEqual(props["compatible"]["strings"], ["vendor,ir", "qcom,camera"])
        self.assertEqual(props["reg"]["cells_be32"], [0x20, 0x12345678])
        self.assertEqual(props["gpios"], {"status": "ok", "hex": "010203"})

    def test_malformed_truncated_duplicate_and_unknown_records_are_rejected(self):
        records = (
            "noise\n", "PROPERTY unexpected\n00\nEND 0\n",
            "PROPERTY reg\n00 00 00 00\n", "PROPERTY reg\n0\nEND 0\n",
            "PROPERTY reg\ngg\nEND 0\n", "PROPERTY reg\n00\nEND nope\n",
            "PROPERTY reg\n00\nEND 0\nPROPERTY reg\n01\nEND 0\n",
            "PROPERTY reg\n*\nEND 0\n",
        )
        for text in records:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    collector.decode_node(text)

    def test_permission_denied_property_does_not_decode_a_value(self):
        self.assertEqual(collector.decode_node("PROPERTY reg\n\nEND 13\n"),
                         {"reg": {"status": "error", "exit_code": 13}})

    def test_only_canonical_live_tree_camera_paths_are_selected(self):
        good = "/proc/device-tree/soc/cci@1"
        bad = (
            "/tmp/camera@2", "/proc/device-tree-evil/camera@2",
            "/proc/device-tree/soc/../camera@2", "/proc/device-tree//camera@2",
            "/proc/device-tree/camera@2/", "proc/device-tree/camera@2",
            "/proc/device-tree/soc/serial@2",
        )
        self.assertEqual(collector.camera_nodes("\n".join((NODE, good, NODE) + bad)),
                         sorted([NODE, good]))


class GeneratedShellTests(unittest.TestCase):
    def test_platform_uevent_fallback_reads_only_selected_camera_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ("soc:qcom,camera@0", "fda0c000.cci", "unrelated-device"):
                node = base / name
                node.mkdir()
                (node / "uevent").write_text("DRIVER=fixture\nOF_NAME=" + name + "\n")
            command = collector.PLATFORM_DEVICES.replace(
                "/sys/bus/platform/devices", shlex.quote(str(base)))
            result = subprocess.run(["/bin/sh", "-c", command], capture_output=True,
                                    text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OF_NAME=soc:qcom,camera@0", result.stdout)
            self.assertIn("OF_NAME=fda0c000.cci", result.stdout)
            self.assertNotIn("unrelated-device", result.stdout)
            self.assertEqual(result.stdout.count("END 0"), 2)

    def test_discovery_follows_device_tree_root_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            actual = base / "actual-tree"
            node = actual / "soc" / "cci@1" / "camera@2"
            node.mkdir(parents=True)
            root = base / "device-tree"
            root.symlink_to(actual, target_is_directory=True)
            command = collector.FIND_TREE.replace(
                "/sys/firmware/devicetree/base /proc/device-tree", shlex.quote(str(root)))
            result = subprocess.run(["/bin/sh", "-c", command], capture_output=True,
                                    text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(root / "soc" / "cci@1" / "camera@2"), result.stdout.splitlines())

    def test_media_controller_model_is_collected_without_name_attribute(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            media = base / "media" / "media0"
            media.mkdir(parents=True)
            (media / "model").write_text("fixture-camera-controller\n")
            video = base / "video4linux" / "v4l-subdev0"
            video.mkdir(parents=True)
            (video / "name").write_text("fixture-cci\n")
            command = collector.DEVICE_NAMES.replace(
                "/sys/class/video4linux", shlex.quote(str(base / "video4linux"))).replace(
                "/sys/class/media", shlex.quote(str(base / "media")))
            result = subprocess.run(["/bin/sh", "-c", command], capture_output=True,
                                    text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fixture-camera-controller", result.stdout)
            self.assertIn("fixture-cci", result.stdout)

    def test_real_od_command_reads_binary_properties_and_quotes_untrusted_path(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            # Both quote-breaking syntax and command substitution stay literal.
            node = base / "camera'; touch PWNED; #$(touch PWNED_SUB)"
            node.mkdir()
            strings = b"vendor,iris\0qcom,camera\0"
            repeated_cells = b"\0" * 64 + b"\x12\x34\x56\x78"
            (node / "compatible").write_bytes(strings)
            (node / "reg").write_bytes(repeated_cells)
            (node / "status").write_bytes(b"disabled\0")
            (node / "not-in-allowlist").write_bytes(b"ignored\0")
            result = subprocess.run(["/bin/sh", "-c", collector.read_node_command(str(node))],
                                    cwd=base, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((base / "PWNED").exists())
            self.assertFalse((base / "PWNED_SUB").exists())
            props = collector.decode_node(result.stdout)
            self.assertEqual(set(props), {"compatible", "reg", "status"})
            self.assertEqual(props["compatible"]["hex"], strings.hex())
            self.assertEqual(props["compatible"]["strings"], ["vendor,iris", "qcom,camera"])
            self.assertEqual(props["reg"]["hex"], repeated_cells.hex())
            self.assertEqual(props["reg"]["cells_be32"], [0] * 16 + [0x12345678])
            self.assertEqual(props["status"]["strings"], ["disabled"])

    def test_real_shell_preserves_od_failure_status_in_property_record(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            node = base / "camera"
            node.mkdir()
            (node / "reg").write_bytes(b"\0\0\0\x01")
            fake_od = base / "od"
            fake_od.write_text("#!/bin/sh\necho 'fixture permission denied' >&2\nexit 13\n")
            fake_od.chmod(0o755)
            process_env = dict(os.environ, PATH=str(base) + os.pathsep + os.defpath)
            result = subprocess.run(["/bin/sh", "-c", collector.read_node_command(str(node))],
                                    env=process_env, capture_output=True, text=True, check=False)
            self.assertIn("fixture permission denied", result.stderr)
            self.assertEqual(collector.decode_node(result.stdout),
                             {"reg": {"status": "error", "exit_code": 13}})


class AdbTransportTests(unittest.TestCase):
    def test_serial_is_redacted_from_errors_without_corrupting_successful_property(self):
        for code in (0, 1):
            with self.subTest(code=code):
                completed = subprocess.CompletedProcess(["adb"], code, "36\n", "device '36' not found")
                with mock.patch.object(collector.subprocess, "run", return_value=completed):
                    result = collector.Adb(serial="36").run("shell", "getprop ro.build.version.sdk")
                self.assertNotIn("36", result["stderr"])
                self.assertEqual(result["stdout"], "36\n" if code == 0 else "[REDACTED]\n")

    def test_timeout_hides_command_and_device_serial(self):
        adb = collector.Adb("adb fixture", "private-serial-fixture", 0.25)
        with mock.patch.object(collector.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(
                                   ["adb", "-s", "private-serial-fixture"], 0.25)) as run:
            result = adb.run("get-state")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["exit_code"])
        self.assertEqual(result["stderr"], "ADB command timed out")
        self.assertNotIn("private-serial-fixture", json.dumps(result))
        self.assertEqual(run.call_args.args[0],
                         ["adb fixture", "-s", "private-serial-fixture", "get-state"])
        self.assertEqual(run.call_args.kwargs["timeout"], 0.25)

    def test_missing_executable_returns_error_record(self):
        with tempfile.TemporaryDirectory() as directory:
            result = collector.Adb(str(Path(directory) / "missing-adb")).run("get-state")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["exit_code"])
        self.assertIn("Cannot run ADB:", result["stderr"])

    def test_nonzero_exit_and_output_truncation_cannot_report_success(self):
        cases = ((1, "device\n", "offline", False),
                 (0, "x" * 262145, "", True),
                 (0, "", "x" * 16385, True))
        for returncode, stdout, stderr, truncated in cases:
            with self.subTest(returncode=returncode, truncated=truncated):
                completed = subprocess.CompletedProcess(["adb"], returncode, stdout, stderr)
                with mock.patch.object(collector.subprocess, "run", return_value=completed):
                    result = collector.Adb().run("get-state")
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["truncated"], truncated)
                self.assertLessEqual(len(result["stdout"]), 262144)
                self.assertLessEqual(len(result["stderr"]), 16384)


class CliTests(unittest.TestCase):
    def test_existing_report_is_never_overwritten_and_adb_is_not_constructed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("existing evidence\n")
            with mock.patch.object(collector, "Adb") as adb, contextlib.redirect_stderr(io.StringIO()):
                code = collector.main(["--output", str(output)])
            self.assertEqual(code, 2)
            adb.assert_not_called()
            self.assertEqual(output.read_text(), "existing evidence\n")

    def test_invalid_timeout_stops_before_creating_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            for value in ("0", "-1", "121", "nan", "inf"):
                with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        collector.main(["--timeout", value, "--output", str(output)])
                    self.assertEqual(raised.exception.code, 2)
                    self.assertFalse(output.exists())

    def test_cli_runs_simulated_executable_with_literal_metacharacters_and_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            adb_path = base / "adb fixture; touch PWNED"
            log_path = base / "requests.jsonl"
            output_path = base / "collected.json"
            fake = FakeAdb()
            mapping = {call[1]: response["stdout"] for call, response in fake.responses.items()
                       if call[0] == "shell"}
            adb_path.write_text(
                "#!" + sys.executable + "\n"
                "import json, sys\n"
                "from pathlib import Path\n"
                f"log = Path({str(log_path)!r})\n"
                "with log.open('a') as output: output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "args = sys.argv[1:]\n"
                "if args[:2] != ['-s', 'fixture-serial']: sys.exit(80)\n"
                "args = args[2:]\n"
                "if args == ['get-state']: print('device'); sys.exit(0)\n"
                f"responses = {mapping!r}\n"
                "if len(args) != 2 or args[0] != 'shell' or args[1] not in responses: sys.exit(81)\n"
                "sys.stdout.write(responses[args[1]])\n")
            adb_path.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--adb", str(adb_path),
                 "--serial", "fixture-serial", "--output", str(output_path)],
                cwd=base, capture_output=True, text=True, check=False, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((base / "PWNED").exists())
            report = json.loads(output_path.read_text())
            self.assertEqual(report["status"], "collected")
            self.assertNotIn("fixture-serial", output_path.read_text())
            self.assertIn("not a sensor or biometric test", report["purpose"])
            requests = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertEqual(requests[0], ["-s", "fixture-serial", "get-state"])
            self.assertEqual(len(requests), 1 + len(collector.PROPERTIES) + 4)


if __name__ == "__main__":
    unittest.main()
