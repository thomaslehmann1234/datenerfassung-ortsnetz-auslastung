import importlib.util
import io
import json
import pathlib
import signal
import sys
import tempfile
import types
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).with_name("e3dc_ortsnetz.py")

# Tests laufen ohne installiertes pye3dc; das Script braucht nur Klasse, Verbindungstyp
# und die RSCP-Tags für Frequenz-, Netzleistungs- und SOC-Abfrage
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
        EMS_REQ_POWER_GRID = "EMS_REQ_POWER_GRID"
        EMS_REQ_BAT_SOC = "EMS_REQ_BAT_SOC"

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
    "BATTERY_CAPACITY_KWH": "",
    "PV_FORECAST_HA_URL": "",
    "PV_FORECAST_HA_TOKEN": "",
    "PV_FORECAST_HA_ENTITY": "",
    "PV_FORECAST_MAX_AGE_S": "",
    "PV_FORECAST_DATEI": "",
    "PV_FORECAST_BEFEHL": "",
    "SMARTMETER_MODEL": "",
    "STATE_DATEI": "",
    "SENDINTERVALL_S": "",
    "ENV_DATEI": "nicht-vorhanden.env",
}

# Feste Zeitpunkte für Stichproben im 300-Sekunden-Intervall
ZEIT = 1_700_000_000
STICHPROBEN = [
    [ZEIT - 240, 229.0, 231.0, 230.0, 49.90],
    [ZEIT - 180, 230.5, 232.0, 230.5, 50.02],
    [ZEIT - 120, 231.5, 229.5, None, 50.10],
    [ZEIT - 60, 230.0, None, 231.0, None],
    [ZEIT, 230.15, 231.02, 229.85, 50.02],
]


class FakeE3DC:
    CONNECT_LOCAL = "local"

    def __init__(self, zaehler=None, daten=None, frequenz=None, leistung=-4200.0, soc=57,
                 peak=None, kapazitaet=None, model="S10_Mini", serial="8800123456789"):
        self.zaehler = zaehler if zaehler is not None else list(ZAEHLERLISTE)
        self.daten = daten if daten is not None else dict(NETZ_ZAEHLER)
        self.frequenz = frequenz
        self.leistung = leistung
        self.soc = soc
        self.installedPeakPower = peak
        self.installedBatteryCapacity = kapazitaet
        self.model = model
        self.serialNumber = serial
        self.getrennt = False
        self.used_index = None
        self.tags = []

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

    def sendRequestTag(self, tag, keepAlive=False):
        self.tags.append(tag)
        if tag == "EMS_REQ_POWER_GRID":
            return self.leistung
        if tag == "EMS_REQ_BAT_SOC":
            return self.soc
        return None

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


def protokollierter_lauf(daten, fake, index=1, typ="PM_TYPE_ROOT", fenster=None, forecast=None):
    """Liefert den Payload einer Stichprobe, wie main ihn baut."""
    lauf = MODULE.messlauf_erstellen(daten, fake, index, typ)
    stichprobe = MODULE.stichprobe_erstellen(lauf, ZEIT)
    fenster = fenster if fenster is not None else [stichprobe]
    with patch.object(MODULE, "LATITUDE", 48.109569), patch.object(MODULE, "LONGITUDE", 11.726477), \
         patch.object(MODULE, "SENDINTERVALL_S", 300):
        return MODULE.payload_erstellen(stichprobe, fenster, lauf, forecast)


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


def logfanger():
    """Sammelt alle Logzeilen des Scripts in einer Liste."""
    zeilen = []
    return patch.object(MODULE, "log", lambda text: zeilen.append(text)), zeilen


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


