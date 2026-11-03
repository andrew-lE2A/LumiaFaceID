"""Catch the real vendor pinctrl layout regression in compiled DTBs."""
import copy
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import repack_boot as boot
import validate_iris_dtbs as validator
sys.path.pop(0)


class IrisDtbTests(unittest.TestCase):
    def test_original_failed_build_is_rejected_for_wrong_pinctrl_parent(self):
        data = (ROOT / 'kernel/builds/iris-id-01/boards.dtb').read_bytes()
        with self.assertRaisesRegex(ValueError, 'not a direct child'):
            validator.validate(data)

    def test_corrected_build_resolves_controller_and_resources(self):
        data = (ROOT / 'kernel/builds/iris-id-02/boards.dtb').read_bytes()
        report = validator.validate(data)
        self.assertEqual(report['pins'], [14, 102])
        self.assertFalse(report['automatic_identification'])

    def test_wrong_reset_supply_and_default_state_are_rejected(self):
        data = (ROOT / 'kernel/builds/iris-id-02/boards.dtb').read_bytes()
        first = struct.unpack_from('>I', data, 4)[0]
        original = boot.dtb_nodes(data[first:])
        gpio, _, flags = struct.unpack('>III', original[validator.DEVICE]['reset-gpios'])
        for field, value in (('reset-gpios', struct.pack('>III', gpio, 106, flags)),
                             ('vana-supply', original[validator.DEVICE]['core-supply']),
                             ('pinctrl-names', b'default\0sleep\0')):
            with self.subTest(field=field):
                nodes = copy.deepcopy(original)
                nodes[validator.DEVICE][field] = value
                with self.assertRaises(ValueError):
                    validator.validate_nodes(nodes)


if __name__ == '__main__':
    unittest.main()
