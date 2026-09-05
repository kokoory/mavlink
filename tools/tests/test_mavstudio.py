"""Tests for tools/mavstudio.

Run from the repository root:

    PYTHONPATH=tools python3 -m unittest discover -s tools/tests -v
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mavstudio import mosa  # noqa: E402
from mavstudio.bandwidth import compute_budget, frame_bytes  # noqa: E402
from mavstudio.build import build_profile_dialect  # noqa: E402
from mavstudio.capabilities import CapabilitySet  # noqa: E402
from mavstudio.catalog import load_catalog  # noqa: E402
from mavstudio.customdialect import (  # noqa: E402
    DialectError,
    add_message,
    build_message,
    check_id,
    load_custom_dialect,
    parse_field_spec,
    remove_message,
    validate_message,
)
from mavstudio.icd import generate_markdown  # noqa: E402
from mavstudio.model import split_type, type_size  # noqa: E402
from mavstudio.parser import dialect_xml, parse_file  # noqa: E402
from mavstudio.profile import MessageOverride, Profile, resolve  # noqa: E402
from mavstudio.project import Project  # noqa: E402
from mavstudio.store import ident, slug  # noqa: E402
from mavstudio.validate import validate_all  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFS = os.path.join(REPO, "message_definitions", "v1.0")


def catalog():
    if not hasattr(catalog, "_cached"):
        catalog._cached = load_catalog(DEFS)
    return catalog._cached


class TestModel(unittest.TestCase):
    def test_split_type(self):
        self.assertEqual(split_type("float"), ("float", 1))
        self.assertEqual(split_type("uint16_t[4]"), ("uint16_t", 4))

    def test_type_size(self):
        self.assertEqual(type_size("float[4]"), 16)
        self.assertEqual(type_size("uint8_t"), 1)
        self.assertEqual(type_size("bogus"), 0)


class TestCatalog(unittest.TestCase):
    def test_parses_every_dialect(self):
        c = catalog()
        self.assertGreater(len(c.dialects), 15)
        self.assertIn("common", c.dialects)
        self.assertIn("HEARTBEAT", c.messages)

    def test_payload_size_matches_wire_format(self):
        # ATTITUDE is uint32 + 6 floats = 28 bytes; the MAVLink 2 frame adds 12.
        self.assertEqual(catalog().message("ATTITUDE").payload_bytes, 28)
        self.assertEqual(frame_bytes(28, 2, False), 40)
        self.assertEqual(frame_bytes(28, 2, True), 53)
        self.assertEqual(frame_bytes(28, 1, False), 36)

    def test_include_closure(self):
        closure = catalog().include_closure("ardupilotmega")
        self.assertIn("common", closure)
        self.assertIn("minimal", closure)

    def test_no_conflicts_inside_a_real_dialect(self):
        # Upstream has benign cross-dialect id reuse (paparazzi vs ardupilotmega)
        # but nothing may collide inside one include closure.
        c = catalog()
        for name in ("common", "ardupilotmega", "all", "development"):
            self.assertEqual(c.conflicts_in(c.include_closure(name)), {}, name)

    def test_extension_fields_are_marked(self):
        message = catalog().message("ATTITUDE_QUATERNION")
        self.assertTrue(message.has_extensions)
        self.assertEqual(
            [f.name for f in message.fields if f.is_extension], ["repr_offset_q"]
        )


class TestParserRoundTrip(unittest.TestCase):
    def test_message_xml_is_reparseable(self):
        message = catalog().message("ATTITUDE_QUATERNION")
        document = dialect_xml([], "3", "0", [], [message])
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(document)
            path = handle.name
        try:
            reparsed = parse_file(path).messages[0]
        finally:
            os.unlink(path)
        self.assertEqual(reparsed.name, message.name)
        self.assertEqual(reparsed.id, message.id)
        self.assertEqual(reparsed.payload_bytes, message.payload_bytes)
        self.assertEqual(
            [f.is_extension for f in reparsed.fields],
            [f.is_extension for f in message.fields],
        )

    def test_no_double_hyphen_in_comments(self):
        # A "--" inside an XML comment makes the document unparsable.
        document = dialect_xml([], "3", "0", [], [], header_comment="a -- b")
        self.assertNotIn("--", document.split("<!--")[1].split("-->")[0])

    def test_superseded_survives_a_round_trip(self):
        # <superseded> is a softer deprecation upstream uses 40 times; dropping
        # it on the way out would silently lose the replacement pointer.
        message = catalog().message("SMART_BATTERY_INFO")
        self.assertIsNotNone(message.superseded)
        self.assertEqual(message.superseded[1], "BATTERY_INFO")
        self.assertEqual(catalog().messages["SMART_BATTERY_INFO"].status,
                         "superseded")
        document = dialect_xml([], "3", "0", [], [message])
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(document)
            path = handle.name
        try:
            reparsed = parse_file(path).messages[0]
        finally:
            os.unlink(path)
        self.assertEqual(reparsed.superseded, message.superseded)

    def test_deprecated_keeps_both_attributes(self):
        # mavschema.xsd requires replaced_by even when it is empty.
        enum = next(e for e in catalog().enums.values() if e.name == "MAV_FRAME")
        entry = enum.entry("MAV_FRAME_RESERVED_13")
        self.assertIsNotNone(entry.deprecated)
        from mavstudio.parser import enum_xml
        rendered = "\n".join(enum_xml(enum))
        self.assertIn('replaced_by=""', rendered)


class TestCapabilities(unittest.TestCase):
    def test_every_standard_message_has_a_capability(self):
        c = catalog()
        _, unclaimed = CapabilitySet().coverage(c)
        orphans = sorted(
            n for n in unclaimed
            if c.dialect_of(n) in ("minimal", "standard", "common")
        )
        self.assertEqual(orphans, [], "standard messages with no capability")

    def test_capability_owns_expected_messages(self):
        owned = CapabilitySet().messages_for("ftp", catalog())
        self.assertEqual(owned, {"FILE_TRANSFER_PROTOCOL"})


class TestResolution(unittest.TestCase):
    def setUp(self):
        self.project = Project()
        self.capabilities = CapabilitySet()

    def resolve(self, profile):
        return resolve(self.project, profile, catalog(), self.capabilities)

    def test_defaults_disable_optional_capabilities(self):
        r = self.resolve(Profile(vehicle="V", name="flight"))
        self.assertTrue(r.states["HEARTBEAT"].enabled)
        self.assertTrue(r.states["ATTITUDE"].enabled)
        self.assertFalse(r.states["FILE_TRANSFER_PROTOCOL"].enabled)
        self.assertFalse(r.states["HIGHRES_IMU"].enabled)

    def test_capability_toggle_moves_every_owned_message(self):
        profile = Profile(vehicle="V", name="flight")
        profile.capabilities["telemetry_imu"] = True
        r = self.resolve(profile)
        self.assertTrue(r.states["HIGHRES_IMU"].enabled)
        self.assertTrue(r.states["VIBRATION"].enabled)

    def test_explicit_override_beats_capability(self):
        profile = Profile(vehicle="V", name="flight")
        profile.capabilities["telemetry_imu"] = False
        profile.messages["HIGHRES_IMU"] = MessageOverride(enabled=True)
        r = self.resolve(profile)
        self.assertTrue(r.states["HIGHRES_IMU"].enabled)
        self.assertEqual(r.states["HIGHRES_IMU"].reason,
                         "explicit override in profile")

    def test_required_messages_cannot_be_disabled(self):
        profile = Profile(vehicle="V", name="flight")
        profile.messages["HEARTBEAT"] = MessageOverride(enabled=False)
        r = self.resolve(profile)
        self.assertTrue(r.states["HEARTBEAT"].enabled)
        self.assertIn("required", r.states["HEARTBEAT"].reason)

    def test_required_capability_stays_on(self):
        profile = Profile(vehicle="V", name="flight")
        profile.capabilities["heartbeat"] = False
        r = self.resolve(profile)
        self.assertTrue(r.capability_states["heartbeat"])


class TestBandwidth(unittest.TestCase):
    def test_budget_sums_frames_not_payloads(self):
        profile = Profile(vehicle="V", name="flight")
        profile.link.bitrate = 115200
        profile.messages["ATTITUDE"] = MessageOverride(enabled=True, rate_hz=50)
        r = resolve(Project(), profile, catalog(), CapabilitySet())
        budget = compute_budget(r)
        attitude = next(s for s in budget.streams if s.name == "ATTITUDE")
        self.assertEqual(attitude.frame_bytes, 40)     # 28 payload + 12 header/CRC
        self.assertEqual(attitude.bits_per_second, 40 * 10 * 50)  # 20 kbps

    def test_over_budget_is_flagged(self):
        profile = Profile(vehicle="V", name="flight")
        profile.link.bitrate = 9600
        profile.messages["ATTITUDE"] = MessageOverride(enabled=True, rate_hz=50)
        r = resolve(Project(), profile, catalog(), CapabilitySet())
        budget = compute_budget(r)
        self.assertTrue(budget.over_budget)
        self.assertTrue(any("exceeds the link rate" in w for w in budget.warnings))


class TestCustomDialect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project = Project(root=os.path.join(self.tmp, "uav"))
        self.project.definitions_dir = DEFS
        self.project.dialect.path = os.path.join(self.tmp, "my_uav.xml")
        self.project.dialect.name = "my_uav"
        self.project.id_space.messages = (52700, 52799)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def message(self, name="UAV_TEST", message_id=52700, fields=None):
        return build_message(
            name, message_id, "A test message.",
            fields if fields is not None
            else [{"name": "value", "type": "float", "units": "m"}],
        )

    def test_add_then_remove(self):
        add_message(self.project, self.message(), catalog())
        self.assertEqual(
            [m.name for m in load_custom_dialect(self.project).messages],
            ["UAV_TEST"],
        )
        remove_message(self.project, "UAV_TEST")
        self.assertEqual(load_custom_dialect(self.project).messages, [])

    def test_standard_messages_cannot_be_removed(self):
        with self.assertRaises(DialectError):
            remove_message(self.project, "ATTITUDE")

    def test_duplicate_name_is_refused(self):
        errors = validate_message(self.project, catalog(),
                                  self.message(name="ATTITUDE"))
        self.assertTrue(any("already exists" in e for e in errors))

    def test_id_outside_range_is_refused(self):
        errors = validate_message(self.project, catalog(),
                                  self.message(message_id=30))
        self.assertTrue(any("outside the project id range" in e for e in errors))

    def test_id_collision_is_detected(self):
        # 42001 belongs to icarous.xml -- exactly the trap a naive custom
        # dialect falls into.
        check = check_id(self.project, catalog(), 42001)
        self.assertFalse(check.available)
        self.assertIn(("icarous", "ICAROUS_KINEMATIC_BANDS"), check.collisions)

    def test_payload_limit(self):
        fields = [{"name": f"f{i}", "type": "double"} for i in range(40)]
        errors = validate_message(self.project, catalog(),
                                  self.message(fields=fields))
        self.assertTrue(any("over the MAVLink" in e for e in errors))

    def test_extension_fields_must_come_last(self):
        fields = [
            {"name": "a", "type": "float", "extension": True},
            {"name": "b", "type": "float"},
        ]
        errors = validate_message(self.project, catalog(),
                                  self.message(fields=fields))
        self.assertTrue(any("must come last" in e for e in errors))

    def test_unknown_enum_reference_is_refused(self):
        fields = [{"name": "a", "type": "uint8_t", "enum": "NO_SUCH_ENUM"}]
        errors = validate_message(self.project, catalog(),
                                  self.message(fields=fields))
        self.assertTrue(any("unknown enum" in e for e in errors))

    def test_bad_names_are_refused(self):
        # build_message upper-cases for convenience, so go around it to check
        # the validator itself.
        from mavstudio.model import Field, Message
        bad = Message(id=52700, name="Bad Name", description="x",
                      fields=[Field(name="value", type="float")])
        errors = validate_message(self.project, catalog(), bad)
        self.assertTrue(any("UPPER_SNAKE_CASE" in e for e in errors))
        errors = validate_message(
            self.project, catalog(),
            self.message(fields=[{"name": "BadField", "type": "float"}]),
        )
        self.assertTrue(any("lower_snake_case" in e for e in errors))

    def test_written_xml_is_valid_and_reparses(self):
        add_message(self.project, self.message(), catalog())
        reparsed = parse_file(self.project.dialect.path)
        self.assertEqual(reparsed.messages[0].name, "UAV_TEST")
        self.assertEqual(reparsed.includes, ["common.xml"])


class TestFieldSpec(unittest.TestCase):
    def test_compact_forms(self):
        self.assertEqual(parse_field_spec("accel_x:float:m/s2"),
                         {"name": "accel_x", "type": "float", "units": "m/s2"})
        self.assertEqual(
            parse_field_spec("motor_id:uint8_t::UAV_MOTOR:Which motor"),
            {"name": "motor_id", "type": "uint8_t", "enum": "UAV_MOTOR",
             "description": "Which motor"},
        )

    def test_extra_separators_are_tolerated(self):
        parsed = parse_field_spec("t:uint64_t:us:::Timestamp.")
        self.assertEqual(parsed["description"], "Timestamp.")

    def test_missing_type_is_an_error(self):
        with self.assertRaises(DialectError):
            parse_field_spec("just_a_name")


class TestBuild(unittest.TestCase):
    def test_pruned_dialect_contains_only_enabled_messages(self):
        profile = Profile(vehicle="V", name="flight")
        r = resolve(Project(definitions_dir=DEFS), profile, catalog(),
                    CapabilitySet())
        tmp = tempfile.mkdtemp()
        try:
            project = Project(definitions_dir=DEFS)
            project.dialect.path = os.path.join(tmp, "none.xml")
            result = build_profile_dialect(
                project, catalog(), r,
                output_path=os.path.join(tmp, "out.xml"),
            )
            built = parse_file(result.dialect_path)
            names = {m.name for m in built.messages}
            self.assertIn("HEARTBEAT", names)
            self.assertNotIn("FILE_TRANSFER_PROTOCOL", names)
            self.assertEqual(len(built.messages), len(r.enabled_messages()))
            # Every enum a kept message points at must have come along.
            enums = {e.name for e in built.enums}
            for message in built.messages:
                for ref in message.enum_refs:
                    self.assertIn(ref, enums, f"{message.name} -> {ref}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_build_strips_superseded(self):
        # <superseded> is documentation, and older mavschema.xsd releases reject
        # it, so the build artefact must not carry it even though the catalog does.
        profile = Profile(vehicle="V", name="flight")
        profile.capabilities["telemetry_battery"] = True
        r = resolve(Project(definitions_dir=DEFS), profile, catalog(),
                    CapabilitySet())
        self.assertTrue(r.states["SMART_BATTERY_INFO"].enabled)
        tmp = tempfile.mkdtemp()
        try:
            project = Project(definitions_dir=DEFS)
            project.dialect.path = os.path.join(tmp, "none.xml")
            result = build_profile_dialect(
                project, catalog(), r, output_path=os.path.join(tmp, "out.xml")
            )
            with open(result.dialect_path, encoding="utf-8") as handle:
                self.assertNotIn("<superseded", handle.read())
            # ...and the catalog still has it, untouched.
            self.assertIsNotNone(catalog().message("SMART_BATTERY_INFO").superseded)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_build_filename_is_a_c_identifier(self):
        # mavgen turns the filename into a preprocessor macro.
        self.assertEqual(ident("SWAN-H200"), "swan_h200")
        self.assertEqual(ident("my uav!!"), "my_uav")
        self.assertEqual(ident("9lives"), "_9lives")
        self.assertEqual(slug("SWAN-H200"), "swan-h200")


class TestMosa(unittest.TestCase):
    def test_semver_same_major_only(self):
        self.assertTrue(mosa.satisfies("1.3.0", "1.2.0"))
        self.assertFalse(mosa.satisfies("1.2.0", "1.3.0"))
        self.assertFalse(mosa.satisfies("2.0.0", "1.3.0"))

    def test_data_model_refs(self):
        self.assertEqual(mosa.split_ref("ATTITUDE"), ("mavlink", "ATTITUDE"))
        self.assertEqual(mosa.split_ref("dds:TargetTrack"), ("dds", "TargetTrack"))
        # An unknown prefix is a name, not a model.
        self.assertEqual(mosa.split_ref("FOO:BAR"), ("mavlink", "FOO:BAR"))
        self.assertEqual(mosa.mavlink_refs(["A", "dds:B"]), ["A"])
        self.assertEqual(mosa.external_refs(["A", "dds:B"]), [("dds", "B")])

    def contract(self):
        return mosa.InterfaceContract(
            name="PROP.MON", version="1.2.0",
            providers=["ESC"], consumers=["FC"],
            required_messages=["UAV_MOTOR_STATUS", "dds:Telemetry"],
            commands=["MAV_CMD_UAV_MOTOR_TEST"],
            aspects={"power": "28VDC", "timing": ""},
        )

    def test_module_satisfying_everything_is_compatible(self):
        manifest = mosa.ModuleManifest(
            name="ESC", version="1.0.0",
            interfaces={"PROP.MON": "1.2.0"},
            tx=["UAV_MOTOR_STATUS"], commands=["MAV_CMD_UAV_MOTOR_TEST"],
            aspects={"power": "28VDC", "timing": "PTP"},
        )
        checks = mosa.check_module(manifest, {"PROP.MON": self.contract()})
        self.assertTrue(checks[0].compatible, checks[0].notes)

    def test_missing_aspect_breaks_conformance(self):
        manifest = mosa.ModuleManifest(
            name="ESC", version="1.0.0", interfaces={"PROP.MON": "1.2.0"},
            tx=["UAV_MOTOR_STATUS"], commands=["MAV_CMD_UAV_MOTOR_TEST"],
            aspects={"power": "28VDC"},
        )
        checks = mosa.check_module(manifest, {"PROP.MON": self.contract()})
        self.assertFalse(checks[0].compatible)

    def test_swap_scores_messages_commands_and_aspects(self):
        interfaces = {"PROP.MON": self.contract()}
        current = mosa.ModuleManifest(
            name="A", interfaces={"PROP.MON": "1.2.0"},
            tx=["UAV_MOTOR_STATUS"], commands=["MAV_CMD_UAV_MOTOR_TEST"],
            aspects={"power": "28VDC", "timing": "PTP"},
        )
        replacement = mosa.ModuleManifest(
            name="B", interfaces={"PROP.MON": "1.2.0"},
            tx=["UAV_MOTOR_STATUS"], commands=[],
            aspects={"power": "28VDC"},
        )
        reports = mosa.compare_modules(current, replacement, interfaces)
        report = reports[0]
        # 4 checked items (1 mavlink message, 1 command, 2 aspects), 2 fail.
        self.assertAlmostEqual(report.score, 0.5)
        self.assertEqual(report.verdict, "partial")
        self.assertEqual(report.unverified, ["dds:Telemetry"])

    def test_swap_to_a_module_without_the_interface_scores_zero(self):
        current = mosa.ModuleManifest(name="A", interfaces={"PROP.MON": "1.2.0"})
        replacement = mosa.ModuleManifest(name="B", interfaces={})
        reports = mosa.compare_modules(current, replacement,
                                       {"PROP.MON": self.contract()})
        self.assertEqual(reports[0].verdict, "incompatible")
        self.assertEqual(mosa.swap_score(reports), 0.0)

    def test_change_classification(self):
        before = mosa.InterfaceContract(name="I", version="1.1.0",
                                        required_messages=["A", "B"])
        after = mosa.InterfaceContract(name="I", version="1.1.0",
                                       required_messages=["A"])
        level, reasons = mosa.classify_change(before, after)
        self.assertEqual(level, "major")
        self.assertEqual(mosa.expected_version(before, level), "2.0.0")
        after2 = mosa.InterfaceContract(name="I", version="1.1.0",
                                        required_messages=["A", "B"],
                                        optional_messages=["C"])
        level2, _ = mosa.classify_change(before, after2)
        self.assertEqual(level2, "minor")
        self.assertEqual(mosa.expected_version(before, level2), "1.2.0")


class TestValidateAndIcd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project = Project(root=os.path.join(self.tmp, "uav"))
        self.project.definitions_dir = DEFS
        self.project.dialect.path = os.path.join(self.tmp, "my_uav.xml")
        self.profile = Profile(vehicle="V", name="flight")
        self.profile.messages["ATTITUDE"] = MessageOverride(
            enabled=True, rate_hz=50, tx=["FC"], rx=["GCS"]
        )
        self.resolution = resolve(self.project, self.profile, catalog(),
                                  CapabilitySet())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_project_has_no_errors(self):
        report = validate_all(self.project, catalog(), CapabilitySet(),
                              self.resolution)
        self.assertEqual(report.errors, [i.message for i in []] or report.errors)
        self.assertTrue(report.ok, [i.message for i in report.errors])

    def test_profile_override_on_unknown_message_is_an_error(self):
        self.profile.messages["NOT_A_MESSAGE"] = MessageOverride(enabled=True)
        resolution = resolve(self.project, self.profile, catalog(),
                             CapabilitySet())
        report = validate_all(self.project, catalog(), CapabilitySet(), resolution)
        self.assertTrue(
            any("does not exist" in i.message for i in report.errors)
        )

    def test_icd_contains_the_enabled_set(self):
        markdown = generate_markdown(self.project, catalog(), CapabilitySet(),
                                     self.resolution)
        self.assertIn("Interface Control Document", markdown)
        self.assertIn("`ATTITUDE`", markdown)
        self.assertIn("Requirement traceability", markdown)
        self.assertNotIn("`FILE_TRANSFER_PROTOCOL`", markdown)


if __name__ == "__main__":
    unittest.main()
