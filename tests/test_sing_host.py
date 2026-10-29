"""Тесты чистой логики native host: разбор вывода sing, валидация имён, протокол."""

import io
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "host"))

import sing_host  # noqa: E402

SELECT_OUTPUT = """— свои:
 * MyUK
— подписка:
   🇱🇹 Вильнюс, Литва, Extra
"""


class SingHostTest(unittest.TestCase):
    """Проверки разбора и защиты входных данных."""

    def test_parse_marks_groups_and_current(self):
        locations = sing_host.parse_select_output(SELECT_OUTPUT)

        self.assertEqual([item["group"] for item in locations], ["custom", "subscription"])
        self.assertTrue(locations[0]["current"])

    def test_parse_splits_flag_city_country(self):
        location = sing_host.parse_select_output(SELECT_OUTPUT)[1]

        self.assertEqual((location["flag"], location["city"], location["country"]),
                         ("🇱🇹", "Вильнюс", "Литва"))

    def test_reserved_names_rejected(self):
        for bad_name in ("add", "RM", "--help", "", None, "x" * 500):
            with self.subTest(bad_name=bad_name), self.assertRaises(ValueError):
                sing_host.validate_location_name(bad_name)

    def test_message_round_trip(self):
        buffer = io.BytesIO()
        sing_host.write_message(buffer, {"ok": True})
        buffer.seek(0)

        self.assertEqual(sing_host.read_message(buffer), {"ok": True})

    def test_oversized_message_rejected(self):
        buffer = io.BytesIO(struct.pack("=I", sing_host.MAX_MESSAGE_BYTES + 1))

        with self.assertRaises(ValueError):
            sing_host.read_message(buffer)

    def test_connect_reserved_name_returns_error(self):
        self.assertFalse(sing_host.dispatch({"action": "connect", "name": "add"})["ok"])


class FakeSelectModule:
    """Подмена select.py: ссылки вида «тип:имя»; wg считается WireGuard, bad — битой."""

    @staticmethod
    def build_outbound(link):
        kind, _, _name = link.partition(":")
        if kind == "bad":
            raise ValueError("bad link")
        return {"type": "wireguard" if kind == "wg" else kind, "tag": "proxy", "server": "h"}

    @staticmethod
    def link_name(link):
        return link.partition(":")[2]


class ProbeOutboundsTest(unittest.TestCase):
    """Подготовка outbound-ов для замера задержки."""

    def test_skips_wireguard_and_bad_links_and_assigns_unique_tags(self):
        outbounds, names = sing_host.build_probe_outbounds(
            FakeSelectModule, ["vless:A", "wg:B", "bad:C", "trojan:D"])

        self.assertEqual([item["tag"] for item in outbounds], ["probe-0", "probe-1"])
        self.assertEqual(names, {"probe-0": "A", "probe-1": "D"})

    def test_no_links_gives_no_outbounds(self):
        self.assertEqual(sing_host.build_probe_outbounds(FakeSelectModule, []), ([], {}))


class SingMissingTest(unittest.TestCase):
    """Режим без sing: host отвечает флагом singMissing, а не падает."""

    def test_sing_actions_report_missing_sing(self):
        original = sing_host.SING_BIN
        sing_host.SING_BIN = "/nonexistent/sing"
        try:
            for action in ("list", "connect", "exceptions_get"):
                reply = sing_host.dispatch({"action": action})
                self.assertFalse(reply["ok"])
                self.assertTrue(reply["singMissing"])
        finally:
            sing_host.SING_BIN = original

    def test_ping_still_works_without_sing(self):
        original = sing_host.SING_BIN
        sing_host.SING_BIN = "/nonexistent/sing"
        try:
            self.assertEqual(sing_host.dispatch({"action": "ping"}), {"ok": True, "singInstalled": False})
        finally:
            sing_host.SING_BIN = original