class KennzahlenTests(unittest.TestCase):
    def fenster_aus(self, proben, zeitpunkt=ZEIT):
        with patch.object(MODULE, "SENDINTERVALL_S", 300):
            return MODULE.stichproben_fenster(proben, zeitpunkt)

    def test_min_max_avg_ueber_stichproben(self):
        fenster = self.fenster_aus(STICHPROBEN)
        self.assertEqual(len(fenster), 5, "alle fünf Stichproben liegen im Intervall")
        self.assertEqual(MODULE.kennzahlen(fenster, 1), (229.0, 231.5, 230.23))

    def test_min_kleiner_avg_kleiner_max(self):
        fenster = self.fenster_aus(STICHPROBEN)
        for spalte in (1, 2, 3, 4):
            ken = MODULE.kennzahlen(fenster, spalte)
            if ken:
                self.assertLessEqual(ken[0], ken[2])
                self.assertLessEqual(ken[2], ken[1])

    def test_fehtende_werte_werden_ignoriert(self):
        fenster = self.fenster_aus(STICHPROBEN)
        # L2 fehlt in der Stichprobe bei ZEIT-60, Frequenz fehlt bei ZEIT-60
        self.assertEqual(MODULE.kennzahlen(fenster, 2), (229.5, 232.0, round((231.0 + 232.0 + 229.5 + 231.02) / 4, 2)))
        self.assertEqual(MODULE.kennzahlen(fenster, 4), (49.9, 50.1, round((49.90 + 50.02 + 50.10 + 50.02) / 4, 2)))

    def test_keine_gueltigen_werte(self):
        fenster = [[ZEIT, None, None, None, None]]
        self.assertEqual(MODULE.kennzahlen(fenster, 2), None)
        self.assertEqual(MODULE.kennzahlen(fenster, 4), None)

    def test_runden_auf_zwei_nachkommastellen(self):
        fenster = [[ZEIT, 229.995, 230.0, 230.0, 49.9995]]
        self.assertEqual(MODULE.kennzahlen(fenster, 1), (230.0, 230.0, 230.0))

    def test_fenster_nur_intervall(self):
        proben = STICHPROBEN + [[ZEIT - 400, 228.0, 228.0, 228.0, 49.0], [ZEIT + 5, 240.0, 240.0, 240.0, 51.0]]
        fenster = self.fenster_aus(proben)
        self.assertEqual([s[0] for s in fenster], [s[0] for s in STICHPROBEN])

    def test_pruenen_wirft_altlast_und_zukunft(self):
        proben = STICHPROBEN + [[ZEIT - 1000, 220.0, 220.0, 220.0, 49.0], [ZEIT + 30, 240.0, 240.0, 240.0, 51.0]]
        with patch.object(MODULE, "AUFBEWAHRUNG_S", 900):
            geprueft = MODULE.stichproben_pruenen(proben, ZEIT)
        self.assertEqual([s[0] for s in geprueft], [s[0] for s in STICHPROBEN])

    def test_pruenen_kappt_max_stichproben(self):
        proben = [[ZEIT - i, 230.0, 230.0, 230.0, 50.0] for i in range(60)]
        with patch.object(MODULE, "MAX_STICHPROBEN", 40):
            geprueft = MODULE.stichproben_pruenen(proben, ZEIT)
        self.assertEqual(len(geprueft), 40)
        self.assertEqual(geprueft[-1][0], ZEIT, "die aktuellste Stichprobe bleibt")
        self.assertEqual(geprueft[0][0], ZEIT - 39)

    def test_sortierung_aufsteigend(self):
        proben = [[ZEIT, 230.0, 230.0, 230.0, 50.0], [ZEIT - 60, 229.0, 229.0, 229.0, 49.9]]
        geprueft = MODULE.stichproben_pruenen(proben, ZEIT)
        self.assertEqual([s[0] for s in geprueft], [ZEIT - 60, ZEIT])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)
        self.pfad = str(pathlib.Path(self.ordner.name) / "state.json")

    def test_state_pfad_standard(self):
        with patch.object(MODULE, "STATE_DATEI", ""), patch.dict("os.environ", {"XDG_STATE_HOME": "/tmp/stx"}, clear=True):
            self.assertEqual(MODULE.state_pfad(), "/tmp/stx/ortsnetz-e3dc/state.json")
        with patch.object(MODULE, "STATE_DATEI", "/var/lib/ortsnetz-e3dc/state.json"):
            self.assertEqual(MODULE.state_pfad(), "/var/lib/ortsnetz-e3dc/state.json")

    def test_fehtende_state_datei(self):
        staat = MODULE.staat_lesen(self.pfad)
        self.assertEqual(staat, {"last_send": None, "samples": []})

    def test_unlesbare_state_datei(self):
        pathlib.Path(self.pfad).write_text("kein json")
        patcher, zeilen = logfanger()
        with patcher:
            staat = MODULE.staat_lesen(self.pfad)
        self.assertEqual(staat, {"last_send": None, "samples": []})
        self.assertTrue(any("unlesbar" in z for z in zeilen))

    def test_roundtrip(self):
        MODULE.staat_schreiben(self.pfad, STICHPROBEN, ZEIT)
        staat = MODULE.staat_lesen(self.pfad)
        self.assertEqual(staat["last_send"], ZEIT)
        self.assertEqual([s[0] for s in staat["samples"]], [s[0] for s in STICHPROBEN])

    def test_ordner_wird_angelegt(self):
        pfad = str(pathlib.Path(self.ordner.name) / "neu" / "state.json")
        MODULE.staat_schreiben(pfad, [], None)
        self.assertTrue(pathlib.Path(pfad).is_file())
        self.assertEqual(oct(pathlib.Path(pfad).parent.stat().st_mode)[-3:], "700")

    def test_unvollstaendige_eintraege_werden_ignoriert(self):
        pathlib.Path(self.pfad).write_text(json.dumps(
            {"last_send": "zeit", "samples": [[ZEIT, 230.0], [ZEIT - 60, 230.0, 230.0, 230.0, 50.0], " Unsinn"]}))
        staat = MODULE.staat_lesen(self.pfad)
        self.assertEqual(staat["last_send"], None)
        self.assertEqual(len(staat["samples"]), 1)

    def test_atomar_ohne_temp_rest(self):
        MODULE.staat_schreiben(self.pfad, STICHPROBEN, ZEIT)
        self.assertFalse(pathlib.Path(self.pfad + ".tmp").exists())


class GatingTests(unittest.TestCase):
    def faellig(self, last_send, zeitpunkt):
        with patch.object(MODULE, "SENDINTERVALL_S", 300):
            return MODULE.senden_faellig(last_send, zeitpunkt)

    def test_erster_lauf(self):
        self.assertTrue(self.faellig(None, ZEIT))

    def test_intervall_abgelaufen(self):
        self.assertTrue(self.faellig(ZEIT - 300, ZEIT))

    def test_intervall_nicht_abgelaufen(self):
        self.assertFalse(self.faellig(ZEIT - 60, ZEIT))
        self.assertFalse(self.faellig(ZEIT - 299, ZEIT))


