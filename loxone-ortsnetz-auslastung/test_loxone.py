import base64
import http.server
import importlib.util
import json
import pathlib
import threading
import unittest
import urllib.parse
from datetime import datetime, timezone
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).with_name("ortsnetz_loxone.py")
SPEC = importlib.util.spec_from_file_location("ortsnetz_loxone", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# Antworten eines Miniservers auf GET /jdev/sps/io/<Name> (Werte mit Einheit, wie der Webservice sie liefert)
WERTE = {
    "L1 voltage": ("200", "237.68 V"),
    "L2 voltage": ("200", "237.07 V"),
    "L3 voltage": ("200", "236.92 V"),
    "Grid frequency": ("200", "49.98 Hz"),
    "L1 current": ("200", "-2.04 A"),
    "Power factor": ("200", "-0.647"),
    "grid_power": ("200", "-1.25"),
    "[ESS]Battery SOC": ("200", "55,1 %"),
    "VC_today": ("200", "35.8 kWh"),
    "Ohne Rechte": ("403", ""),
}
BENUTZER, PASSWORT = "ortsnetz", "geheim"


class Miniserver(http.server.BaseHTTPRequestHandler):
    werte = WERTE
    posts = []

    def log_message(self, *args):
        pass

    def antworten(self, status, daten):
        body = json.dumps(daten).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        erwartet = "Basic " + base64.b64encode(f"{BENUTZER}:{PASSWORT}".encode()).decode()
        if self.headers.get("Authorization") != erwartet:
            self.antworten(401, {})
            return
        name = urllib.parse.unquote(self.path[len("/jdev/sps/io/"):])
        code, wert = self.werte.get(name, ("404", ""))
        self.antworten(200, {"LL": {"control": f"dev/sps/io/{name}", "value": wert, "Code": code}})

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length", "0"))
        Miniserver.posts.append(json.loads(self.rfile.read(laenge)))
        self.antworten(202, {"accepted": True, "status": {"overall": "green"}})


class MitServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Miniserver)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.host = f"127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Miniserver.posts = []
        werte = {
            "LOXONE_HOST": self.host, "LOXONE_USER": BENUTZER, "LOXONE_PASSWORD": PASSWORT,
            "LATITUDE": 52.52, "LONGITUDE": 13.4, "NAME_L1": "L1 voltage", "NAME_L2": "L2 voltage",
            "NAME_L3": "L3 voltage", "NAME_FREQUENZ": "", "NAME_STROM_L1": "", "NAME_LEISTUNGSFAKTOR": "",
            "NAME_NETZLEISTUNG": "", "NAME_SOC": "", "NETZLEISTUNG_FAKTOR": 1.0, "PLANT_CAPACITY_KWP": None,
            "NAME_PV_PROGNOSE": "", "BATTERY_CAPACITY_KWH": None,
            "API_URL": f"http://{self.host}/v1/measurements",
        }
        for name, wert in werte.items():
            patcher = patch.object(MODULE, name, wert)
            patcher.start()
            self.addCleanup(patcher.stop)


class LesenTests(MitServer):
    def test_wert_mit_einheit_und_basic_auth(self):
        self.assertEqual(MODULE.loxone_lesen("L1 voltage"), 237.68)
        self.assertEqual(MODULE.loxone_lesen("[ESS]Battery SOC"), 55.1, "Name mit Klammern, Dezimalkomma")

    def test_403_nennt_die_rechte(self):
        with self.assertRaises(MODULE.MesswertFehler) as fehler:
            MODULE.loxone_lesen("Ohne Rechte")
        self.assertIn("keine Rechte", str(fehler.exception))

    def test_404_nennt_die_bezeichnung(self):
        with self.assertRaises(MODULE.MesswertFehler) as fehler:
            MODULE.loxone_lesen("Gibt es nicht")
        self.assertIn("404", str(fehler.exception))

    def test_falsches_passwort(self):
        with patch.object(MODULE, "LOXONE_PASSWORD", "falsch"):
            with self.assertRaises(MODULE.MesswertFehler) as fehler:
                MODULE.loxone_lesen("L1 voltage")
        self.assertIn("401", str(fehler.exception))
        self.assertNotIn("falsch", str(fehler.exception), "das Passwort steht in keiner Meldung")

    def test_zahl_aus_text(self):
        for text, erwartet in (("237.68 V", 237.68), ("0.647", 0.647), ("-1.25", -1.25), ("55,1 %", 55.1),
                               ("", None), ("aus", None), (None, None)):
            self.assertEqual(MODULE.wert_aus_text(text), erwartet, text)