class InstallerTest(unittest.TestCase):
    """Проверки установки native host без изменений домашнего каталога пользователя."""

    def setUp(self):
        """Создаёт отдельный HOME и подменяет внешние команды."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.home = self.root / 'home "with" spaces'
        self.home.mkdir()
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        for name in ("bash", "dirname", "mkdir", "ln", "mv", "chmod", "cat", "cmp", "cp", "mktemp", "rm", "touch"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable)
            (self.fake_bin / name).symlink_to(executable)

        self.browser = self.home / "Library/Application Support/Google/Chrome"
        self.browser.mkdir(parents=True)
        self.repo = self.root / 'VPN "Ext" Browser'
        (self.repo / "src/host").mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / "install.sh"
        # Не даём тестам вызвать настоящий Homebrew на машине разработчика.
        installer_text = source.read_text()
        self.assertIn("/opt/homebrew/bin/brew", installer_text)
        self.assertIn("/usr/local/bin/brew", installer_text)
        self.assertIn('HOST_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"',
                      installer_text)
        installer_text = installer_text.replace(
            "/opt/homebrew/bin/brew", str(self.root / "absent-opt-brew")
        ).replace("/usr/local/bin/brew", str(self.root / "absent-local-brew")).replace(
            'HOST_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"',
            f'HOST_PATH="{self.fake_bin}"',
        )
        self.make_script(self.repo / "install.sh", installer_text)
        (self.repo / "src/host/sing_host.py").write_text("# test host\n")
        self.make_script(self.fake_bin / "node", "#!/bin/sh\necho v20.0.0\n")
        self.make_script(self.fake_bin / "npm", """#!/bin/bash
printf '%s\n' "$*" >> "$BUILD_LOG"
if [[ "$*" == "run build" ]]; then
  [[ "${FAIL_BUILD:-}" != "1" ]] || exit 1
  mkdir -p build
  touch build/manifest.json build/background.js build/popup.js build/proxy-links.js build/popup.html build/popup.css
fi
""")
        sing_repo = self.root / "sing"
        sing_repo.mkdir()
        self.make_script(sing_repo / "install.sh", """#!/bin/bash
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/sing" "$HOME/.proxychains"
printf '#!/bin/sh\\nexit 0\\n' > "$HOME/.local/bin/sing"
chmod +x "$HOME/.local/bin/sing"
touch "$HOME/.local/share/sing/select.py" "$HOME/.proxychains/sing.conf"
printf 'sing installed\\n' >> "$INSTALL_LOG"
""")
        self.environment = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": str(self.fake_bin),
            "FAKE_BIN": str(self.fake_bin),
            "INSTALL_LOG": str(self.root / "install.log"),
            "BUILD_LOG": str(self.root / "build.log"),
            "REAL_PYTHON": sys.executable,
        }

    def make_script(self, path, content):
        """Пишет исполняемый тестовый скрипт."""
        path.write_text(content)
        path.chmod(0o755)

    def make_dependency_commands(self):
        """Добавляет доступные команды без вызова Homebrew."""
        for name in ("python3", "sing-box", "proxychains4", "nc"):
            content = ("#!/bin/sh\nexec \"$REAL_PYTHON\" \"$@\"\n" if name == "python3"
                       else "#!/bin/sh\nexit 0\n")
            self.make_script(self.fake_bin / name, content)

    def run_installer(self):
        """Запускает установщик в изолированном окружении."""
        return subprocess.run(
            [str(self.repo / "install.sh")], env=self.environment,
            text=True, capture_output=True, check=False, timeout=15,
        )

    def test_installs_missing_dependencies_and_sing(self):
        """Один запуск ставит зависимости, sing и регистрирует native host."""
        self.make_script(self.fake_bin / "brew", """#!/bin/bash
printf '%s\\n' "$*" >> "$INSTALL_LOG"
for command_name in python3 sing-box proxychains4 nc; do
  printf '#!/bin/sh\\nexit 0\\n' > "$FAKE_BIN/$command_name"
  chmod +x "$FAKE_BIN/$command_name"