class PayloadTests(unittest.TestCase):
    def payload(self, daten, frequenz=None, **kw):
        fake = FakeE3DC(daten=daten, frequenz=frequenz, **kw)
        return protokollierter_lauf(daten, fake)

    def test_dreiphasig_mit_frequenz(self):
        payload = self.payload(dict(NETZ_ZAEHLER, frequency=50.02), leistung=-4200.0, soc=57)
        self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (230.15, 231.02, 229.85))
        self.assertEqual(payload["grid_frequency_hz"], 50.02)
        self.assertEqual(payload["grid_power_w"], -4200.0)
        self.assertEqual(payload["battery_soc_percent"], 57)
        self.assertEqual(payload["integration_version"], "e3dc-rscp-1.3")
        self.assertRegex(payload["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertNotIn("plant_capacity_kwp", payload)
        self.assertNotIn("battery_capacity", payload)

    def test_kennzahlen_aus_fuenf_stichproben(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=50.02), fenster=STICHPROBEN)
        self.assertEqual(payload["observed_at"], "2023-11-14T22:13:20Z")
        self.assertEqual((payload["l1_v_min"], payload["l1_v_max"], payload["l1_v_avg"]), (229.0, 231.5, 230.23))
        self.assertEqual((payload["l2_v_min"], payload["l2_v_max"], payload["l2_v_avg"]), (229.5, 232.0, 230.88))
        self.assertEqual((payload["grid_frequency_hz_min"], payload["grid_frequency_hz_max"],
                          payload["grid_frequency_hz_avg"]), (49.9, 50.1, 50.01))

    def test_kennzahlen_minus_1_fuer_nicht_gemessene_phase(self):
        daten = dict(NETZ_ZAEHLER, voltage={"L1": 230.0, "L2": 0, "L3": None})
        payload = protokollierter_lauf(daten, FakeE3DC(daten=daten, frequenz=50.02))
        self.assertEqual(payload["l2_v"], -1)
        self.assertEqual(payload["l2_v_min"], -1)
        self.assertEqual(payload["l2_v_max"], -1)
        self.assertEqual(payload["l2_v_avg"], -1)
        self.assertEqual(payload["l3_v_min"], -1)

    def test_frequenz_kennzahlen_ohne_gueltige_stichprobe(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None),
                                       fenster=[[ZEIT, 230.0, 230.0, 230.0, None]])
        self.assertNotIn("grid_frequency_hz", payload)
        self.assertNotIn("grid_frequency_hz_min", payload)
        self.assertNotIn("grid_frequency_hz_avg", payload)

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

    def test_pv_leistung_aus_konfiguration(self):
        daten = dict(NETZ_ZAEHLER)
        fake = FakeE3DC(daten=daten, frequenz=None, peak=12000)
        with patch.object(MODULE, "LATITUDE", 48.1), patch.object(MODULE, "LONGITUDE", 11.7), \
             patch.object(MODULE, "PLANT_CAPACITY_KWP", 9.8):
            payload = protokollierter_lauf(daten, fake)
        self.assertEqual(payload["plant_capacity_kwp"], 9.8, "Konfiguration hat Vorrang")

    def test_pv_leistung_automatisch(self):
        fake = FakeE3DC(frequenz=None, peak=9800)
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), fake)
        self.assertEqual(payload["plant_capacity_kwp"], 9.8)

    def test_batteriekapazitaet_aus_konfiguration(self):
        fake = FakeE3DC(frequenz=None, kapazitaet=12000)
        with patch.object(MODULE, "BATTERY_CAPACITY_KWH", 10.4):
            payload = protokollierter_lauf(dict(NETZ_ZAEHLER), fake)
        self.assertEqual(payload["battery_capacity"], 10.4, "Konfiguration hat Vorrang")

    def test_batteriekapazitaet_automatisch_als_naeherung(self):
        fake = FakeE3DC(frequenz=None, kapazitaet=10500)
        patcher, zeilen = logfanger()
        with patcher:
            payload = protokollierter_lauf(dict(NETZ_ZAEHLER), fake)
        self.assertEqual(payload["battery_capacity"], 10.5, "Wh werden zu kWh")

    def test_ohne_batterie(self):
        fake = FakeE3DC(frequenz=None, soc=None, kapazitaet=None)
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), fake)
        self.assertNotIn("battery_soc_percent", payload)
        self.assertNotIn("battery_capacity", payload)

    def test_soc_null_ist_gueltig(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, soc=0))
        self.assertEqual(payload["battery_soc_percent"], 0)

    def test_unplausibler_soc(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, soc=120))
        self.assertNotIn("battery_soc_percent", payload)

    def test_netzleistung_vorzeichen(self):
        # negativ = Einspeisung, positiv = Bezug, wie API.md Zeile 120
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, leistung=3500.0))
        self.assertEqual(payload["grid_power_w"], 3500.0)
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, leistung=-4200.0))
        self.assertEqual(payload["grid_power_w"], -4200.0)

    def test_unplausibile_netzleistung(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, leistung=-150000.0))
        self.assertNotIn("grid_power_w", payload)

    def test_netzleistung_keine_antwort(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, leistung=None))
        self.assertNotIn("grid_power_w", payload)

    def test_zaehlerbezeichnung_aus_modell_und_seriennummer(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None))
        self.assertEqual(payload["smartmeter_model"], "E3/DC S10_Mini 8800123456789")

    def test_zaehlerbezeichnung_override(self):
        fake = FakeE3DC(frequenz=None)
        with patch.object(MODULE, "SMARTMETER_MODEL", "E3/DC S10-Mini G3"):
            payload = protokollierter_lauf(dict(NETZ_ZAEHLER), fake)
        self.assertEqual(payload["smartmeter_model"], "E3/DC S10-Mini G3")

    def test_zaehlerbezeichnung_auswich(self):
        fake = FakeE3DC(frequenz=None, model=None, serial=None)
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), fake)
        self.assertEqual(payload["smartmeter_model"], "E3/DC Hauskraftwerk")

    def test_zaehlerbezeichnung_kuerzung(self):
        fake = FakeE3DC(frequenz=None, model="X" * 150, serial="1")
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), fake)
        self.assertEqual(len(payload["smartmeter_model"]), 120)

    def test_pv_prognose_im_payload(self):
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, peak=9800), forecast=24.5)
        self.assertEqual(payload["pv_forecast_kwh"], 24.5)

    def test_pv_prognose_wird_nur_mit_anlagengroesse_gelesen(self):
        # payload_erstellen vertraut der Grenze in pv_forecast_lesen, nicht hier
        befehl = f"{sys.executable} -c \"print('24.5')\""
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_BEFEHL", befehl):
            self.assertEqual(MODULE.pv_forecast_lesen(None), None, "ohne Anlagengröße verworfen")
            forecast = MODULE.pv_forecast_lesen(9.8)
        self.assertEqual(forecast, 24.5)
        payload = protokollierter_lauf(dict(NETZ_ZAEHLER), FakeE3DC(frequenz=None, peak=9800), forecast=forecast)
        self.assertEqual(payload["pv_forecast_kwh"], 24.5)


