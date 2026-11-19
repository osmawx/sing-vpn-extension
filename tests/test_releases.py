"""Verify repository-free release installation with isolated files and fake downloads."""

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import release_tools


class ReleaseInstallTest(unittest.TestCase):
    """Protect installed code and user data across release updates."""

    def setUp(self):
        """Create isolated HOME and a tiny valid release archive."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.home_patch = patch.object(release_tools, 'HOME', self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def archive(self, version='1.3.1', unsafe=False):
        """Build a bounded fake extension release with valid file hashes."""
        files = {name: b'test code\n' for name in release_tools.REQUIRED['extension']}
        files['build/manifest.json'] = json.dumps({'version': version}).encode()
        files['build/release-info.json'] = b'{"managed":true}'
        manifest = {'version': version, 'component': 'extension', 'files': {
            name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        files['release.json'] = json.dumps(manifest).encode()
        if unsafe:
            files['../outside'] = b'unsafe'
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def install(self, data=None, checksum=None):
        """Install a fake official release without network access."""
        data = data or self.archive()
        info = {'version': '1.3.1', 'url': 'https://github.com/osmawx/sing-vpn-extension/releases/download/v1.3.1/sing-vpn-macos.tar.gz',
                'checksumUrl': 'https://github.com/osmawx/sing-vpn-extension/releases/download/v1.3.1/sing-vpn-macos.tar.gz.sha256'}
        digest = checksum or hashlib.sha256(data).hexdigest()
        with patch.object(release_tools, 'latest', return_value=info), patch.object(
                release_tools, 'download', side_effect=[data, (digest + '  sing-vpn-macos.tar.gz\n').encode()]):
            return release_tools.deploy('extension')

    def test_installs_without_git_or_npm_and_preserves_configuration(self):
        """A release installs into managed runtime without touching credentials."""
        config = self.home / '.config/sing-box/custom.txt'
        config.parent.mkdir(parents=True)
        config.write_text('fake credentials')
        with patch('subprocess.run') as run:
            result = self.install()
        self.assertTrue(result['updated'])
        self.assertEqual(release_tools.installed_version('extension'), '1.3.1')
        self.assertEqual(config.read_text(), 'fake credentials')
        run.assert_not_called()

    def test_bad_checksum_keeps_current_installation(self):
        """Checksum failures never replace installed code."""
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.install(checksum='0' * 64)
        self.assertFalse(release_tools.destination('extension').exists())

    def test_rejects_traversal_before_writing_files(self):
        """Archive entries cannot escape staging or create links."""
        with self.assertRaises(ValueError):
            self.install(self.archive(unsafe=True))
        self.assertFalse((self.home / 'outside').exists())

    def test_refuses_modified_managed_code(self):
        """Local changes are preserved instead of silently overwritten."""
        self.install()
        code = release_tools.destination('extension') / 'src/host/sing_host.py'
        code.write_text('local changes')
        with self.assertRaisesRegex(ValueError, 'modified'):
            self.install()
        self.assertEqual(code.read_text(), 'local changes')

    def test_failed_swap_restores_previous_directory(self):
        """A failed directory replacement restores the prior release."""
        target = release_tools.destination('extension')
        target.parent.mkdir(parents=True)
        target.mkdir()
        (target / 'marker').write_text('previous')
        source = target.parent / 'staged'
        source.mkdir()
        original_replace = os.replace

        def fail_new_directory(first, second):
            """Fail only activation, allowing the rollback rename."""
            if Path(first) == source:
                raise OSError('fake activation failure')
            return original_replace(first, second)

        with patch.object(release_tools.os, 'replace', side_effect=fail_new_directory):
            with self.assertRaises(OSError):
                release_tools.activate(source, target)
        self.assertEqual((target / 'marker').read_text(), 'previous')

    def test_metadata_rejects_foreign_asset_url(self):
        """Release assets must belong to the fixed official repository."""
        with patch.object(release_tools, 'download', return_value=json.dumps({
            'tag_name': 'v1.3.1', 'assets': [
                {'name': 'sing-vpn-macos.tar.gz', 'browser_download_url': 'https://evil.invalid/code'},
                {'name': 'sing-vpn-macos.tar.gz.sha256', 'browser_download_url': 'https://evil.invalid/hash'},
            ]}).encode()):
            with self.assertRaises(ValueError):
                release_tools.latest('extension')

    def sing_code(self):
        """Create fake standalone CLI files for installation tests."""
        root = self.home / 'code'
        for name in release_tools.REQUIRED['sing']:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('fake code')
        return {'path': str(root), 'version': '1.0.1', 'updated': False}

    def test_fresh_sing_install_creates_private_writable_configuration(self):
        """First-run proxy imports can write files without a preexisting config directory."""
        with patch.object(release_tools, 'deploy', return_value=self.sing_code()):
            release_tools.install_sing()
        configuration = self.home / '.config/sing-box'
        self.assertEqual(configuration.stat().st_mode & 0o777, 0o700)
        (configuration / 'custom.txt').write_text('http://example.invalid:80#Fake')
        self.assertTrue((configuration / 'custom.txt').is_file())

    def test_sing_migration_preserves_existing_settings(self):
        """Legacy names migrate only when new names do not exist."""
        configuration = self.home / '.config/sing-box'
        configuration.mkdir(parents=True)
        (configuration / 'blanc.sub').write_text('fake old subscription')
        (configuration / 'blanc.current').write_text('old selection')
        (configuration / 'sing.current').write_text('new selection')
        with patch.object(release_tools, 'deploy', return_value=self.sing_code()):
            release_tools.install_sing()
        self.assertEqual((configuration / 'sing.sub').read_text(), 'fake old subscription')
        self.assertEqual((configuration / 'sing.current').read_text(), 'new selection')
        self.assertEqual((configuration / 'blanc.current').read_text(), 'old selection')

    def test_failed_link_install_restores_migration_and_old_links(self):
        """A destination directory cannot destroy settings or previous CLI files."""
        configuration = self.home / '.config/sing-box'
        configuration.mkdir(parents=True)
        (configuration / 'blanc.sub').write_text('fake old subscription')
        conflict = self.home / '.local/share/sing/select.py'
        conflict.mkdir(parents=True)
        with patch.object(release_tools, 'deploy', return_value=self.sing_code()):
            with self.assertRaises(ValueError):
                release_tools.install_sing()
        self.assertEqual((configuration / 'blanc.sub').read_text(), 'fake old subscription')
        self.assertFalse((configuration / 'sing.sub').exists())
        self.assertTrue(conflict.is_dir())
