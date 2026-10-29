"""Изолированные проверки backup и восстановления sing с вымышленными данными."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import sing_host


class ConfigurationTest(unittest.TestCase):
    """Импорт не касается настоящего HOME или запущенного sing."""

    def setUp(self):
        """Создаёт отдельные файлы и безопасные парсеры."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.data = {"subscriptionUrl": "https://example.com/sub", "customLinks": ["http://example.com:80"],
                     "exceptions": {"domains": ["example.org"], "bypassRu": True}}
        selector = types.SimpleNamespace(build_outbound=lambda link: {}, normalize_domain=lambda domain: domain)
        for name, value in (("CONFIG_DIR", str(self.directory)), ("CACHE_FILE", str(self.directory / 'cache'))):
            active = patch.object(sing_host, name, value)
            active.start()
            self.addCleanup(active.stop)
        for name, value in (("load_select_module", selector), ("run_sing", (0, '', ''))):
            active = patch.object(sing_host, name, return_value=value)
            active.start()
            self.addCleanup(active.stop)

    def test_import_backs_up_and_round_trips_sources(self):
        """Backup сохраняет прежние файлы, импорт не включает автоподключение."""
        (self.directory / 'sing.sub').write_text('https://old.example.com/sub')
        (self.directory / 'sing.json').write_text('{}')
        result = sing_host.handle_import_configuration({'configuration': self.data})
        backup = Path(result['backup'])
        self.assertEqual((backup / 'sing.sub').read_text(), 'https://old.example.com/sub')
        self.assertFalse((self.directory / 'sing.json').exists())
        self.assertEqual((self.directory / 'custom.txt').stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual(sing_host.handle_export_configuration({})['configuration'], self.data)

    def test_invalid_import_preserves_files(self):
        """Ошибочный URL не меняет ни одного файла."""
        original = self.directory / 'sing.sub'
        original.write_text('original')
        with self.assertRaises(ValueError):
            sing_host.handle_import_configuration({'configuration': {**self.data, 'subscriptionUrl': 'file:///etc/passwd'}})
        self.assertEqual(original.read_text(), 'original')
        self.assertEqual(list(self.directory.glob('import-backup-*')), [])

    def test_write_failure_restores_original_files(self):
        """Ошибка записи возвращает исходные файлы из снимка."""
        original = self.directory / 'sing.sub'
        original.write_text('original')
        writer = sing_host.write_private_file
        failed = False

        def fail_once(path, contents):
            """Имитирует одну ошибку записи целевого файла после backup."""
            nonlocal failed
            if Path(path) == self.directory / 'custom.txt' and not failed:
                failed = True
                raise OSError('test failure')
            writer(path, contents)

        with patch.object(sing_host, 'write_private_file', side_effect=fail_once), self.assertRaises(RuntimeError):
            sing_host.handle_import_configuration({'configuration': self.data})
        self.assertEqual(original.read_text(), 'original')
        self.assertFalse((self.directory / 'custom.txt').exists())

    def test_symlink_is_not_overwritten(self):
        """Импорт не записывает через пользовательский symlink."""
        outside = self.directory / 'outside'
        outside.write_text('keep')
        (self.directory / 'sing.sub').symlink_to(outside)
        with self.assertRaises(ValueError):
            sing_host.handle_import_configuration({'configuration': self.data})
        self.assertEqual(outside.read_text(), 'keep')
