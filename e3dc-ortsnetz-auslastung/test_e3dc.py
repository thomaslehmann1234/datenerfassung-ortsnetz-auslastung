import importlib.util
import io
import pathlib
import signal
import sys
import types
import unittest
import urllib.error
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).with_name("e3dc_ortsnetz.py")

# Tests laufen ohne installiertes pye3dc; das Script braucht nur Klasse, Verbindungstyp
# und die RSCP-Tags für die Frequenzabfrage
if "e3dc" not in sys.modules:
    stub = types.ModuleType("e3dc")

    class E3DC:
        CONNECT_LOCAL = "local"

    stub.E3DC = E3DC

    rscp_stub = types.ModuleType("e3dc._rscpTags")

    class RscpTag:
        PVI_REQ_DATA = "PVI_REQ_DATA"
        PVI_INDEX = "PVI_INDEX"
        PVI_REQ_AC_FREQUENCY = "PVI_REQ_AC_FREQUENCY"
        PVI_VALUE = "PVI_VALUE"

    class RscpType:
        Container = "Container"
        Uint16 = "Uint16"
        NoneType = "NoneType"

    TYPNAMES = {0: "PM_TYPE_UNDEFINED", 1: "PM_TYPE_ROOT", 3: "PM_TYPE_ADDITIONAL_PRODUCTION",
                4: "PM_TYPE_ADDITIONAL_CONSUMPTION", 7: "PM_TYPE_WALLBOX"}

    def getStrPowermeterType(typ):
        return TYPNAMES.get(typ, "PM_TYPE_UNDEFINED")

    lib_stub = types.ModuleType("e3dc._rscpLib")

    def rscpFindTagIndex(objekt, tag):
        """Findiert den Wert eines Tags in verschachtelten RSCP-Antworten, wie in pye3dc."""
        if not isinstance(objekt, (list, tuple)):
            return None
        if len(objekt) >= 3 and objekt[0] == tag:
            return objekt[2]
        for teil in objekt:
            wert = rscpFindTagIndex(teil, tag)
            if wert is not None:
                return wert
        return None

    rscp_stub.RscpTag = RscpTag
    rscp_stub.RscpType = RscpType
    rscp_stub.getStrPowermeterType = getStrPowermeterType
    lib_stub.rscpFindTagIndex = rscpFindTagIndex
    stub._rscpTags = rscp_stub
    stub._rscpLib = lib_stub
    sys.modules["e3dc"] = stub
    sys.modules["e3dc._rscpTags"] = rscp_stub
    sys.modules["e3dc._rscpLib"] = lib_stub