done
printf '#!/bin/sh\\nexec "$REAL_PYTHON" "$@"\\n' > "$FAKE_BIN/python3"
""")

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("install python sing-box proxychains-ng netcat", (self.root / "install.log").read_text())
        self.assertEqual((self.root / "build.log").read_text().splitlines(),
                         ["ci --no-audit --no-fund", "run build"])
        self.assertTrue((self.home / ".local/bin/sing").is_file())
        manifest = self.browser / "NativeMessagingHosts/com.singvpn.host.json"
        self.assertEqual(json.loads(manifest.read_text())["path"],
                         str(self.home / ".local/share/sing-vpn/host.sh"))
        wrapper = self.home / ".local/share/sing-vpn/host.sh"
        self.assertEqual(subprocess.run([shutil.which("bash"), "-n", str(wrapper)], check=False).returncode, 0)
        self.assertEqual(shlex.split(wrapper.read_text().splitlines()[1])[-1],
                         str(self.repo / "src/host/sing_host.py"))

    def test_reuses_installed_dependencies_and_sing(self):
        """Повторный запуск не переустанавливает готовые зависимости и sing."""
        self.make_dependency_commands()
        sing_binary = self.home / ".local/bin/sing"
        sing_binary.parent.mkdir(parents=True)
        self.make_script(sing_binary, "#!/bin/sh\nexit 0\n")
        (self.home / ".local/share/sing").mkdir(parents=True)
        (self.home / ".local/share/sing/select.py").touch()
        (self.home / ".proxychains").mkdir()
        (self.home / ".proxychains/sing.conf").touch()

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "install.log").exists())
        manifest = self.browser / "NativeMessagingHosts/com.singvpn.host.json"
        self.assertTrue(manifest.is_file())
        second_result = self.run_installer()
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        self.assertEqual(list(manifest.parent.glob("com.singvpn.host.json.bak.*")), [])
        self.assertEqual((self.root / "build.log").read_text().splitlines(),
                         ["ci --no-audit --no-fund", "run build"] * 2)

    def test_installs_node_when_missing(self):
        """Отсутствующие Node.js и npm ставятся до сборки."""
        self.make_dependency_commands()
        (self.fake_bin / "node").unlink()
        (self.fake_bin / "npm").unlink()
        self.make_script(self.fake_bin / "brew", """#!/bin/bash
printf '%s\n' "$*" >> "$INSTALL_LOG"
printf '#!/bin/sh\necho v20.0.0\n' > "$FAKE_BIN/node"
chmod +x "$FAKE_BIN/node"
cp "$FAKE_NPM_SOURCE" "$FAKE_BIN/npm"
chmod +x "$FAKE_BIN/npm"
""")
        npm_source = self.root / "npm-source"
        self.make_script(npm_source, """#!/bin/bash
printf '%s\n' "$*" >> "$BUILD_LOG"
if [[ "$*" == "run build" ]]; then
  mkdir -p build
  touch build/manifest.json build/background.js build/popup.js build/proxy-links.js build/popup.html build/popup.css
fi
""")
        self.environment["FAKE_NPM_SOURCE"] = str(npm_source)

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("install node", (self.root / "install.log").read_text())
        self.assertIn("run build", (self.root / "build.log").read_text())

    def test_build_failure_does_not_register_host(self):
        """Ошибка сборки останавливает установку до записи файлов пользователя."""
        self.make_dependency_commands()
        self.environment["FAIL_BUILD"] = "1"

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.browser / "NativeMessagingHosts/com.singvpn.host.json").exists())
        self.assertFalse((self.home / ".local/share/sing-vpn/host.sh").exists())

    def test_installs_homebrew_when_missing(self):
        """Отсутствующий Homebrew ставится в том же запуске перед формулами."""
        brew_source = self.root / "brew-source"
        self.make_script(brew_source, """#!/bin/bash
