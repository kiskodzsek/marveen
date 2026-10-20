#!/usr/bin/env python3
"""Tests for scripts/image-safety/check.py (card 1a4fe725, Viktor 9018, Lex 9016).

Mock detectors only. The fixtures are a few bytes of filler with an image suffix:
no real image, no photo-like content, and by design no nudity test set (Lex 9016:
recall on child nudity is not measured, and no such test image is generated).

Run: python3 scripts/__tests__/image-safety-check.test.py   (exit 0 = all green)
"""
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT_DIR = HERE.parent / "image-safety"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location("check", SCRIPT_DIR / "check.py")
check = importlib.util.module_from_spec(spec)
sys.modules["check"] = check
spec.loader.exec_module(check)


def det(name, value, threshold=0.5, calls=None):
    def score(p):
        if calls is not None:
            calls.append(p.name)
        if isinstance(value, Exception):
            raise value
        return value
    return check.Detector(name, threshold, score)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name)) / "mflux"
        self.root.mkdir()
        self.store = Path(self.tmp.name) / "store"
        self.sent = []
        self.sinks = check.Sinks(
            log_path=self.store / "image-safety.log",
            blocklist_path=self.store / "blocklist.tsv",
            send=lambda to, text: self.sent.append((to, text)),
        )
        self.inbox = self.root / check.UNSCREENED
        self.inbox.mkdir()

    def tearDown(self):
        # mode 000 files must be readable again for cleanup
        for dp, dn, fn in os.walk(self.tmp.name):
            for n in dn + fn:
                p = os.path.join(dp, n)
                if not os.path.islink(p):
                    os.chmod(p, 0o700)
        self.tmp.cleanup()

    def put(self, rel, data=b"\x89PNG-synthetic-filler"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def mode(self, p):
        return stat.S_IMODE(os.lstat(p).st_mode)


class InboxTests(Base):
    def test_pass_moves_image_and_sidecar_to_dest(self):
        self.put("_unscreened/kep_seed7.png")
        self.put("_unscreened/kep_seed7.metadata.json", b'{"prompt":"x"}')
        rc = check.run_inbox(self.root, "out/panna", [det("a", 0.1), det("b", 0.2)], self.sinks)
        self.assertEqual(rc, check.EXIT_OK)
        self.assertTrue((self.root / "out/panna/kep_seed7.png").is_file())
        self.assertTrue((self.root / "out/panna/kep_seed7.metadata.json").is_file())
        self.assertEqual(os.listdir(self.inbox), [])
        self.assertEqual(self.sent, [])
        self.assertTrue((self.root / check.PASSED_LEDGER).is_file())

    def test_flag_quarantines_mode_000_and_records_only_allowed_fields(self):
        self.put("_unscreened/furdes-x_seed42.png")
        self.put("_unscreened/furdes-x_seed42.metadata.json", b'{"prompt":"SECRET PROMPT TEXT"}')
        rc = check.run_inbox(self.root, "out/panna", [det("a", 0.1), det("nudenet", 0.9)], self.sinks)
        self.assertEqual(rc, check.EXIT_QUARANTINED)
        q = self.root / check.QUARANTINE / "furdes-x_seed42.png"
        self.assertTrue(os.path.lexists(q))
        self.assertEqual(self.mode(q), 0)
        self.assertEqual(self.mode(self.root / check.QUARANTINE), 0o700)
        self.assertFalse((self.root / "out/panna/furdes-x_seed42.png").exists())
        # sidecar kept as documentation, outside the quarantine, not next to passed images
        self.assertTrue((self.root / check.QUARANTINE_META / "furdes-x_seed42.metadata.json").is_file())
        log = self.sinks.log_path.read_text()
        self.assertEqual(self.mode(self.sinks.log_path), 0o600)
        self.assertIn("file=furdes-x_seed42.png", log)
        self.assertIn("prompt=furdes-x", log)
        self.assertIn("seed=42", log)
        self.assertIn("detector=nudenet", log)
        self.assertIn("score=0.900", log)
        self.assertEqual(self.sinks.blocklist_path.read_text(), "furdes-x\t42\n")
        self.assertEqual(self.mode(self.sinks.blocklist_path), 0o600)
        self.assertEqual(sorted(t for t, _ in self.sent), ["klodel", "mira"])
        for _, text in self.sent + [(None, log)]:
            self.assertNotIn("SECRET PROMPT TEXT", text)
            self.assertNotIn(str(self.root), text)  # no path / link to the content
            self.assertNotIn("base64", text)

    def test_detector_error_is_quarantine(self):
        self.put("_unscreened/a_seed1.png")
        rc = check.run_inbox(self.root, "out", [det("a", RuntimeError("boom"))], self.sinks)
        self.assertEqual(rc, check.EXIT_QUARANTINED)
        self.assertIn("score=error:RuntimeError", self.sinks.log_path.read_text())

    def test_out_of_range_score_is_quarantine(self):
        self.put("_unscreened/a_seed1.png")
        rc = check.run_inbox(self.root, "out", [det("a", 1.7)], self.sinks)
        self.assertEqual(rc, check.EXIT_QUARANTINED)
        self.assertIn("error:ScoreOutOfRange", self.sinks.log_path.read_text())

    def test_no_detectors_is_quarantine(self):
        self.put("_unscreened/a_seed1.png")
        self.assertEqual(check.run_inbox(self.root, "out", [], self.sinks), check.EXIT_QUARANTINED)

    def test_later_detector_still_runs_after_a_pass(self):
        self.put("_unscreened/a_seed1.png")
        calls = []
        rc = check.run_inbox(self.root, "out", [det("a", 0.0, calls=calls), det("b", 0.95, calls=calls)], self.sinks)
        self.assertEqual(calls, ["a_seed1.png", "a_seed1.png"])
        self.assertEqual(rc, check.EXIT_QUARANTINED)

    def test_symlink_is_quarantined_not_followed(self):
        target = self.put("elsewhere/real.png")
        os.symlink(target, self.inbox / "link_seed3.png")
        calls = []
        rc = check.run_inbox(self.root, "out", [det("a", 0.0, calls=calls)], self.sinks)
        self.assertEqual(rc, check.EXIT_QUARANTINED)
        self.assertEqual(calls, [])  # never opened through the link
        self.assertTrue(os.path.islink(self.root / check.QUARANTINE / "link_seed3.png"))
        self.assertTrue(target.is_file())  # the target is untouched
        self.assertIn("error:Symlink", self.sinks.log_path.read_text())

    def test_dest_outside_root_or_into_screening_dirs_is_refused(self):
        self.put("_unscreened/a_seed1.png")
        for dest in ("../outside", check.QUARANTINE, check.UNSCREENED + "/x", "out/" + check.QUARANTINE):
            self.assertEqual(check.run_inbox(self.root, dest, [det("a", 0.0)], self.sinks), check.EXIT_USAGE)
        self.assertTrue((self.inbox / "a_seed1.png").is_file())

    def test_name_collision_in_quarantine_does_not_overwrite(self):
        self.put("_unscreened/a_seed1.png")
        check.run_inbox(self.root, "out", [det("a", 0.9)], self.sinks)
        self.put("_unscreened/a_seed1.png", b"second")
        check.run_inbox(self.root, "out", [det("a", 0.9)], self.sinks)
        names = sorted(os.listdir(self.root / check.QUARANTINE))
        self.assertEqual(names, ["a_seed1.png", "a_seed1.png.1"])

    def test_failed_message_does_not_stop_the_batch(self):
        def bad_send(to, text):
            raise OSError("queue down")
        self.sinks.send = bad_send
        self.put("_unscreened/a_seed1.png")
        self.put("_unscreened/b_seed2.png")
        rc = check.run_inbox(self.root, "out", [det("a", 0.9)], self.sinks)
        self.assertEqual(rc, check.EXIT_QUARANTINED)
        self.assertEqual(len(os.listdir(self.root / check.QUARANTINE)), 2)


class SweepTests(Base):
    def test_sweep_quarantines_flagged_copies_and_skips_screening_dirs(self):
        self.put("final/fotok/x_seed5.jpg")
        self.put("drafts/y_seed6.png")
        self.put("_quarantine/old.png")
        calls = []
        rc = check.run_sweep(self.root, ["out", "final", "drafts"], [det("a", 0.9, calls=calls)], self.sinks)
        self.assertEqual(rc, check.EXIT_QUARANTINED)
        self.assertEqual(sorted(calls), ["x_seed5.jpg", "y_seed6.png"])
        self.assertNotIn("old.png", calls)
        self.assertFalse((self.root / "final/fotok/x_seed5.jpg").exists())

    def test_sweep_skips_already_passed_content(self):
        self.put("out/a_seed1.png")
        calls = []
        check.run_sweep(self.root, ["out"], [det("a", 0.1, calls=calls)], self.sinks)
        check.run_sweep(self.root, ["out"], [det("a", 0.1, calls=calls)], self.sinks)
        self.assertEqual(calls, ["a_seed1.png"])
        # changed content is screened again
        self.put("out/a_seed1.png", b"different bytes")
        check.run_sweep(self.root, ["out"], [det("a", 0.1, calls=calls)], self.sinks)
        self.assertEqual(len(calls), 2)


class ReviewFixTests(Base):
    """Viktor's b0471f83 review (card 1a4fe725 #5060)."""

    def test_b1_unreadable_file_does_not_stop_the_sweep(self):
        locked = self.put("out/a_locked_seed1.png")
        os.chmod(locked, 0)
        self.put("final/b_seed2.png")
        calls = []
        rc = check.run_sweep(self.root, ["out", "final"], [det("a", 0.1, calls=calls)], self.sinks)
        self.assertEqual(rc, check.EXIT_FILE_ERRORS)
        self.assertEqual(calls, ["b_seed2.png"])  # final/ still screened
        self.assertTrue(os.path.lexists(locked))  # left where it is
        self.assertIn("file=a_locked_seed1.png\tverdict=error:PermissionError", self.sinks.log_path.read_text())

    def test_b1_reject_dirs_are_untouched_by_the_sweep(self):
        keep = [self.put("out/panna-elvetett/x_seed1.png"), self.put("final/visszavonva/y.jpg"),
                self.put("out/Panna-Elvetett/z.png"), self.put("quarantine-meta/m.png")]
        locked = self.put("out/panna-elvetett/l_seed2.png")
        os.chmod(locked, 0)
        calls = []
        rc = check.run_sweep(self.root, ["out", "final", "quarantine-meta"], [det("a", 0.99, calls=calls)], self.sinks)
        self.assertEqual(rc, check.EXIT_OK)
        self.assertEqual(calls, [])
        for k in keep + [locked]:
            self.assertTrue(os.path.lexists(k), k)
        self.assertFalse((self.root / check.QUARANTINE).exists())

    def test_l1_detector_change_rescreens_passed_content(self):
        self.put("out/a_seed1.png")
        calls = []
        check.run_sweep(self.root, ["out"], [det("a", 0.1, threshold=0.5, calls=calls)], self.sinks)
        check.run_sweep(self.root, ["out"], [det("a", 0.1, threshold=0.5, calls=calls)], self.sinks)
        self.assertEqual(len(calls), 1)  # same content, same detectors: skipped
        check.run_sweep(self.root, ["out"], [det("a", 0.1, threshold=0.3, calls=calls)], self.sinks)
        self.assertEqual(len(calls), 2)

    def test_l2_other_image_formats_are_swept(self):
        for ext in ("heic", "gif", "tiff", "avif", "BMP"):
            self.put(f"out/a.{ext}", ext.encode())  # distinct bytes: the ledger skips by content
        calls = []
        check.run_sweep(self.root, ["out"], [det("a", 0.1, calls=calls)], self.sinks)
        self.assertEqual(len(calls), 5)

    def test_l3_symlinked_inbox_is_refused(self):
        os.rmdir(self.inbox)
        real = self.root.parent / "elsewhere-inbox"
        real.mkdir()
        (real / "a_seed1.png").write_bytes(b"x")
        os.symlink(real, self.inbox)
        rc = check.run_inbox(self.root, "out", [det("a", 0.0)], self.sinks)
        self.assertEqual(rc, check.EXIT_USAGE)
        self.assertTrue((real / "a_seed1.png").is_file())

    def test_screening_dirs_equal_the_gate_list(self):
        gate = (HERE.parent / "self-pace-gate.mjs").read_text(encoding="utf-8")
        import re
        m = re.search(r"const SCREENING_DIR_NAMES = \[([^\]]*)\]", gate)
        self.assertIsNotNone(m)
        names = re.findall(r"'([^']+)'", m.group(1))
        self.assertEqual(sorted(names), sorted(check.SCREENING_DIRS))


class GuardTests(unittest.TestCase):
    def test_network_is_blocked_after_block_network(self):
        code = (
            "import sys, socket, os; sys.path.insert(0, %r); import check; check.block_network();\n"
            "assert os.environ['HF_HUB_OFFLINE'] == '1' and os.environ['HF_HUB_DISABLE_TELEMETRY'] == '1'\n"
            "for f in (lambda: socket.create_connection(('127.0.0.1', 9)),\n"
            "          lambda: socket.socket().connect(('127.0.0.1', 9))):\n"
            "    try: f(); sys.exit('connected')\n"
            "    except OSError as e: assert 'disabled' in str(e), e\n"
        ) % str(SCRIPT_DIR)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_cli_without_models_touches_nothing_and_exits_3(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "mflux"
            (root / check.UNSCREENED).mkdir(parents=True)
            img = root / check.UNSCREENED / "a_seed1.png"
            img.write_bytes(b"filler")
            models = Path(t) / "empty-models"
            models.mkdir()
            r = subprocess.run([sys.executable, str(SCRIPT_DIR / "check.py"), "--root", str(root),
                                "--models", str(models), "inbox", "--dest", "out"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, check.EXIT_DETECTORS_UNAVAILABLE, r.stderr)
            self.assertTrue(img.is_file())
            self.assertEqual(stat.S_IMODE(img.stat().st_mode) & 0o400, 0o400)
            self.assertFalse((root / check.QUARANTINE).exists())

    def test_pickle_files_are_refused(self):
        try:
            import detectors  # noqa: F401  (imports only stdlib + check at module level)
        except ImportError as e:
            self.skipTest(f"detectors import: {e}")
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "pytorch_model.bin").write_bytes(b"x")
            with self.assertRaises(check.DetectorError):
                detectors._refuse_pickles(d)


class DetectorPins(unittest.TestCase):
    """Viktor 9018 P1, #5205 O5, 9429: pinned files, CPU provider only. Stdlib
    only: onnxruntime, cv2 and numpy are faked, no model is loaded."""

    @classmethod
    def setUpClass(cls):
        import detectors
        cls.det = detectors

    def _sha(self, b):
        import hashlib
        return hashlib.sha256(b).hexdigest()

    def test_pins_refuse_mismatch_missing_symlink_and_extra_files(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "model.safetensors").write_bytes(b"weights")
            pins = {"model.safetensors": self._sha(b"weights")}
            self.det._verify_pins(d, pins)
            self.det._only_pinned_files(d, pins)
            with self.assertRaises(check.DetectorError):
                self.det._verify_pins(d, {"model.safetensors": self._sha(b"other")})
            with self.assertRaises(check.DetectorError):
                self.det._verify_pins(d, {**pins, "config.json": self._sha(b"{}")})
            (d / "model.safetensors.index.json").write_text("{}")
            with self.assertRaises(check.DetectorError):
                self.det._only_pinned_files(d, pins)
            (d / "model.safetensors.index.json").unlink()
            (d / "real").write_bytes(b"weights")
            (d / "model.safetensors").unlink()
            os.symlink(d / "real", d / "model.safetensors")
            with self.assertRaises(check.DetectorError):
                self.det._verify_pins(d, pins)
            with self.assertRaises(check.DetectorError):
                self.det._pinned_bytes(d / "model.safetensors", pins["model.safetensors"])

    def test_json_pin_is_on_content_not_formatting(self):
        import json
        canon = json.dumps(["A_EXPOSED", "B_COVERED"], separators=(",", ":")).encode()
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "labels.json"
            p.write_text('[\n "A_EXPOSED",\n "B_COVERED"\n]\n')
            self.assertEqual(self.det._pinned_json(p, self._sha(canon)), ["A_EXPOSED", "B_COVERED"])
            p.write_text('["A_EXPOSED"]')
            with self.assertRaises(check.DetectorError):
                self.det._pinned_json(p, self._sha(canon))

    def test_no_onnxruntime_tools_or_quantization_import(self):
        import re
        src = (SCRIPT_DIR / "detectors.py").read_text(encoding="utf-8")
        code = "\n".join(l.split("#", 1)[0].rstrip() for l in src.splitlines())
        self.assertNotRegex(code, r"onnxruntime\.(tools|quantization)")
        self.assertEqual(re.findall(r"^\s*(?:import|from)\s+onnxruntime\b.*$", code, re.M),
                         ["    import onnxruntime as ort"])

    def _nudenet_dir(self, d, providers_seen):
        import json
        import types
        files = {"model.onnx": b"onnx", "labels.json": b'["A_EXPOSED","FEET_EXPOSED"]',
                 "config.json": b'{"input_size": 320}'}
        for n, b in files.items():
            (d / n).write_bytes(b)
        canon = lambda b: json.dumps(json.loads(b), sort_keys=True, separators=(",", ":")).encode()
        pins = {"model.onnx": self._sha(files["model.onnx"])}
        jpins = {n: self._sha(canon(files[n])) for n in ("labels.json", "config.json")}

        class Session:
            def __init__(self, model, providers):
                self.model = model
                providers_seen.append(providers)

            def get_providers(self):
                return list(Session.active)

            def get_inputs(self):
                return [types.SimpleNamespace(name="images")]

        fakes = {"onnxruntime": types.SimpleNamespace(InferenceSession=Session),
                 "cv2": types.ModuleType("cv2"), "numpy": types.ModuleType("numpy")}
        return pins, jpins, Session, fakes

    def test_nudenet_runs_on_the_cpu_provider_only(self):
        from unittest import mock
        seen = []
        with tempfile.TemporaryDirectory() as t:
            pins, jpins, Session, fakes = self._nudenet_dir(Path(t), seen)
            with mock.patch.dict(sys.modules, fakes), \
                    mock.patch.object(self.det, "NUDENET_PINS", pins), \
                    mock.patch.object(self.det, "NUDENET_JSON_PINS", jpins):
                Session.active = ["CPUExecutionProvider"]
                d = self.det.load_nudenet(Path(t))
                self.assertEqual(seen, [["CPUExecutionProvider"]])
                self.assertTrue(d.name.startswith("nudenet:"))
                Session.active = ["AzureExecutionProvider", "CPUExecutionProvider"]
                with self.assertRaises(check.DetectorError):
                    self.det.load_nudenet(Path(t))

    def test_nudenet_refuses_a_tampered_model_before_the_session(self):
        from unittest import mock
        seen = []
        with tempfile.TemporaryDirectory() as t:
            pins, jpins, Session, fakes = self._nudenet_dir(Path(t), seen)
            (Path(t) / "model.onnx").write_bytes(b"tampered")
            with mock.patch.dict(sys.modules, fakes), \
                    mock.patch.object(self.det, "NUDENET_PINS", pins), \
                    mock.patch.object(self.det, "NUDENET_JSON_PINS", jpins):
                Session.active = ["CPUExecutionProvider"]
                with self.assertRaises(check.DetectorError):
                    self.det.load_nudenet(Path(t))
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