SPEC = importlib.util.spec_from_file_location("e3dc_ortsnetz", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# Netzzähler am Index 1, Index 0 ist eine Wallbox – wie in einer abweichenden Installation
NETZ_ZAEHLER = {
    "activePhases": "111",
    "index": 1,
    "type": 1,
    "voltage": {"L1": 230.15, "L2": 231.02, "L3": 229.85},
    "power": {"L1": 100, "L2": 200, "L3": 300},
}
ZAEHLERLISTE = [
    {"index": 0, "type": 7, "typeName": "PM_TYPE_WALLBOX"},
    {"index": 1, "type": 1, "typeName": "PM_TYPE_ROOT"},
]

UMGEBUNG = {
    "E3DC_HOST": "192.168.60.220",
    "E3DC_USERNAME": "test@example.com",
    "E3DC_PASSWORD": "testpasswort",
    "RSCP_KEY": "testkey",
    "LATITUDE": "48.109569",
    "LONGITUDE": "11.726477",
    "METER_INDEX": "",
    "PLANT_CAPACITY_KWP": "",
    "ENV_DATEI": "nicht-vorhanden.env",
}


class FakeE3DC:
    CONNECT_LOCAL = "local"

    def __init__(self, zaehler=None, daten=None, frequenz=None):
        self.zaehler = zaehler if zaehler is not None else list(ZAEHLERLISTE)
        self.daten = daten if daten is not None else dict(NETZ_ZAEHLER)
        self.frequenz = frequenz
        self.getrennt = False
        self.used_index = None

    def get_powermeters(self, keepAlive=False):
        return self.zaehler

    def get_powermeter_data(self, pmIndex=None, keepAlive=False):
        self.used_index = pmIndex
        return self.daten

    def get_pvis(self, keepAlive=False):
        return [{"index": 0, "phases": 3}] if self.frequenz is not None else []

    def sendRequest(self, request, keepAlive=False):
        return ("PVI_DATA", "Container", [
            ("PVI_INDEX", "Uint16", 0),
            ("PVI_AC_FREQUENCY", "Container", [("PVI_INDEX", "Uint16", 0), ("PVI_VALUE", "Float32", self.frequenz)]),
        ])

    def disconnect(self):
        self.getrennt = True


def zaehler_constructor(fake):
    """pye3dc-Ersatz: dieselbe Aufrufform wie E3DC(...), inklusive CONNECT_LOCAL."""
    def constructor(*argumente, **schluesselworte):
        return fake

    constructor.CONNECT_LOCAL = "local"
    return constructor


def umgebung(**anderungen):
    werte = dict(UMGEBUNG)
    werte.update(anderungen)
    return werte


class FakeAntwort:
    def __init__(self, status, text):
        self.status = status
        self.text = text

    def read(self):
        return self.text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *ausnahme):
        return False


def http_fehler(code, text):
    fp = io.BytesIO(text.encode("utf-8"))
    return urllib.error.HTTPError("https://api", code, "Fehler", {}, fp)


class ZaehlerauswahlTests(unittest.TestCase):
    def netzhaehler(self, zaehler, meter_index=None):
        with patch.object(MODULE, "METER_INDEX", meter_index):
            return MODULE.netzhaehler_finden(FakeE3DC(zaehler=zaehler))

    def test_netzzaehler_nicht_index_0(self):
        # powermeters[0] ist eine Wallbox, der Netzzähler steht an Index 1
        self.assertEqual(self.netzhaehler(ZAEHLERLISTE), (1, "PM_TYPE_ROOT"))

    def test_index_aus_der_liste(self):
        selbst = [{"index": 3, "type": 1, "typeName": "PM_TYPE_ROOT"}]
        self.assertEqual(self.netzhaehler(selbst), (3, "PM_TYPE_ROOT"))

    def test_konfigurierter_index_wird_akzeptiert(self):
        self.assertEqual(self.netzhaehler(ZAEHLERLISTE, meter_index=1), (1, "PM_TYPE_ROOT"))

    def test_konfigurierter_index_falscher_typ(self):
        with self.assertRaises(MODULE.MesswertFehler) as fehler:
            self.netzhaehler(ZAEHLERLISTE, meter_index=0)
        self.assertIn("kein Netzzähler", str(fehler.exception))

    def test_kein_netzzaehler(self):
        with self.assertRaises(MODULE.MesswertFehler):
            self.netzhaehler([{"index": 0, "type": 7, "typeName": "PM_TYPE_WALLBOX"}])

    def test_keine_zaelher(self):
        with self.assertRaises(MODULE.MesswertFehler):
            self.netzhaehler([])

    def test_typ_zahl_in_neuer_pye3dc(self):
        # pye3dc ab 0.10.0 nennt die Typzahl, der Name wird über die Tags ermittelt
        self.assertEqual(self.netzhaehler([{"index": 0, "type": 1}]), (0, "PM_TYPE_ROOT"))

    def test_typname_ohne_namen(self):
        # pye3dc bis 0.9.x nennt nur die Typzahl, ohne Namen und ohne Ermittlung
        with patch.object(MODULE, "getStrPowermeterType", None):
            self.assertEqual(self.netzhaehler([{"index": 0, "type": 3}]), (0, None))