class PrognoseQuellenTests(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)

    def zahl_aus_text(self, text):
        return MODULE.zahl_aus_text(text)

    def test_zahl(self):
        self.assertEqual(self.zahl_aus_text("24.5"), 24.5)
        self.assertEqual(self.zahl_aus_text("24,5 kWh"), 24.5)
        self.assertEqual(self.zahl_aus_text("kein wert"), None)

    def test_json(self):
        self.assertEqual(self.zahl_aus_text('{"pv_forecast_kwh": 12.3}'), 12.3)
        self.assertEqual(self.zahl_aus_text('{"foo": 3}'), None)

    def test_datei(self):
        pfad = pathlib.Path(self.ordner.name) / "prognose.json"
        pfad.write_text('{"pv_forecast_kwh": 24.5}')
        with patch.object(MODULE, "PV_FORECAST_DATEI", str(pfad)):
            self.assertEqual(MODULE.pv_forecast_lesen(9.8), 24.5)

    def test_fehtende_datei(self):
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_DATEI", str(pathlib.Path(self.ordner.name) / "x")):
            self.assertEqual(MODULE.pv_forecast_lesen(9.8), None)
        self.assertTrue(any("nicht lesbar" in z for z in zeilen))

    def test_befehl(self):
        befehl = f"{sys.executable} -c \"print('24.5')\""
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_BEFEHL", befehl):
            self.assertEqual(MODULE.pv_forecast_lesen(9.8), 24.5)

    def test_befehl_scheitert(self):
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_BEFEHL", "/bin/nicht-vorhanden"):
            self.assertEqual(MODULE.pv_forecast_lesen(9.8), None)
        self.assertTrue(any("fehlgeschlagen" in z for z in zeilen))

    def test_grenze_10_kwh_je_kwp(self):
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_BEFEHL", f"{sys.executable} -c \"print('99')\""):
            self.assertEqual(MODULE.pv_forecast_lesen(9.8), None, "99 kWh über 98 kWh")
        self.assertTrue(any("überschreitet" in z for z in zeilen))

    def test_ohne_anlagengroesse(self):
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_BEFEHL", f"{sys.executable} -c \"print('24.5')\""):
            self.assertEqual(MODULE.pv_forecast_lesen(None), None, "API antwortet 422 ohne Anlagengröße")
        self.assertTrue(any("422" in z for z in zeilen))

    def test_keine_quelle(self):
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_DATEI", ""), patch.object(MODULE, "PV_FORECAST_BEFEHL", ""):
            self.assertEqual(MODULE.pv_forecast_lesen(9.8), None)
        self.assertEqual(zeilen, [], "ohne Quelle wird nicht gewarnt")


def sensorantwort(state, einheit="kWh", alter=0, entity="sensor.pv_prognose"):
    """Liefert eine Home-Assistant-Sensorantwort wie /api/states; alter in Sekunden seit jetzt."""
    zeit = datetime.fromtimestamp(ZEIT - alter, timezone.utc).isoformat()
    attributes = {"friendly_name": "PV-Prognose"}
    if einheit is not None:
        attributes["unit_of_measurement"] = einheit
    return {"entity_id": entity, "state": state, "attributes": attributes,
            "last_updated": zeit, "last_reported": zeit}


def ha_abruf(antworten, aufzeichnungen=None):
    """urllib.request.urlopen-Ersatz für die Home-Assistant-Abfrage, eine Antwort je Aufruf."""
    vorrat = list(antworten)

    def abfrage(anfrage, timeout=None):
        if aufzeichnungen is not None:
            aufzeichnungen.append(anfrage)
        if not vorrat:
            raise urllib.error.URLError("keine Antwort")
        antwort = vorrat.pop(0)
        if isinstance(antwort, urllib.error.HTTPError):
            raise antwort
        return FakeAntwort(200, json.dumps(antwort))

    return abfrage


