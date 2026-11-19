"""Regression tests for bounded, private diagnostic log exports."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import sing_host


class LogExportTest(unittest.TestCase):
    """Exercise log export without accessing real user files."""

    def setUp(self):
        """Create isolated logs and configuration."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = self.root / 'sing.log'
        self.config = self.root / 'config'
        self.config.mkdir()
        self.log_patch = patch.object(sing_host, 'LOG_FILE', str(self.log))
        self.config_patch = patch.object(sing_host, 'CONFIG_DIR', str(self.config))
        self.log_patch.start()
        self.config_patch.start()
        self.addCleanup(self.log_patch.stop)
        self.addCleanup(self.config_patch.stop)

    def test_exports_without_sing_and_redacts_credentials(self):
        """Remove active secrets, URLs, UUIDs and labelled credentials."""
        (self.config / 'sing.json').write_text(json.dumps({'outbounds': [
            {'password': 'fake-secret', 'uuid': '11111111-2222-3333-4444-555555555555'},
        ]}))
        self.log.write_text('ERROR dial timeout fake-secret\nhttps://user:pass@example.test/sub?token=abc\n'
                            'password=other-secret\n11111111-2222-3333-4444-555555555555\n')
        with patch.object(sing_host.os, 'access', return_value=False):
            result = sing_host.dispatch({'action': 'export_logs'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'available')
        self.assertIn('ERROR dial timeout', result['text'])
        for secret in ['fake-secret', 'other-secret', 'https://', '11111111-2222-3333-4444-555555555555']:
            self.assertNotIn(secret, result['text'])

    def test_missing_log_is_not_an_error(self):
        """A fresh install has no native log yet."""
        self.assertEqual(sing_host.dispatch({'action': 'export_logs'}),
                         {'ok': True, 'status': 'missing', 'text': '', 'truncated': False})

    def test_tail_is_bounded_and_skips_partial_line(self):
        """Export only a bounded tail, without a cut credential prefix."""
        self.log.write_bytes(b'x' * (sing_host.MAX_LOG_BYTES + 10) + b'\nERROR latest\n')
        result = sing_host.dispatch({'action': 'export_logs'})
        self.assertTrue(result['truncated'])
        self.assertEqual(result['text'], 'ERROR latest\n')

    def test_symlink_and_fifo_are_not_read(self):
        """Never export another file or block on a named pipe."""
        target = self.root / 'private'
        target.write_text('private content')
        self.log.symlink_to(target)
        self.assertEqual(sing_host.dispatch({'action': 'export_logs'})['status'], 'unavailable')
        self.log.unlink()
        os.mkfifo(self.log)
        self.assertEqual(sing_host.dispatch({'action': 'export_logs'})['status'], 'unavailable')

    def test_invalid_configuration_omits_log(self):
        """Fail closed when known secrets cannot be collected."""
        self.log.write_text('ERROR fake-secret')
        (self.config / 'sing.json').write_text('{ invalid')
        result = sing_host.dispatch({'action': 'export_logs'})
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['text'], '')

    def test_short_secrets_do_not_expand_native_reply_past_limit(self):
        """Redaction markers remain intact and the encoded reply stays bounded."""
        (self.config / 'sing.json').write_text(json.dumps({'username': 'A', 'password': 'D'}))
        self.assertEqual(sing_host.redact_log('A D'), '[REDACTED] [REDACTED]')
        self.log.write_text('A!' * (sing_host.MAX_LOG_BYTES // 2))
        result = sing_host.dispatch({'action': 'export_logs'})
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['text'].encode()), sing_host.MAX_LOG_BYTES)
        self.assertLess(len(json.dumps(result).encode()), sing_host.MAX_MESSAGE_BYTES)
