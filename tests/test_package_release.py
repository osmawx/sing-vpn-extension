"""Verify real release packaging round-trips through the production validator."""

import hashlib
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/host'))
import release_tools


class PackageReleaseTest(unittest.TestCase):
    """Ensure shipped artifacts contain ready-to-run code and consistent versions."""

    def test_packaged_build_is_deterministic_and_installable(self):
        """Use real build files, checksum manifest and archive validation."""
        package = runpy.run_path(str(ROOT / 'scripts/package_release.py'))['package_release']
        version = json.loads((ROOT / 'package.json').read_text())['version']
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / 'output'
            package(ROOT, version, output)
            archive = (output / 'sing-vpn-macos.tar.gz').read_bytes()
            self.assertEqual((output / 'sing-vpn-macos.tar.gz.sha256').read_text().split()[0],
                             hashlib.sha256(archive).hexdigest())
            package(ROOT, version, output)
            self.assertEqual((output / 'sing-vpn-macos.tar.gz').read_bytes(), archive)
            staging = directory / 'staging'
            staging.mkdir()
            release_tools.unpack(archive, staging, 'extension', version)
            self.assertTrue(json.loads((staging / 'build/release-info.json').read_text())['managed'])
            self.assertFalse((staging / '.git').exists())
            self.assertFalse((staging / 'node_modules').exists())
