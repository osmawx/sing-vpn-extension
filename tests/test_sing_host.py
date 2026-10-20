"""Тесты чистой логики native host: разбор вывода sing, валидация имён, протокол."""

import io
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host"))

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


if __name__ == "__main__":
    unittest.main()
