"""Protect the installed extension folder during repository-free updates."""

import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import release_tools


class InstalledLocationTest(unittest.TestCase):
    """Use fake browser profiles, keys and extension folders only."""

    def setUp(self):
        """Create a fake HOME with an old unpacked copy and a verified runtime build."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.key = base64.b64encode(b'fake-public-key-for-tests').decode()
        self.identifier = ''.join(chr(97 + int(digit, 16)) for digit in
                                  hashlib.sha256(b'fake-public-key-for-tests').hexdigest()[:32])
        for name, value in [('HOME', self.home), ('EXTENSION_ID', self.identifier)]:
            patched = patch.object(release_tools, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.installed = self.home / 'developer project/build'
        self.runtime = self.home / 'runtime/build'
        self.make_extension(self.installed, '1.3.0', 'old popup')
        self.make_extension(self.runtime, '1.3.30', 'new popup')
        self.register('Aside', self.installed)

    def make_extension(self, directory, version, text):
        """Create a minimal unpacked extension with a fake stable identity."""
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'manifest.json').write_text(json.dumps({
            'manifest_version': 3, 'key': self.key, 'name': 'Fake Sing', 'version': version}))
        (directory / 'popup.js').write_text(text)

    def register(self, browser, directory):
        """Write just the fake extension registration, with no user credentials."""
        preferences = self.home / 'Library/Application Support' / browser / 'Default/Secure Preferences'
        preferences.parent.mkdir(parents=True, exist_ok=True)
        preferences.write_text(json.dumps({'extensions': {'settings': {
            self.identifier: {'path': str(directory)}}}}))

    def test_discovers_and_deduplicates_loaded_folder(self):
        """Two browsers using one folder produce one update destination."""
        self.register('Arc/User Data', self.installed)
        self.assertEqual(release_tools.installed_extension_paths(), [self.installed.resolve()])

    def test_discovers_dia_guid_profile_and_opera_root_profile(self):
        """Non-Default profile names and root-level Opera profiles are supported."""
        for browser, profile in [('Dia/User Data', 'fake-guid-profile'), ('com.operasoftware.Opera', '')]:
            target = self.home / (browser.replace('/', '-') + '-extension')
            self.make_extension(target, '1.3.0', 'fake popup')
            preferences = self.home / 'Library/Application Support' / browser / profile / 'Secure Preferences'
            preferences.parent.mkdir(parents=True, exist_ok=True)
            preferences.write_text(json.dumps({'extensions': {'settings': {
                self.identifier: {'path': str(target)}}}}))
            self.assertIn(target.resolve(), release_tools.installed_extension_paths())

    def test_discovers_unknown_single_profile_chromium_with_sing_installed(self):
        """A fork without info_cache is recognized from the extension it actually loads."""
        root = self.home / 'Library/Application Support/New Brand'
        root.mkdir()
        target = self.home / 'new-brand-extension'
        self.make_extension(target, '1.3.0', 'fake popup')
        (root / 'Preferences').write_text(json.dumps({'extensions': {'settings': {
            self.identifier: {'path': str(target)}}}}))
        self.assertIn(target.resolve(), release_tools.installed_extension_paths())

    def test_ignores_registration_with_another_extension_key(self):
        """A forged registration cannot authorize updating an unrelated directory."""
        manifest = self.installed / 'manifest.json'
        data = json.loads(manifest.read_text())
        data['key'] = base64.b64encode(b'other fake key').decode()
        manifest.write_text(json.dumps(data))
        self.assertEqual(release_tools.installed_extension_paths(), [])

    def test_updates_in_place_and_keeps_source_and_original_build(self):
        """The registered path stays fixed; source files and prior build are preserved."""
        source = self.installed.parent / 'source.txt'
        source.write_text('developer changes')
        result = release_tools.update_installed_build(self.runtime, self.installed)
        self.assertTrue(result['updated'])
        self.assertEqual((self.installed / 'popup.js').read_text(), 'new popup')
        self.assertEqual((Path(result['backup']) / 'popup.js').read_text(), 'old popup')
        self.assertEqual(source.read_text(), 'developer changes')
        self.assertEqual(release_tools.installed_extension_paths(), [self.installed.resolve()])

    def test_rejects_unregistered_target_without_changing_it(self):
        """The native caller cannot supply an arbitrary filesystem destination."""
        other = self.home / 'unregistered'
        self.make_extension(other, '1.3.0', 'keep')
        with self.assertRaises(ValueError):
            release_tools.update_installed_build(self.runtime, other)
        self.assertEqual((other / 'popup.js').read_text(), 'keep')

    def test_same_build_is_a_noop_and_cannot_become_its_own_backup(self):
        """Updating a managed folder from itself must not move or remove it."""
        result = release_tools.update_installed_build(self.installed, self.installed)
        self.assertFalse(result['updated'])
        self.assertEqual((self.installed / 'popup.js').read_text(), 'old popup')

    def test_failed_swap_restores_original_loaded_folder(self):
        """Failed activation leaves the browser's original directory available."""
        original = os.replace

        def fail_activation(source, target):
            """Reject only replacement of the final folder, allowing rollback."""
            if Path(target) == self.installed and '.sing-vpn-update-' in str(source):
                raise OSError('fake write failure')
            return original(source, target)

        with patch.object(release_tools.os, 'replace', side_effect=fail_activation):
            with self.assertRaises(OSError):
                release_tools.update_installed_build(self.runtime, self.installed)
        self.assertEqual((self.installed / 'popup.js').read_text(), 'old popup')
