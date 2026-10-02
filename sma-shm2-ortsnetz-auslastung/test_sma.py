"""Regressionstests mit synthetischen SMA-Telegrammen, ohne Netzwerkzugriffe."""

import contextlib
import importlib.util
import io
import json
import socket
import struct
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PFAD = Path(__file__).with_name("ortsnetz-sma-shm2.py")
SPEC = importlib.util.spec_from_file_location("sma", PFAD)
sma = importlib.util.module_from_spec(SPEC)
with patch.dict("os.environ", {}, clear=True):
    SPEC.loader.exec_module(sma)


def messwert(index, wert, kanal=0, tarif=0, typ=4):
    return bytes((kanal, index, typ, tarif)) + wert.to_bytes(typ, "big")


def telegramm(datensaetze, seriennummer=123456):
    # Aufbau nach SMA EMETER-Protokoll-TI-en-10, Kapitel 4.
    inhalt = struct.pack(">HHII", 0x6069, 349, seriennummer, 123000) + datensaetze
    return (bytes.fromhex("534d4100 000402a0 00000001")
            + struct.pack(">HH", len(inhalt), 0x10) + inhalt + bytes(4))


SPANNUNGEN = messwert(32, 230123) + messwert(52, 229900) + messwert(72, 231200)
VERSION = bytes.fromhex("90000000 02010052")


class SmaTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(
            sma, LATITUDE=52.5, LONGITUDE=13.4, METER_SERIAL=None,
            INTERVAL_S=300, INTERFACE_IP="0.0.0.0"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.http = self.stack.enter_context(patch.object(
            sma.urllib.request, "urlopen", side_effect=AssertionError("Unerwarteter HTTP-Aufruf")))
        self.netz = self.stack.enter_context(patch.object(
            sma, "multicast_socket", side_effect=AssertionError("Unerwarteter Socket-Aufruf")))

    def empfang(self, pakete):
        sock = MagicMock()
        sock.recvfrom.side_effect = [(paket, ("192.0.2.1", 9522)) for paket in pakete]
        return sock

    def einmallauf(self, args, pakete):
        sock = self.empfang(pakete)
        self.netz.side_effect = None
        self.netz.return_value.__enter__.return_value = sock
        return sma.main(args)

    def antwort(self, daten, status=202):
        self.http.side_effect = None
        self.http.return_value.__enter__.return_value = io.BytesIO(daten)
        self.http.return_value.__enter__.return_value.status = status

    def test_spannungen_frequenz_energie_und_payload(self):
        energie = messwert(1, 123456789, typ=8)
        serial, werte = sma.telegramm_dekodieren(telegramm(
            energie + SPANNUNGEN + messwert(14, 50010) + VERSION))
        self.assertEqual(serial, 123456)
        payload = sma.payload_erstellen(werte)
        self.assertEqual([payload[f"l{i}_v"] for i in (1, 2, 3)], [230.1, 229.9, 231.2])
        self.assertEqual(payload["grid_frequency_hz"], 50.01)
        self.assertTrue(payload["observed_at"].endswith("Z"))
        self.assertEqual(set(payload), {
            "observed_at", "latitude", "longitude", "l1_v", "l2_v", "l3_v",
            "grid_frequency_hz", "integration_version"})

    def test_version_vor_zwischen_und_nach_messwerten(self):
        for daten in (VERSION + SPANNUNGEN, SPANNUNGEN[:8] + VERSION + SPANNUNGEN[8:],
                      SPANNUNGEN + VERSION):
            with self.subTest(daten=daten.hex()):
                self.assertEqual(sma.telegramm_dekodieren(telegramm(daten))[1][72], 231200)

    def test_alle_abgeschnittenen_telegramme_verwerfen(self):
        paket = telegramm(SPANNUNGEN + messwert(1, 12, typ=8) + VERSION)
        for laenge in range(len(paket)):
            with self.subTest(laenge=laenge):
                self.assertIsNone(sma.telegramm_dekodieren(paket[:laenge]))

    def test_fehlerhafte_kennungen_laengen_und_abschluss_verwerfen(self):
        paket = telegramm(SPANNUNGEN)
        for offset in (0, 3, 4, 6, 12, 13, 14, 16, len(paket) - 1):
            with self.subTest(offset=offset):
                daten = bytearray(paket)
                daten[offset] ^= 1
                self.assertIsNone(sma.telegramm_dekodieren(daten))
        self.assertIsNone(sma.telegramm_dekodieren(paket + bytes(4)))

    def test_unvollstaendige_und_unbekannte_datensaetze_verwerfen(self):
        for rest in (b"\x00", messwert(52, 230000)[:-1], messwert(1, 123, typ=8)[:-1],
                     bytes.fromhex("00340300 00038270")):
            with self.subTest(rest=rest.hex()):
                self.assertIsNone(sma.telegramm_dekodieren(telegramm(SPANNUNGEN + rest)))

    def test_andere_kanaele_und_tarife_ueberschreiben_nicht(self):
        daten = SPANNUNGEN + messwert(32, 180000, kanal=1) + messwert(52, 190000, tarif=1)
        self.assertEqual(sma.telegramm_dekodieren(telegramm(daten))[1],
                         {32: 230123, 52: 229900, 72: 231200})

    def test_leeres_telegramm(self):
        self.assertEqual(sma.telegramm_dekodieren(telegramm(b"")), (123456, {}))

    def test_optionale_felder_und_grenzwerte(self):
        for roh in (0, 1, 49, 500001, 0xFFFFFFFF):
            with self.subTest(roh=roh):
                self.assertEqual(sma.spannung({32: roh}, 1), -1)
        self.assertEqual(sma.spannung({32: 500000}, 1), 500)
        payload = sma.payload_erstellen({32: 230000, 14: 60000})
        self.assertEqual(payload["l2_v"], -1)
        self.assertEqual(payload["l3_v"], -1)
        self.assertNotIn("grid_frequency_hz", payload)

    def test_serialfilter_und_ungueltige_messungen(self):
        sma.METER_SERIAL = 222
        sock = self.empfang([b"garbage", telegramm(SPANNUNGEN, 111),
                             telegramm(b"", 222), telegramm(messwert(32, 0), 222),
                             telegramm(SPANNUNGEN, 222)])
        self.assertEqual(sma.messung_empfangen(sock)[0], 222)

    def test_timeout_auch_bei_fremden_telegrammen(self):
        with patch.object(sma.time, "monotonic", side_effect=[0, 0, 16]):
            self.assertIsNone(sma.messung_empfangen(self.empfang([b"garbage"])))

    def test_dry_run_ohne_upload(self):
        self.assertEqual(self.einmallauf(["--dry-run"], [telegramm(SPANNUNGEN)]), 0)
        self.http.assert_not_called()
        self.netz.return_value.__exit__.assert_called_once()

    def test_erfolgreicher_upload(self):
        self.antwort(b'{"accepted":true,"status":{"overall":"green"}}')
        self.assertEqual(self.einmallauf(["--once"], [telegramm(SPANNUNGEN)]), 0)
        anfrage = self.http.call_args[0][0]
        self.assertEqual(anfrage.method, "POST")
        self.assertEqual(anfrage.full_url, sma.API_URL)
        self.assertEqual(json.loads(anfrage.data)["l1_v"], 230.1)

    def test_http_fehler_liefert_exitcode_eins(self):
        self.http.side_effect = sma.urllib.error.HTTPError(
            sma.API_URL, 422, "invalid", {}, io.BytesIO(b"invalid measurement"))
        self.assertEqual(self.einmallauf(["--once"], [telegramm(SPANNUNGEN)]), 1)

    def test_netzwerkfehler_liefert_exitcode_eins(self):
        self.http.side_effect = sma.urllib.error.URLError("offline")
        self.assertEqual(self.einmallauf(["--once"], [telegramm(SPANNUNGEN)]), 1)

    def test_ungueltige_api_bestaetigung_liefert_exitcode_eins(self):
        for daten, status in ((b"invalid", 202), (b"[]", 202), (b"{}", 202),
                              (b'{"accepted":false}', 202), (b'{"accepted":true}', 200)):
            with self.subTest(daten=daten, status=status):
                self.antwort(daten, status)
                self.assertEqual(self.einmallauf(["--once"], [telegramm(SPANNUNGEN)]), 1)

    def test_empfangstimeout_liefert_exitcode_eins(self):
        sock = MagicMock()
        sock.recvfrom.side_effect = socket.timeout
        self.netz.side_effect = None
        self.netz.return_value.__enter__.return_value = sock
        for args in (["--once"], ["--dry-run"]):
            self.assertEqual(sma.main(args), 1)
        self.http.assert_not_called()

    def test_hilfe_und_falsche_argumente_ohne_netzwerk(self):
        for args, code in ((["--help"], 0), (["--dryrun"], 2),
                           (["--once", "--dry-run"], 2)):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                sma.main(args)
            self.assertEqual(error.exception.code, code)
        self.netz.assert_not_called()
        self.http.assert_not_called()

    def test_ungueltige_konfiguration_verhindert_netzwerkzugriff(self):
        for name, wert in (("LATITUDE", None), ("LATITUDE", 91), ("LATITUDE", float("nan")),
                           ("LONGITUDE", -181), ("LONGITUDE", float("inf")),
                           ("INTERVAL_S", 0), ("INTERVAL_S", -1),
                           ("METER_SERIAL", -1), ("METER_SERIAL", 2**32),
                           ("INTERFACE_IP", "not-an-ip")):
            with self.subTest(name=name, wert=wert), patch.object(sma, name, wert):
                with self.assertRaises(SystemExit) as error:
                    sma.main(["--once"])
                self.assertEqual(error.exception.code, 2)
        self.netz.assert_not_called()


if __name__ == "__main__":
    unittest.main()
