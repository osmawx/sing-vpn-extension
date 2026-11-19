"""Test the downloadable macOS release installer without network or real installation."""

import hashlib
import gzip
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]


class DownloadableInstallerTest(unittest.TestCase):
    """Verify executable packaging and checksum-gated installation."""

    def test_archive_contains_executable_launcher(self):
        """Archive Utility extracts an executable command matching the source."""
        contents = (PROJECT_DIR / 'build/sing-installer.tar.gz').read_bytes()
        self.assertEqual(contents[:10], bytes([31, 139, 8, 0, 0, 0, 0, 0, 0, 255]))
        self.assertTrue(gzip.decompress(contents))
        with tarfile.open(PROJECT_DIR / 'build/sing-installer.tar.gz') as archive:
            self.assertEqual(archive.getnames(), ['Install Sing.command'])
            member = archive.getmembers()[0]
            self.assertTrue(member.isfile())
            self.assertEqual(member.mode, 0o755)
            self.assertEqual(archive.extractfile(member).read(),
                             (PROJECT_DIR / 'src/installer/Install Sing.command').read_bytes())

    def run_launcher(self, fail_download=False, bad_checksum=False):
        """Run a launcher with fake curl, HOME and installation script."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / 'commands'
            commands.mkdir()
            contents = b'#!/bin/bash\n[[ "$1" == --prebuilt ]]\nprintf installed > "$HOME/result"\n'
            archive_path = root / 'fake-release.tar.gz'
            with tarfile.open(archive_path, mode='w:gz') as archive:
                member = tarfile.TarInfo('install.sh')
                member.size = len(contents)
                archive.addfile(member, io.BytesIO(contents))
            fake_curl = commands / 'curl'
            fake_curl.write_text('''#!/bin/bash
set -eu
if [[ "${FAIL_DOWNLOAD:-}" == 1 ]]; then exit 42; fi
target="${@: -1}"
if [[ "$target" == */checksum ]]; then
  printf '%s  sing-vpn-macos.tar.gz\\n' "$FAKE_CHECKSUM" > "$target"
else
  cp "$FAKE_ARCHIVE" "$target"
fi
''')
            fake_curl.chmod(0o755)
            for name in ('git', 'npm', 'node'):
                command = commands / name
                command.write_text('#!/bin/sh\nexit 99\n')
                command.chmod(0o755)
            sentinel = root / '.config/sing-box/custom.txt'
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text('fake credentials')
            result = subprocess.run(
                ['bash', str(PROJECT_DIR / 'src/installer/Install Sing.command')],
                env={**os.environ, 'HOME': directory, 'PATH': f'{commands}:/usr/bin:/bin',
                     'FAIL_DOWNLOAD': '1' if fail_download else '0', 'FAKE_ARCHIVE': str(archive_path),
                     'FAKE_CHECKSUM': '0' * 64 if bad_checksum else hashlib.sha256(archive_path.read_bytes()).hexdigest()},
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(sentinel.read_text(), 'fake credentials')
            return result, (root / 'result').exists()

    def test_installs_prebuilt_release_without_git_or_npm(self):
        """A verified package starts installation and gives the stable load path."""
        result, installed = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(installed)
        self.assertIn('Load unpacked', result.stdout)
        self.assertIn('/.local/share/sing-vpn/runtime/build', result.stdout)

    def test_checksum_failure_never_executes_downloaded_code(self):
        """Corrupt downloads cannot run the installation script."""
        result, installed = self.run_launcher(bad_checksum=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(installed)

    def test_download_failure_stops_install_and_reports_error(self):
        """Failed downloads never run an installer or report success."""
        result, installed = self.run_launcher(fail_download=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(installed)
        self.assertIn('Installation failed', result.stdout)
