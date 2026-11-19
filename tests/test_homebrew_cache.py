"""Repair only Homebrew's verified, quarantined portable Ruby cache in an isolated HOME."""

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HomebrewCacheTest(unittest.TestCase):
    """Use fake Homebrew metadata and commands without touching installed software."""

    def setUp(self):
        """Create fake Homebrew, its exact vendor archive and a controlled xattr command."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.prefix = self.home / 'brew prefix'
        vendor = self.prefix / 'Library/Homebrew/vendor'
        vendor.mkdir(parents=True)
        (vendor / 'portable-ruby-version').write_text('4.0.10\n')
        digest = hashlib.sha256(b'fake verified ruby archive').hexdigest()
        for architecture in ('arm64', 'x86_64'):
            (vendor / ('portable-ruby-' + architecture + '-darwin')).write_text(
                'ruby_TAG=arm64_big_sur\nruby_SHA=' + digest + '\n')
        self.cache = self.home / 'Library/Caches/Homebrew'
        self.cache.mkdir(parents=True)
        self.archive = self.cache / 'portable-ruby-4.0.10.arm64_big_sur.bottle.tar.gz'
        self.archive.write_bytes(b'fake verified ruby archive')
        self.binaries = self.home / 'commands'
        self.binaries.mkdir()
        self.write_command('xattr', '#!/bin/bash\n[[ "${QUARANTINED:-1}" == 1 ]]\n')
        self.brew = self.prefix / 'bin/brew'
        self.brew.parent.mkdir()
        self.brew.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$HOME/brew-called"\n')
        self.brew.chmod(0o755)
        self.environment = {**os.environ, 'HOME': str(self.home), 'PATH': str(self.binaries) + ':/usr/bin:/bin'}
        self.environment.pop('HOMEBREW_CACHE', None)

    def write_command(self, name, contents):
        """Create a controlled command stub in the isolated PATH."""
        command = self.binaries / name
        command.write_text(contents)
        command.chmod(0o755)

    def run_helper(self):
        """Run the shared preflight and fake upgrade with the real system Bash."""
        return subprocess.run(['/bin/bash', str(ROOT / 'src/host/homebrew_tools.sh'), str(self.brew),
                               'upgrade', 'sing-box'], env=self.environment, capture_output=True,
                              text=True, timeout=10, check=False)

    def test_quarantined_verified_archive_is_preserved_before_brew_runs(self):
        """Homebrew must fetch a clean archive instead of reusing browser quarantine."""
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.archive.exists())
        backups = list(self.cache.glob(self.archive.name + '.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'fake verified ruby archive')
        self.assertEqual((self.home / 'brew-called').read_text(), 'upgrade sing-box\n')

    def test_clean_cache_is_unchanged(self):
        """Normal Homebrew caches incur no file replacements."""
        self.environment['QUARANTINED'] = '0'
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.archive.exists())
        self.assertEqual(list(self.cache.glob('*.backup-*')), [])

    def test_checksum_mismatch_stops_before_brew_or_cache_changes(self):
        """Never treat an unverified cached archive as trusted software."""
        self.archive.write_bytes(b'corrupt archive')
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.archive.read_bytes(), b'corrupt archive')
        self.assertFalse((self.home / 'brew-called').exists())

    def test_unrelated_cached_packages_and_symlinks_are_untouched(self):
        """Only the exact vendor archive may be renamed; symlinks are never followed."""
        other = self.cache / 'unrelated-package.tar.gz'
        other.write_bytes(b'keep')
        self.archive.unlink()
        self.archive.symlink_to(other)
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.archive.is_symlink())
        self.assertEqual(other.read_bytes(), b'keep')

    def test_symlinked_brew_uses_repository_metadata(self):
        """Intel Homebrew keeps its repository below the installation prefix."""
        repository = self.prefix / 'Homebrew'
        repository.mkdir()
        (self.prefix / 'Library').rename(repository / 'Library')
        (repository / 'bin').mkdir()
        real_brew = repository / 'bin/brew'
        self.brew.rename(real_brew)
        self.brew.symlink_to('../Homebrew/bin/brew')
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.archive.exists())
        self.assertEqual(len(list(self.cache.glob('*.backup-*'))), 1)
