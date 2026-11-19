"""Verify real release packaging round-trips through the production validator."""

import hashlib
import json
import runpy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_release_is_accepted_by_existing_updater_allowlist(self):
        """Versions through 1.3.26 allow new build resources but reject new host paths."""
        legacy_required = {'build/manifest.json', 'build/background.js', 'build/popup.js',
                           'build/popup.html', 'build/popup.css', 'build/release-info.json',
                           'src/host/sing_host.py', 'src/host/release_tools.py', 'install.sh'}
        package = runpy.run_path(str(ROOT / 'scripts/package_release.py'))['package_release']
        version = json.loads((ROOT / 'package.json').read_text())['version']
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package(ROOT, version, directory)
            staging = directory / 'staging'
            staging.mkdir()
            with patch.dict(release_tools.REQUIRED, {'extension': legacy_required}):
                release_tools.unpack((directory / 'sing-vpn-macos.tar.gz').read_bytes(), staging,
                                     'extension', version)
            self.assertTrue((staging / 'build/homebrew-tools.sh').is_file())

    def test_terminal_installer_migrates_the_v1_3_28_host_layout(self):
        """The v1.3.28 allowlist needs its existing copied-command repair route once."""
        package = runpy.run_path(str(ROOT / 'scripts/package_release.py'))['package_release']
        version = json.loads((ROOT / 'package.json').read_text())['version']
        legacy_required = (release_tools.REQUIRED['extension'] - {'build/homebrew-tools.sh'}) | {
            'src/host/homebrew_tools.sh'}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package(ROOT, version, directory)
            contents = (directory / 'sing-vpn-macos.tar.gz').read_bytes()
            rejected = directory / 'legacy-attempt'
            rejected.mkdir()
            with patch.dict(release_tools.REQUIRED, {'extension': legacy_required}):
                with self.assertRaisesRegex(ValueError, 'incomplete release archive'):
                    release_tools.unpack(contents, rejected, 'extension', version)
            source = directory / 'source'
            source.mkdir()
            release_tools.unpack(contents, source, 'extension', version)
            home = directory / 'home'
            with patch.object(release_tools, 'HOME', home):
                target = release_tools.destination('extension')
                shutil.copytree(source, target)
                (target / 'build/homebrew-tools.sh').rename(target / 'src/host/homebrew_tools.sh')
                manifest = json.loads((target / 'release.json').read_text())
                digest = manifest['files'].pop('build/homebrew-tools.sh')
                manifest['files']['src/host/homebrew_tools.sh'] = digest
                (target / 'release.json').write_text(json.dumps(manifest))
                sentinel = home / '.config/sing-box/custom.txt'
                sentinel.parent.mkdir(parents=True)
                sentinel.write_text('fake user configuration')
                release_tools.install_local_extension(source)
                self.assertTrue((target / 'build/homebrew-tools.sh').is_file())
                self.assertFalse((target / 'src/host/homebrew_tools.sh').exists())
                self.assertEqual(sentinel.read_text(), 'fake user configuration')
