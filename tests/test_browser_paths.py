"""Discover Chromium browser data roots without reading or logging user credentials."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/host'))
import release_tools


class BrowserPathsTest(unittest.TestCase):
    """Use only isolated browser metadata and fake profile directories."""

    def setUp(self):
        """Create a temporary Application Support tree."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.support = self.home / 'Library/Application Support'
        self.support.mkdir(parents=True)
        patched = patch.object(release_tools, 'HOME', self.home)
        patched.start()
        self.addCleanup(patched.stop)

    def test_known_browser_families_include_dia_arc_edge_and_opera(self):
        """Known roots work even before a first profile finishes initialization."""
        names = ['Dia', 'Dia/User Data', 'Arc', 'Arc/User Data', 'Aside', 'Google/Chrome',
                 'Chromium', 'Microsoft Edge', 'BraveSoftware/Brave-Browser',
                 'Vivaldi', 'com.operasoftware.Opera', 'Yandex/YandexBrowser']
        for name in names:
            (self.support / name).mkdir(parents=True, exist_ok=True)
        discovered = release_tools.browser_user_data_dirs()
        for name in names:
            self.assertIn(self.support / name, discovered)

    def test_unknown_chromium_brand_is_detected_from_profile_metadata(self):
        """New vendors do not require a hardcoded browser-name update."""
        browser = self.support / 'Future Vendor/Future Browser/User Data'
        browser.mkdir(parents=True)
        (browser / 'Local State').write_text(json.dumps({'profile': {'info_cache': {}}}))
        self.assertIn(browser, release_tools.browser_user_data_dirs())

    def test_unrelated_application_or_broken_state_is_ignored(self):
        """Do not add host registrations to arbitrary app directories."""
        unrelated = self.support / 'Other App'
        unrelated.mkdir()
        (unrelated / 'Local State').write_text('{"browser":{}}')
        broken = self.support / 'Broken App'
        broken.mkdir()
        (broken / 'Local State').write_text('{ invalid')
        self.assertNotIn(unrelated, release_tools.browser_user_data_dirs())
        self.assertNotIn(broken, release_tools.browser_user_data_dirs())

    def test_cli_emits_null_delimited_host_directories(self):
        """Spaces and quotes in paths survive the shell installer boundary."""
        browser = self.support / 'Custom Browser "Quoted"'
        browser.mkdir()
        (browser / 'Local State').write_text('{"profile":{"info_cache":{}}}')
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'src/host/release_tools.py'), 'browser-host-dirs'],
                                env={**os.environ, 'HOME': str(self.home)}, capture_output=True, check=True, timeout=10)
        self.assertIn(os.fsencode(str(browser / 'NativeMessagingHosts')), result.stdout.split(b'\0'))