class HomeAssistantTests(unittest.TestCase):
    URL = "http://192.168.60.10:8123"
    TOKEN = "langlebigertoken"
    ENTITY = "sensor.pv_prognose"

    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)

    def lesen(self, antworten, kapazitaet=9.8, entity=ENTITY, max_age=3600,
              weitere=None, aufzeichnungen=None, url=None):
        """Liefert (pv_forecast_kwh, Logzeilen) für die angegebenen Sensorantworten."""
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_HA_URL", url or self.URL), \
             patch.object(MODULE, "PV_FORECAST_HA_TOKEN", self.TOKEN), \
             patch.object(MODULE, "PV_FORECAST_HA_ENTITY", entity), \
             patch.object(MODULE, "PV_FORECAST_MAX_AGE_S", max_age), \
             patch.object(MODULE, "jetzt", lambda: ZEIT), \
             patch("urllib.request.urlopen", side_effect=ha_abruf(antworten, aufzeichnungen)):
            for name, wert in (weitere or {}).items():
                patcher2 = patch.object(MODULE, name, wert)
                patcher2.start()
                self.addCleanup(patcher2.stop)
            return MODULE.pv_forecast_lesen(kapazitaet), zeilen

    def test_sensor_kwh(self):
        wert, zeilen = self.lesen([sensorantwort("24.5")])
        self.assertEqual(wert, 24.5)
        self.assertEqual(zeilen, [], "gültiger Sensor wird nicht beanstandet")

    def test_sensor_zahl_als_float(self):
        wert, _ = self.lesen([sensorantwort(24.5)])
        self.assertEqual(wert, 24.5)

    def test_einheit_wh(self):
        wert, _ = self.lesen([sensorantwort("24500", einheit="Wh")])
        self.assertEqual(wert, 24.5)

    def test_einheit_mwh(self):
        wert, _ = self.lesen([sensorantwort("0.0245", einheit="MWh")])
        self.assertEqual(wert, 24.5)

    def test_einheit_fehlt(self):
        wert, zeilen = self.lesen([sensorantwort("24.5", einheit=None)])
        self.assertEqual(wert, None, "ohne unit_of_measurement wird nicht geraten")
        self.assertTrue(any("Energieeinheit" in z for z in zeilen))

    def test_einheit_watt(self):
        wert, zeilen = self.lesen([sensorantwort("24500", einheit="W")])
        self.assertEqual(wert, None, "Leistung statt Energie wird nicht umgerechnet")
        self.assertTrue(any("Energieeinheit" in z for z in zeilen))

    def test_unavailable(self):
        wert, zeilen = self.lesen([sensorantwort("unavailable")])
        self.assertEqual(wert, None)
        self.assertTrue(any("keine Zahl" in z for z in zeilen))

    def test_veralteter_sensor(self):
        wert, zeilen = self.lesen([sensorantwort("24.5", alter=7200)], max_age=3600)
        self.assertEqual(wert, None, "Abendwert bleibt nachts stehen und darf nicht gesendet werden")
        self.assertTrue(any("s alt" in z for z in zeilen))

    def test_max_age_null_deaktiviert(self):
        wert, zeilen = self.lesen([sensorantwort("24.5", alter=100000)], max_age=0)
        self.assertEqual(wert, 24.5)
        self.assertEqual(zeilen, [], "max_age 0 prüft das Alter nicht")

    def test_last_reported_vor_last_updated(self):
        antwort = sensorantwort("24.5", alter=7200)
        antwort["last_updated"] = datetime.fromtimestamp(ZEIT - 7200, timezone.utc).isoformat()
        antwort["last_reported"] = datetime.fromtimestamp(ZEIT, timezone.utc).isoformat()
        wert, _ = self.lesen([antwort])
        self.assertEqual(wert, 24.5, "last_reported ist der maßgebliche Zeitstempel")

    def test_ohne_zeitangabe(self):
        antwort = sensorantwort("24.5")
        antwort.pop("last_reported")
        antwort.pop("last_updated")
        wert, zeilen = self.lesen([antwort])
        self.assertEqual(wert, None)
        self.assertTrue(any("Alter nicht prüfbar" in z for z in zeilen))

    def test_zwei_sensoren_summe(self):
        wert, _ = self.lesen([sensorantwort("10.0", entity="sensor.pv_sud"),
                              sensorantwort("5.5", entity="sensor.pv_west")],
                             entity="sensor.pv_sud,sensor.pv_west")
        self.assertEqual(wert, 15.5)

    def test_zwei_sensoren_einer_unavailable(self):
        wert, zeilen = self.lesen([sensorantwort("unavailable", entity="sensor.pv_sud"),
                                   sensorantwort("5.5", entity="sensor.pv_west")],
                                  entity="sensor.pv_sud,sensor.pv_west")
        self.assertEqual(wert, 5.5, "ein Ausfall überspringt nur diesen Sensor")

    def test_url_und_token(self):
        aufzeichnungen = []
        wert, _ = self.lesen([sensorantwort("24.5")], aufzeichnungen=aufzeichnungen)
        self.assertEqual(wert, 24.5)
        anfrage = aufzeichnungen[0]
        self.assertEqual(anfrage.full_url, self.URL + "/api/states/sensor.pv_prognose")
        self.assertEqual(anfrage.headers["Authorization"], "Bearer " + self.TOKEN)

    def test_url_mit_schraegstrich(self):
        aufzeichnungen = []
        self.lesen([sensorantwort("24.5")], aufzeichnungen=aufzeichnungen, url=self.URL + "/")
        anfrage = aufzeichnungen[0]
        self.assertEqual(anfrage.full_url, self.URL + "/api/states/sensor.pv_prognose")
        self.assertNotIn("//api", anfrage.full_url, "doppelter Schrägstrich vermieden")

    def test_401(self):
        wert, zeilen = self.lesen([http_fehler(401, "Unauthorized")])
        self.assertEqual(wert, None, "Sensorausfall darf die Messung nicht blockieren")
        self.assertTrue(any("nicht abrufbar" in z for z in zeilen))

    def test_403(self):
        wert, zeilen = self.lesen([http_fehler(403, "Forbidden")])
        self.assertEqual(wert, None)
        self.assertTrue(any("nicht abrufbar" in z for z in zeilen))

    def test_verbindungsabbruch(self):
        wert, zeilen = self.lesen([urllib.error.URLError("keine Route")])
        self.assertEqual(wert, None)
        self.assertTrue(any("nicht abrufbar" in z for z in zeilen))

    def test_ohne_sensorobjekt(self):
        wert, zeilen = self.lesen([[1, 2, 3]])
        self.assertEqual(wert, None)
        self.assertTrue(any("ohne Sensorobjekt" in z for z in zeilen))

    def test_vorrang_ha_vor_datei(self):
        pfad = pathlib.Path(self.ordner.name) / "prognose.json"
        pfad.write_text('{"pv_forecast_kwh": 50}')
        wert, _ = self.lesen([sensorantwort("24.5")], weitere={"PV_FORECAST_DATEI": str(pfad)})
        self.assertEqual(wert, 24.5, "Home Assistant wird zuerst gelesen")

    def test_datei_wenn_sensor_unavailable(self):
        pfad = pathlib.Path(self.ordner.name) / "prognose.json"
        pfad.write_text('{"pv_forecast_kwh": 12.3}')
        wert, _ = self.lesen([sensorantwort("unavailable")], weitere={"PV_FORECAST_DATEI": str(pfad)})
        self.assertEqual(wert, 12.3, "Ausfall fällt auf die Datei zurück")

    def test_keine_quelle_keine_abfrage(self):
        patcher, zeilen = logfanger()
        with patcher, patch.object(MODULE, "PV_FORECAST_HA_ENTITY", ""), \
             patch.object(MODULE, "PV_FORECAST_DATEI", ""), \
             patch.object(MODULE, "PV_FORECAST_BEFEHL", ""), \
             patch("urllib.request.urlopen", side_effect=AssertionError("HA wird nicht abgerufen")):
            self.assertEqual(MODULE.pv_forecast_lesen(9.8), None)
        self.assertEqual(zeilen, [], "ohne Quelle wird nicht gewarnt")

    def test_grenze_10_kwh_je_kwp(self):
        wert, zeilen = self.lesen([sensorantwort("99")], kapazitaet=9.8)
        self.assertEqual(wert, None, "99 kWh über 98 kWh")
        self.assertTrue(any("überschreitet" in z for z in zeilen))

    def test_ohne_anlagengroesse(self):
        wert, zeilen = self.lesen([sensorantwort("24.5")], kapazitaet=None)
        self.assertEqual(wert, None, "API antwortet 422 ohne Anlagengröße")
        self.assertTrue(any("422" in z for z in zeilen))

    def test_iso_zeit_mit_z(self):
        self.assertEqual(MODULE.zeitpunkt_aus_iso("2026-11-04T08:00:00Z"),
                         int(datetime(2026, 11, 4, 8, 0, 0, tzinfo=timezone.utc).timestamp()))

    def test_iso_zeit_ohne_zona(self):
        self.assertEqual(MODULE.zeitpunkt_aus_iso("2026-11-04T08:00:00"),
                         int(datetime(2026, 11, 4, 8, 0, 0, tzinfo=timezone.utc).timestamp()))

    def test_iso_zeit_unlesbar(self):
        self.assertEqual(MODULE.zeitpunkt_aus_iso("nicht datiert"), None)
        self.assertEqual(MODULE.zeitpunkt_aus_iso(None), None)