printf '%s\\n' "$*" >> "$INSTALL_LOG"
for command_name in python3 sing-box proxychains4 nc; do
  printf '#!/bin/sh\\nexit 0\\n' > "$FAKE_BIN/$command_name"
  chmod +x "$FAKE_BIN/$command_name"
done
printf '#!/bin/sh\\nexec "$REAL_PYTHON" "$@"\\n' > "$FAKE_BIN/python3"
""")
        homebrew_installer = self.root / "homebrew-installer"
        self.make_script(homebrew_installer, """#!/bin/bash
cp "$FAKE_BREW_SOURCE" "$FAKE_BIN/brew"
chmod +x "$FAKE_BIN/brew"
printf 'homebrew installed\\n' >> "$INSTALL_LOG"
""")
        self.make_script(self.fake_bin / "curl", "#!/bin/bash\ncp \"$FAKE_HOMEBREW_INSTALLER\" \"$3\"\n")
        self.environment["FAKE_BREW_SOURCE"] = str(brew_source)
        self.environment["FAKE_HOMEBREW_INSTALLER"] = str(homebrew_installer)

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.root / "install.log").read_text()
        self.assertIn("homebrew installed", log)
        self.assertIn("install python sing-box proxychains-ng netcat", log)

    def test_preserves_existing_sing_backup(self):
        """Повторный backup не перезаписывает файл пользователя."""
        self.make_dependency_commands()
        sing_binary = self.home / ".local/bin/sing"
        sing_binary.parent.mkdir(parents=True)
        sing_binary.write_text("existing sing")
        backup = sing_binary.with_name("sing.bak")
        backup.write_text("user backup")

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sing_binary.read_text(), "existing sing")
        self.assertEqual(backup.read_text(), "user backup")
        self.assertFalse((self.browser / "NativeMessagingHosts/com.singvpn.host.json").exists())

    def test_clones_sing_when_sibling_checkout_is_missing(self):
        """Без соседнего checkout установщик получает sing в свой каталог."""
        self.make_dependency_commands()
        template = self.root / "sing-template"
        shutil.move(self.root / "sing", template)
        self.environment["SING_TEMPLATE_DIR"] = str(template)
        self.make_script(self.fake_bin / "git", """#!/bin/bash
printf 'git %s\\n' "$*" >> "$INSTALL_LOG"
cp -R "$SING_TEMPLATE_DIR" "$5"
""")

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("git clone --depth 1", (self.root / "install.log").read_text())
        self.assertTrue((self.home / ".local/share/sing-vpn/sing-source/install.sh").is_file())
        self.assertTrue((self.home / ".local/bin/sing").is_file())

    def test_backs_up_existing_native_host_files(self):
        """Установка сохраняет прежние wrapper и manifest без перезаписи."""
        self.make_dependency_commands()
        sing_binary = self.home / ".local/bin/sing"
        sing_binary.parent.mkdir(parents=True)
        self.make_script(sing_binary, "#!/bin/sh\nexit 0\n")
        (self.home / ".local/share/sing").mkdir(parents=True)
        (self.home / ".local/share/sing/select.py").touch()
        (self.home / ".proxychains").mkdir()
        (self.home / ".proxychains/sing.conf").touch()
        wrapper = self.home / ".local/share/sing-vpn/host.sh"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("user wrapper")
        manifest = self.browser / "NativeMessagingHosts/com.singvpn.host.json"
        manifest.parent.mkdir()
        manifest.write_text("user manifest")

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([path.read_text() for path in wrapper.parent.glob("host.sh.bak.*")],
                         ["user wrapper"])
        self.assertEqual([path.read_text() for path in manifest.parent.glob("com.singvpn.host.json.bak.*")],
                         ["user manifest"])
        self.assertNotEqual(wrapper.read_text(), "user wrapper")
        self.assertNotEqual(manifest.read_text(), "user manifest")


if __name__ == "__main__":
    unittest.main()