class PayloadTests(unittest.TestCase):
    def payload(self, daten, frequenz=None):
        fake = FakeE3DC(daten=daten, frequenz=frequenz)
        with patch.object(MODULE, "LATITUDE", 48.109569), patch.object(MODULE, "LONGITUDE", 11.726477), \
             patch.object(MODULE, "PLANT_CAPACITY_KWP", None):
            return MODULE.payload_erstellen(daten, fake, 1, "PM_TYPE_ROOT")

    def test_dreiphasig_mit_frequenz(self):
        payload = self.payload(dict(NETZ_ZAEHLER, frequency=50.02))
        self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (230.15, 231.02, 229.85))
        self.assertEqual(payload["grid_frequency_hz"], 50.02)
        self.assertEqual(payload["smartmeter_model"], "E3DC Hauskraftwerk")
        self.assertEqual(payload["integration_version"], "e3dc-rscp-1.1")
        self.assertRegex(payload["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertNotIn("plant_capacity_kwp", payload)

    def test_frequenz_am_wechselrichter(self):
        # pye3dc ab 0.10 hat keine Frequenz im Zählerdatensatz
        payload = self.payload(dict(NETZ_ZAEHLER), frequenz=49.98)
        self.assertEqual(payload["grid_frequency_hz"], 49.98)

    def test_frequenz_ohne_quelle(self):
        payload = self.payload(dict(NETZ_ZAEHLER), frequenz=None)
        self.assertNotIn("grid_frequency_hz", payload)

    def test_unplausibile_frequenz(self):
        payload = self.payload(dict(NETZ_ZAEHLER, frequency=60.0), frequenz=None)
        self.assertNotIn("grid_frequency_hz", payload)

    def test_phasen_ausserhalb_des_bereichs(self):
        daten = dict(NETZ_ZAEHLER)
        daten["voltage"] = {"L1": 230.0, "L2": 0, "L3": None}
        payload = self.payload(daten)
        self.assertEqual(payload["l2_v"], -1)
        self.assertEqual(payload["l3_v"], -1)

    def test_l1_unplausibel(self):
        daten = dict(NETZ_ZAEHLER)
        daten["voltage"] = {"L1": 0, "L2": 230.0, "L3": 230.0}
        with self.assertRaises(MODULE.MesswertFehler):
            self.payload(daten)

    def test_energie_alt_struktur(self):
        # pye3dc bis 0.9.x: Messwerte im "data"-Unterordner
        daten = {"id": 0, "type": 3, "data": {"voltageL1": 229.1, "voltageL2": 230.2, "voltageL3": 231.3,
                                             "frequency": 50.0}}
        payload = self.payload(daten)
        self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (229.1, 230.2, 231.3))
        self.assertEqual(payload["grid_frequency_hz"], 50.0)

    def test_pv_leistung(self):
        daten = dict(NETZ_ZAEHLER)
        fake = FakeE3DC(daten=daten, frequenz=None)
        with patch.object(MODULE, "LATITUDE", 48.1), patch.object(MODULE, "LONGITUDE", 11.7), \
             patch.object(MODULE, "PLANT_CAPACITY_KWP", 9.8):
            payload = MODULE.payload_erstellen(daten, fake, 1, "PM_TYPE_ROOT")
        self.assertEqual(payload["plant_capacity_kwp"], 9.8)


class KonfigurationTests(unittest.TestCase):
    def setUp(self):
        for name, wert in (("E3DC_HOST", ""), ("E3DC_USERNAME", ""), ("E3DC_PASSWORD", ""),
                           ("RSCP_KEY", ""), ("LATITUDE", None), ("LONGITUDE", None),
                           ("METER_INDEX", None), ("PLANT_CAPACITY_KWP", None), ("ENV_DATEI", None)):
            patcher = patch.object(MODULE, name, wert)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_umgebungsvariablen(self):
        with patch.dict("os.environ", umgebung(), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            MODULE.konfiguration_pruefen()
        self.assertEqual(MODULE.E3DC_HOST, "192.168.60.220")
        self.assertEqual(MODULE.METER_INDEX, None)

    def test_env_datei(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ordner:
            pfad = pathlib.Path(ordner) / ".env"
            pfad.write_text(
                "# Kommentar\nE3DC_HOST=10.0.0.9\nE3DC_USERNAME='quoted@example.com'\n"
                "E3DC_PASSWORD=\"passwort\"\nRSCP_KEY=key\nLATITUDE=52.52\nLONGITUDE=13.4\nMETER_INDEX=2\n"
            )
            with patch.dict("os.environ", umgebung(), clear=True):
                MODULE.env_datei_laden(str(pfad))
                MODULE.konfiguration_laden()
                MODULE.konfiguration_pruefen()
            # Gesetzte Environment-Variablen haben Vorrang vor der Datei
            self.assertEqual(MODULE.E3DC_HOST, "192.168.60.220")
            self.assertEqual(MODULE.METER_INDEX, 2)

    def test_env_datei_ergaenzt_leere_werte(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ordner:
            pfad = pathlib.Path(ordner) / ".env"
            pfad.write_text("E3DC_HOST=10.0.0.9\nLATITUDE=52.52\nLONGITUDE=13.4\n")
            with patch.dict("os.environ", umgebung(E3DC_HOST="", METER_INDEX="3"), clear=True):
                MODULE.env_datei_laden(str(pfad))
                MODULE.konfiguration_laden()
                MODULE.konfiguration_pruefen()
            self.assertEqual(MODULE.E3DC_HOST, "10.0.0.9")
            self.assertEqual(MODULE.METER_INDEX, 3)

    def test_leere_zeile_wird_ignoriert(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ordner:
            pfad = pathlib.Path(ordner) / ".env"
            pfad.write_text("E3DC_HOST=\nLATITUDE=52.52\nLONGITUDE=13.4\n")
            with patch.dict("os.environ", umgebung(), clear=True):
                MODULE.env_datei_laden(str(pfad))
                MODULE.konfiguration_laden()
                MODULE.konfiguration_pruefen()
            self.assertEqual(MODULE.E3DC_HOST, "192.168.60.220")

    def test_fehlende_zugangsdaten(self):
        with patch.dict("os.environ", umgebung(E3DC_PASSWORD=""), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler):
                MODULE.konfiguration_pruefen()

    def test_ungueltige_zahl(self):
        with patch.dict("os.environ", umgebung(LATITUDE="nichts"), clear=True):
            MODULE.env_datei_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler):
                MODULE.konfiguration_laden()

    def test_ausserhalb_bereich(self):
        with patch.dict("os.environ", umgebung(LATITUDE="91"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler):
                MODULE.konfiguration_pruefen()


class SendeTests(unittest.TestCase):
    payload = {"observed_at": "2026-09-15T08:00:00Z", "latitude": 48.1, "longitude": 11.7,
               "l1_v": 230.0, "l2_v": 230.0, "l3_v": 230.0,
               "smartmeter_model": "E3DC Hauskraftwerk", "integration_version": "e3dc-rscp-1.1"}

    def status(self, code, text):
        with patch("urllib.request.urlopen", return_value=FakeAntwort(code, text)):
            MODULE.senden(self.payload)

    def test_annahme(self):
        self.status(202, '{"accepted": true, "created": true}')

    def test_202_ohne_annahme(self):
        with self.assertRaises(MODULE.ApiFehler):
            self.status(202, '{"accepted": false}')

    def test_422(self):
        with patch("urllib.request.urlopen", side_effect=http_fehler(422, " Payload abgelehnt")):
            with self.assertRaises(MODULE.ApiFehler):
                MODULE.senden(self.payload)

    def test_403(self):
        with patch("urllib.request.urlopen", side_effect=http_fehler(403, "gesperrt")):
            with self.assertRaises(MODULE.ApiFehler):
                MODULE.senden(self.payload)

    def test_verbindungsabbruch(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("keine Route")):
            with self.assertRaises(MODULE.ApiFehler):
                MODULE.senden(self.payload)


class MainTests(unittest.TestCase):
    def setUp(self):
        for name, wert in (("E3DC_HOST", ""), ("E3DC_USERNAME", ""), ("E3DC_PASSWORD", ""),
                           ("RSCP_KEY", ""), ("LATITUDE", None), ("LONGITUDE", None),
                           ("METER_INDEX", None), ("PLANT_CAPACITY_KWP", None), ("ENV_DATEI", None)):
            patcher = patch.object(MODULE, name, wert)
            patcher.start()
            self.addCleanup(patcher.stop)

    def main(self, fake, argumente=(), gesendet=None):
        def sender(payload):
            if gesendet is not None:
                gesendet.append(payload)
            return True

        with patch.object(MODULE, "E3DC", zaehler_constructor(fake)), \
             patch.object(MODULE, "senden", sender), \
             patch.dict("os.environ", umgebung(), clear=True):
            self.addCleanup(signal.alarm, 0)
            return MODULE.main(list(argumente))

    def test_erfolg(self):
        fake = FakeE3DC(frequenz=50.01)
        gesendet = []
        self.assertEqual(self.main(fake, gesendet=gesendet), 0)
        self.assertEqual(fake.used_index, 1, "Netzzähler an Index 1, nicht powermeters[0]")
        self.assertEqual(gesendet[0]["grid_frequency_hz"], 50.01)
        self.assertTrue(fake.getrennt, "Verbindung wird getrennt")

    def test_dry_run(self):
        fake = FakeE3DC(frequenz=50.0)
        gesendet = []
        self.assertEqual(self.main(fake, ["--dry-run"], gesendet=gesendet), 0)
        self.assertEqual(gesendet, [], "--dry-run sendet nichts")

    def test_konfiguration(self):
        with patch.dict("os.environ", umgebung(E3DC_HOST=""), clear=True):
            self.addCleanup(signal.alarm, 0)
            self.assertEqual(MODULE.main([]), MODULE.EXIT_KONFIGURATION)

    def test_verbindung(self):
        def Verbindungsfehler(*argumente, **schluesselworte):
            raise OSError("Connection refused")

        Verbindungsfehler.CONNECT_LOCAL = "local"

        with patch.object(MODULE, "E3DC", Verbindungsfehler), \
             patch.dict("os.environ", umgebung(), clear=True):
            self.addCleanup(signal.alarm, 0)
            self.assertEqual(MODULE.main([]), MODULE.EXIT_RSCP)

    def test_unplausible_spannung(self):
        fake = FakeE3DC(daten=dict(NETZ_ZAEHLER, voltage={"L1": 0, "L2": 0, "L3": 0}))
        self.assertEqual(self.main(fake), MODULE.EXIT_MESSUNG)

    def test_falscher_index_typ(self):
        fake = FakeE3DC(zaehler=ZAEHLERLISTE)
        with patch.object(MODULE, "METER_INDEX", 0):
            self.assertEqual(self.main(fake), MODULE.EXIT_MESSUNG)

    def test_api_fehler(self):
        fake = FakeE3DC(frequenz=50.0)
        def sender(payload):
            raise MODULE.ApiFehler("HTTP 422 – Payload abgelehnt")

        with patch.object(MODULE, "E3DC", zaehler_constructor(fake)), \
             patch.object(MODULE, "senden", sender), \
             patch.dict("os.environ", umgebung(), clear=True):
            self.addCleanup(signal.alarm, 0)
            self.assertEqual(MODULE.main([]), MODULE.EXIT_API)


if __name__ == "__main__":
    unittest.main()