class AntwortTests(unittest.TestCase):
    def werten(self, antwort):
        patcher, zeilen = logfanger()
        with patcher:
            MODULE.antwort_auswerten(antwort)
        return zeilen

    def test_ampel_und_empfehlung(self):
        zeilen = self.werten({"accepted": True, "status": {"l1": "normal", "l2": "normal", "l3": "normal",
                                                           "overall": "green"},
                              "storage_recommendation": "charge"})
        self.assertTrue(any("Ampel" in z and "l1=normal" in z and "green" in z for z in zeilen))
        self.assertTrue(any("Speicherladeempfehlung: charge" in z for z in zeilen))

    def test_redispatch(self):
        zeilen = self.werten({"redispatch": {"active": True, "affected_units": 2,
                                             "active_measures": [], "data_updated_at": "2026-09-15T08:00:00Z"}})
        self.assertTrue(any("Redispatch" in z and "active=True" in z for z in zeilen))

    def test_fehtende_felder_toleriert(self):
        zeilen = self.werten({"accepted": True})
        self.assertEqual(zeilen, [])

    def test_202_mit_antwortfeldern(self):
        patcher, zeilen = logfanger()
        with patch("urllib.request.urlopen", return_value=FakeAntwort(
                202, '{"accepted": true, "status": {"overall": "green"}, "storage_recommendation": "discharge"}')), \
             patcher:
            MODULE.senden({"observed_at": "2026-09-15T08:00:00Z"})
        self.assertTrue(any("Ampel" in z for z in zeilen))
        self.assertTrue(any("Speicherladeempfehlung: discharge" in z for z in zeilen))