class PayloadTests(MitServer):
    def test_dreiphasig_ohne_optionale_werte(self):
        payload = MODULE.payload_erstellen([MODULE.probe_nehmen()])
        self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (237.68, 237.07, 236.92))
        for feld in ("grid_frequency_hz", "l1_a", "power_factor", "grid_power_w", "battery_soc_percent",
                     "plant_capacity_kwp", "pv_forecast_kwh", "battery_capacity", "l1_v_min"):
            self.assertNotIn(feld, payload)
        self.assertRegex(payload["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(payload["integration_version"], "loxone-0.1.0")

    def test_einphasig_setzt_minus_eins(self):
        with patch.object(MODULE, "NAME_L2", ""), patch.object(MODULE, "NAME_L3", ""):
            payload = MODULE.payload_erstellen([MODULE.probe_nehmen()])
        self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (237.68, -1, -1))

    def test_optionale_werte_umgerechnet(self):
        with patch.object(MODULE, "NAME_FREQUENZ", "Grid frequency"), \
                patch.object(MODULE, "NAME_STROM_L1", "L1 current"), \
                patch.object(MODULE, "NAME_LEISTUNGSFAKTOR", "Power factor"), \
                patch.object(MODULE, "NAME_NETZLEISTUNG", "grid_power"), \
                patch.object(MODULE, "NETZLEISTUNG_FAKTOR", 1000.0), \
                patch.object(MODULE, "NAME_SOC", "[ESS]Battery SOC"):
            payload = MODULE.payload_erstellen([MODULE.probe_nehmen()])
        self.assertEqual(payload["grid_frequency_hz"], 49.98)
        self.assertEqual(payload["l1_a"], 2.04, "Effektivwert, nie negativ")
        self.assertEqual(payload["power_factor"], 0.647, "Betrag")
        self.assertEqual(payload["grid_power_w"], -1250, "kW -> W, Einspeisung negativ")
        self.assertEqual(payload["battery_soc_percent"], 55.1)

    def test_pv_prognose_mit_anlagengroesse_und_speicherkapazitaet(self):
        with patch.object(MODULE, "NAME_PV_PROGNOSE", "VC_today"), \
                patch.object(MODULE, "PLANT_CAPACITY_KWP", 22.61), \
                patch.object(MODULE, "BATTERY_CAPACITY_KWH", 16.12):
            payload = MODULE.payload_erstellen([MODULE.probe_nehmen()])
        self.assertEqual(payload["pv_forecast_kwh"], 35.8)
        self.assertEqual(payload["plant_capacity_kwp"], 22.61, "die Anlagengröße geht mit, sonst 422")
        self.assertEqual(payload["battery_capacity"], 16.12)
        self.assertNotIn("pv_forecast_kwh_min", MODULE.payload_erstellen(
            [dict(zeit=datetime(2026, 10, 27, tzinfo=timezone.utc), l1_v=237.0, l2_v=-1, l3_v=-1,
                  pv_forecast_kwh=35.8)], kennzahlen=True), "eine Tagesprognose bekommt keine Kennzahlen")

    def test_pv_prognose_ueber_10_kwh_je_kwp_fehlt_nur(self):
        # die API lehnt sonst die GANZE Messung mit 422 ab
        with patch.object(MODULE, "NAME_PV_PROGNOSE", "VC_today"), \
                patch.object(MODULE, "PLANT_CAPACITY_KWP", 3.0), patch.object(MODULE, "log") as log:
            payload = MODULE.payload_erstellen([MODULE.probe_nehmen()])
        self.assertNotIn("pv_forecast_kwh", payload)
        self.assertEqual(payload["l1_v"], 237.68)
        self.assertTrue(any("VC_today" in str(a.args[0]) for a in log.call_args_list))

    def test_ein_fehlender_optionaler_wert_fehlt_nur(self):
        with patch.object(MODULE, "NAME_FREQUENZ", "Ohne Rechte"), patch.object(MODULE, "log"):
            payload = MODULE.payload_erstellen([MODULE.probe_nehmen()])
        self.assertNotIn("grid_frequency_hz", payload)
        self.assertEqual(payload["l1_v"], 237.68)

    def test_unplausible_spannung_verwirft_die_probe(self):
        with patch.dict(Miniserver.werte, {"L1 voltage": ("200", "0.0 V")}):
            with self.assertRaises(MODULE.MesswertFehler):
                MODULE.probe_nehmen()

    def test_kennzahlen_ueber_das_intervall(self):
        zeit = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
        proben = [dict(zeit=zeit, l1_v=v1, l2_v=230.0, l3_v=-1, grid_frequency_hz=f)
                  for v1, f in ((236.0, 50.01), (238.0, 49.97), (237.0, 50.0))]
        payload = MODULE.payload_erstellen(proben, kennzahlen=True)
        self.assertEqual(payload["l1_v"], 237.0, "die letzte Probe ist die Messung")
        self.assertEqual((payload["l1_v_min"], payload["l1_v_avg"], payload["l1_v_max"]), (236.0, 237.0, 238.0))
        self.assertEqual((payload["grid_frequency_hz_min"], payload["grid_frequency_hz_max"]), (49.97, 50.01))
        self.assertNotIn("l3_v_min", payload, "eine nicht gemessene Phase bekommt keine Kennzahlen")
        for feld in ("l1_v", "l2_v", "grid_frequency_hz"):
            self.assertLessEqual(payload[f"{feld}_min"], payload[f"{feld}_avg"])
            self.assertLessEqual(payload[f"{feld}_avg"], payload[f"{feld}_max"])

    def test_ohne_probe_kein_payload(self):
        with self.assertRaises(MODULE.MesswertFehler):
            MODULE.payload_erstellen([])


class DauerbetriebTests(MitServer):
    def test_sendet_an_der_intervallgrenze_mit_kennzahlen(self):
        jetzt = [1792998000.0 + 280]    # 20 s vor einer 5-Minuten-Grenze

        def schlafen(sekunden):
            jetzt[0] += sekunden
        with patch.object(MODULE, "ABTAST_S", 10.0), patch.object(MODULE, "log"):
            MODULE.dauerbetrieb(uhr=lambda: jetzt[0], schlafen=schlafen, runden=2)
        self.assertEqual(2, len(Miniserver.posts))
        erste, zweite = Miniserver.posts
        self.assertEqual(erste["l1_v_min"], 237.68)
        self.assertIn("l1_v_avg", zweite)
        self.assertEqual(jetzt[0], 1792998000.0 + 300 + 300 + 10, "die zweite Grenze 5 min nach der ersten")

    def test_ein_leeres_intervall_sendet_nichts(self):
        jetzt = [1792998000.0 + 295]
        with patch.dict(Miniserver.werte, {"L1 voltage": ("403", "")}), patch.object(MODULE, "log") as log:
            MODULE.dauerbetrieb(uhr=lambda: jetzt[0], schlafen=lambda s: jetzt.__setitem__(0, jetzt[0] + s),
                                runden=1)
        self.assertEqual([], Miniserver.posts)
        self.assertTrue(any("keine gültige Probe" in str(a.args[0]) for a in log.call_args_list))


class EinstellungTests(unittest.TestCase):
    def test_environment_hat_vorrang(self):
        umgebung = {"LOXONE_HOST": "ms.local", "LATITUDE": "48.1", "LONGITUDE": "11.5", "NAME_L1": "L1 voltage",
                    "LOXONE_PASSWORD": "pw", "INTERVALL_S": "300", "NETZLEISTUNG_FAKTOR": "1000",
                    "NAME_PV_PROGNOSE": "VC_today", "BATTERY_CAPACITY_KWH": "16.12"}
        with patch.dict("os.environ", umgebung), patch.object(MODULE, "LOXONE_HOST", ""), \
                patch.object(MODULE, "LATITUDE", None), patch.object(MODULE, "LONGITUDE", None), \
                patch.object(MODULE, "NAME_L1", ""), patch.object(MODULE, "LOXONE_PASSWORD", ""), \
                patch.object(MODULE, "NETZLEISTUNG_FAKTOR", 1.0), patch.object(MODULE, "NAME_PV_PROGNOSE", ""), \
                patch.object(MODULE, "BATTERY_CAPACITY_KWH", None):
            MODULE.konfiguration_laden()
            self.assertEqual((MODULE.LOXONE_HOST, MODULE.LATITUDE, MODULE.LONGITUDE, MODULE.NAME_L1),
                             ("ms.local", 48.1, 11.5, "L1 voltage"))
            self.assertEqual((MODULE.LOXONE_PASSWORD, MODULE.NETZLEISTUNG_FAKTOR), ("pw", 1000.0))
            self.assertEqual((MODULE.NAME_PV_PROGNOSE, MODULE.BATTERY_CAPACITY_KWH), ("VC_today", 16.12))

    def test_ungueltige_environment_variable(self):
        with patch.dict("os.environ", {"LATITUDE": "abc"}):
            with self.assertRaises(SystemExit):
                MODULE.konfiguration_laden()

    def test_pflichtwerte(self):
        gut = {"LOXONE_HOST": "x", "NAME_L1": "L1", "NAME_L2": "", "NAME_L3": "", "LATITUDE": 52.5,
               "LONGITUDE": 13.4, "PLANT_CAPACITY_KWP": None, "ABTAST_S": 10.0, "INTERVALL_S": 300,
               "NAME_PV_PROGNOSE": "", "BATTERY_CAPACITY_KWH": None}
        for kaputt in ({"LOXONE_HOST": ""}, {"NAME_L1": ""}, {"NAME_L2": "L2"}, {"LATITUDE": None},
                       {"LONGITUDE": 200.0}, {"PLANT_CAPACITY_KWP": 0}, {"ABTAST_S": 400.0},
                       {"NAME_PV_PROGNOSE": "VC_today"}, {"BATTERY_CAPACITY_KWH": 0}):
            werte = dict(gut, **kaputt)
            with self.subTest(kaputt=kaputt):
                patcher = [patch.object(MODULE, k, v) for k, v in werte.items()]
                for p in patcher:
                    p.start()
                try:
                    with self.assertRaises(SystemExit):
                        MODULE.konfiguration_pruefen()
                finally:
                    for p in patcher:
                        p.stop()


if __name__ == "__main__":
    unittest.main()