class KonfigurationTests(unittest.TestCase):
    def setUp(self):
        for name, wert in (("E3DC_HOST", ""), ("E3DC_USERNAME", ""), ("E3DC_PASSWORD", ""),
                           ("RSCP_KEY", ""), ("LATITUDE", None), ("LONGITUDE", None),
                           ("METER_INDEX", None), ("PLANT_CAPACITY_KWP", None),
                           ("BATTERY_CAPACITY_KWH", None), ("PV_FORECAST_HA_URL", ""),
                           ("PV_FORECAST_HA_TOKEN", ""), ("PV_FORECAST_HA_ENTITY", ""),
                           ("PV_FORECAST_MAX_AGE_S", 3600), ("PV_FORECAST_DATEI", ""),
                           ("PV_FORECAST_BEFEHL", ""), ("SMARTMETER_MODEL", ""),
                           ("STATE_DATEI", ""), ("SENDINTERVALL_S", 300), ("ENV_DATEI", None)):
            patcher = patch.object(MODULE, name, wert)
            patcher.start()
            self.addCleanup(patcher.stop)

    def umgebung_laden(self, **anderungen):
        with patch.dict("os.environ", umgebung(), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            MODULE.konfiguration_pruefen()

    def test_umgebungsvariablen(self):
        self.umgebung_laden()
        self.assertEqual(MODULE.E3DC_HOST, "192.168.60.220")
        self.assertEqual(MODULE.METER_INDEX, None)
        self.assertEqual(MODULE.SENDINTERVALL_S, 300)

    def test_neue_variablen(self):
        erwartung = {"BATTERY_CAPACITY_KWH": 10.4, "PV_FORECAST_DATEI": "/tmp/p.json",
                     "PV_FORECAST_BEFEHL": "echo 1", "SMARTMETER_MODEL": "S10-Mini G3",
                     "STATE_DATEI": "/tmp/s.json", "SENDINTERVALL_S": 300}
        for name, wert in erwartung.items():
            with patch.dict("os.environ", umgebung(**{name: str(wert)}), clear=True):
                MODULE.env_datei_laden()
                MODULE.konfiguration_laden()
                MODULE.konfiguration_pruefen()
            self.assertEqual(getattr(MODULE, name), wert, name)

    def test_env_datei(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = pathlib.Path(ordner) / ".env"
            pfad.write_text(
                "# Kommentar\nE3DC_HOST=10.0.0.9\nE3DC_USERNAME='quoted@example.com'\n"
                "E3DC_PASSWORD=\"passwort\"\nRSCP_KEY=key\nLATITUDE=52.52\nLONGITUDE=13.4\nMETER_INDEX=2\n"
                "BATTERY_CAPACITY_KWH=10.4\n"
            )
            with patch.dict("os.environ", umgebung(), clear=True):
                MODULE.env_datei_laden(str(pfad))
                MODULE.konfiguration_laden()
                MODULE.konfiguration_pruefen()
            # Gesetzte Environment-Variablen haben Vorrang vor der Datei
            self.assertEqual(MODULE.E3DC_HOST, "192.168.60.220")
            self.assertEqual(MODULE.METER_INDEX, 2)
            # Nicht gesetzte Werte werden aus der Datei ergänzt
            self.assertEqual(MODULE.BATTERY_CAPACITY_KWH, 10.4)

    def test_env_datei_ergaenzt_leere_werte(self):
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

    def test_batteriekapazitaet_ausserhalb_bereich(self):
        with patch.dict("os.environ", umgebung(BATTERY_CAPACITY_KWH="0"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler):
                MODULE.konfiguration_pruefen()

    def test_sendeintervall_zu_kurz(self):
        with patch.dict("os.environ", umgebung(SENDINTERVALL_S="60"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler) as fehler:
                MODULE.konfiguration_pruefen()
        self.assertIn("300", str(fehler.exception))

    def test_ha_prognose(self):
        with patch.dict("os.environ", umgebung(PV_FORECAST_HA_URL="http://192.168.60.10:8123",
                                               PV_FORECAST_HA_TOKEN="token",
                                               PV_FORECAST_HA_ENTITY="sensor.pv_sud,sensor.pv_west"),
                        clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            MODULE.konfiguration_pruefen()
        self.assertEqual(MODULE.PV_FORECAST_HA_ENTITY, "sensor.pv_sud,sensor.pv_west")
        self.assertEqual(MODULE.PV_FORECAST_MAX_AGE_S, 3600, "Standardalter")

    def test_ha_entity_ohne_url(self):
        with patch.dict("os.environ", umgebung(PV_FORECAST_HA_ENTITY="sensor.pv_prognose"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler) as fehler:
                MODULE.konfiguration_pruefen()
        self.assertIn("http://", str(fehler.exception))

    def test_ha_url_ohne_schema(self):
        with patch.dict("os.environ", umgebung(PV_FORECAST_HA_URL="192.168.60.10:8123",
                                               PV_FORECAST_HA_TOKEN="token",
                                               PV_FORECAST_HA_ENTITY="sensor.pv_prognose"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler):
                MODULE.konfiguration_pruefen()

    def test_ha_token_fehlt(self):
        with patch.dict("os.environ", umgebung(PV_FORECAST_HA_URL="http://192.168.60.10:8123",
                                               PV_FORECAST_HA_ENTITY="sensor.pv_prognose"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler) as fehler:
                MODULE.konfiguration_pruefen()
        self.assertIn("PV_FORECAST_HA_TOKEN", str(fehler.exception))

    def test_ha_entity_ohne_punkt(self):
        with patch.dict("os.environ", umgebung(PV_FORECAST_HA_URL="http://192.168.60.10:8123",
                                               PV_FORECAST_HA_TOKEN="token",
                                               PV_FORECAST_HA_ENTITY="pv_prognose"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler) as fehler:
                MODULE.konfiguration_pruefen()
        self.assertIn("sensor.name", str(fehler.exception))

    def test_max_age_negativ(self):
        with patch.dict("os.environ", umgebung(PV_FORECAST_MAX_AGE_S="-1"), clear=True):
            MODULE.env_datei_laden()
            MODULE.konfiguration_laden()
            with self.assertRaises(MODULE.KonfigurationsFehler):
                MODULE.konfiguration_pruefen()


class SendeTests(unittest.TestCase):
    payload = {"observed_at": "2026-09-15T08:00:00Z", "latitude": 48.1, "longitude": 11.7,
               "l1_v": 230.0, "l2_v": 230.0, "l3_v": 230.0,
               "smartmeter_model": "E3DC Hauskraftwerk", "integration_version": "e3dc-rscp-1.3"}

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
                           ("METER_INDEX", None), ("PLANT_CAPACITY_KWP", None),
                           ("BATTERY_CAPACITY_KWH", None), ("PV_FORECAST_HA_URL", ""),
                           ("PV_FORECAST_HA_TOKEN", ""), ("PV_FORECAST_HA_ENTITY", ""),
                           ("PV_FORECAST_MAX_AGE_S", 3600), ("PV_FORECAST_DATEI", ""),
                           ("PV_FORECAST_BEFEHL", ""), ("SMARTMETER_MODEL", ""),
                           ("SENDINTERVALL_S", 300), ("ENV_DATEI", None)):
            patcher = patch.object(MODULE, name, wert)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)
        self.pfad = str(pathlib.Path(self.ordner.name) / "state.json")
        patcher = patch.object(MODULE, "STATE_DATEI", self.pfad)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.zeit = [ZEIT]
        patcher = patch.object(MODULE, "jetzt", lambda: self.zeit[0])
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

    def last_send(self):
        return MODULE.staat_lesen(self.pfad)["last_send"]

    def test_erfolg(self):
        fake = FakeE3DC(frequenz=50.01)
        gesendet = []
        self.assertEqual(self.main(fake, gesendet=gesendet), 0)
        self.assertEqual(fake.used_index, 1, "Netzzähler an Index 1, nicht powermeters[0]")
        self.assertEqual(gesendet[0]["grid_frequency_hz"], 50.01)
        self.assertEqual(gesendet[0]["grid_power_w"], -4200.0)
        self.assertEqual(gesendet[0]["battery_soc_percent"], 57)
        self.assertTrue(fake.getrennt, "Verbindung wird getrennt")
        self.assertEqual(self.last_send(), ZEIT, "Sendezeitpunkt wird gespeichert")

    def test_gating_alle_fuenf_laeufe(self):
        # Minutentakt: gesendet wird erst nach 300 s, das Sendeintervall bleibt 300 s
        gesendet = []
        for minute in range(6):
            self.zeit[0] = ZEIT + minute * 60
            self.assertEqual(self.main(FakeE3DC(frequenz=50.0), gesendet=gesendet), 0)
        self.assertEqual(len(gesendet), 2, "Sendungen bei Minute 0 und 5")

    def test_stichproben_sammeln_kennzahlen(self):
        gesendet = []
        for minute in range(6):
            self.zeit[0] = ZEIT + minute * 60
            daten = dict(NETZ_ZAEHLER)
            daten["voltage"] = {"L1": 229.0 + minute, "L2": 230.0, "L3": 230.0}
            self.assertEqual(self.main(FakeE3DC(daten=daten, frequenz=50.0 + minute / 100), gesendet=gesendet), 0)
        payload = gesendet[-1]
        self.assertEqual(payload["l1_v_min"], 229.0)
        self.assertEqual(payload["l1_v_max"], 234.0)
        self.assertEqual(payload["l1_v_avg"], 231.5)
        self.assertEqual(payload["grid_frequency_hz_min"], 50.0)
        self.assertEqual(payload["grid_frequency_hz_max"], 50.05)

    def test_state_datei_zwischen_laeufen(self):
        for minute in range(3):
            self.zeit[0] = ZEIT + minute * 60
            self.main(FakeE3DC(frequenz=50.0))
        proben = MODULE.staat_lesen(self.pfad)["samples"]
        self.assertEqual([s[0] for s in proben], [ZEIT, ZEIT + 60, ZEIT + 120])

    def test_sendefehler_behaelt_letzte_stichprobe(self):
        def sender(payload):
            raise MODULE.ApiFehler("HTTP 422 – Payload abgelehnt")

        fake = FakeE3DC(frequenz=50.0)
        with patch.object(MODULE, "E3DC", zaehler_constructor(fake)), \
             patch.object(MODULE, "senden", sender), \
             patch.dict("os.environ", umgebung(), clear=True):
            self.addCleanup(signal.alarm, 0)
            self.assertEqual(MODULE.main([]), MODULE.EXIT_API)
        self.assertEqual([s[0] for s in MODULE.staat_lesen(self.pfad)["samples"]], [ZEIT],
                         "Stichprobe bleibt erhalten")
        self.assertEqual(self.last_send(), None, "ohne Annahme wird das Intervall nicht neu gesetzt")

    def test_dry_run(self):
        fake = FakeE3DC(frequenz=50.0)
        gesendet = []
        self.assertEqual(self.main(fake, ["--dry-run"], gesendet=gesendet), 0)
        self.assertEqual(gesendet, [], "--dry-run sendet nichts")
        self.assertFalse(pathlib.Path(self.pfad).exists(), "--dry-run schreibt die State-Datei nicht")

    def test_ha_ausfall_sendet_messung(self):
        # Sensor nicht erreichbar: Warnung im Log, die Messung wird trotzdem übertragen
        fake = FakeE3DC(frequenz=50.01, peak=9800)
        gesendet = []
        with patch.object(MODULE, "PV_FORECAST_HA_URL", "http://192.168.60.10:8123"), \
             patch.object(MODULE, "PV_FORECAST_HA_TOKEN", "token"), \
             patch.object(MODULE, "PV_FORECAST_HA_ENTITY", "sensor.pv_prognose"), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("keine Route")):
            self.assertEqual(self.main(fake, gesendet=gesendet), 0)
        self.assertEqual(gesendet[0]["l1_v"], 230.15, "Messung wird übertragen")
        self.assertNotIn("pv_forecast_kwh", gesendet[0], "Feld wird weggelassen")

    def test_ha_prognose_im_hauptlauf(self):
        fake = FakeE3DC(frequenz=50.01, peak=9800)
        antwort = sensorantwort("24.5")
        gesendet = []
        with patch.object(MODULE, "PV_FORECAST_HA_URL", "http://192.168.60.10:8123"), \
             patch.object(MODULE, "PV_FORECAST_HA_TOKEN", "token"), \
             patch.object(MODULE, "PV_FORECAST_HA_ENTITY", "sensor.pv_prognose"), \
             patch("urllib.request.urlopen", side_effect=ha_abruf([antwort])):
            self.assertEqual(self.main(fake, gesendet=gesendet), 0)
        self.assertEqual(gesendet[0]["pv_forecast_kwh"], 24.5)

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
