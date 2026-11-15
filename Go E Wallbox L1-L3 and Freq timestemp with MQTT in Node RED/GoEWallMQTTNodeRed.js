//Here an exsample that works as messurment an go E Charger in MQTT Mode (i use my shirpstackserver as MQTT broker)
//use import in Node RED (es muss die richtige SerNummer des Chargers bei 1234 eingesetzt werden )
[
{
"id": "2141aee32c50a56e",
"type": "tab",
"label": "Go e Charger",
"disabled": false,
"info": "",
"env": []
},
{
"id": "bb1d4f35269ba2d7",
"type": "mqtt in",
"z": "2141aee32c50a56e",
"name": "",
"topic": "go-eCharger/1234/#",
"qos": "0",
"datatype": "auto-detect",
"broker": "74091428b02ef4ad",
"nl": false,
"rap": true,
"rh": 0,
"inputs": 0,
"x": 240,
"y": 140,
"wires": [
[
"91aab6e4b82477e8",
"switch_goe_topics"
]
]
},
{
"id": "91aab6e4b82477e8",
"type": "debug",
"z": "2141aee32c50a56e",
"name": "debug 17",
"active": false,
"tosidebar": true,
"console": false,
"tostatus": false,
"complete": "false",
"statusVal": "",
"statusType": "auto",
"x": 520,
"y": 140,
"wires": []
},
{
"id": "switch_goe_topics",
"type": "switch",
"z": "2141aee32c50a56e",
"name": "Topic filtern",
"property": "topic",
"propertyType": "msg",
"rules": [
{
"t": "eq",
"v": "go-eCharger/1234/fhz",
"vt": "str"
},
{
"t": "eq",
"v": "go-eCharger/1234/nrg",
"vt": "str"
}
],
"checkall": "true",
"repair": false,
"outputs": 2,
"x": 510,
"y": 240,
"wires": [
[
"86b4ad690f39da65"
],
[
"change_split_phases"
]
]
},
{
"id": "change_split_phases",
"type": "change",
"z": "2141aee32c50a56e",
"name": "Phasen trennen",
"rules": [
{
"t": "set",
"p": "payload_L1",
"pt": "msg",
"to": "payload[0]",
"tot": "jsonata"
},
{
"t": "set",
"p": "payload_L2",
"pt": "msg",
"to": "payload[1]",
"tot": "jsonata"
},
{
"t": "set",
"p": "payload_L3",
"pt": "msg",
"to": "payload[2]",
"tot": "jsonata"
},
{
"t": "set",
"p": "voltage_l1",
"pt": "flow",
"to": "payload_L1",
"tot": "msg"
},
{
"t": "set",
"p": "voltage_l2",
"pt": "flow",
"to": "payload_L2",
"tot": "msg"
},
{
"t": "set",
"p": "voltage_l3",
"pt": "flow",
"to": "payload_L3",
"tot": "msg"
}
],
"action": "",
"property": "",
"from": "",
"to": "",
"reg": false,
"x": 730,
"y": 260,
"wires": [
[
"debug_nrg_split",
"5666fee8b6aad124"
]
]
},
{
"id": "debug_fnn",
"type": "debug",
"z": "2141aee32c50a56e",
"name": "Netzfrequenz (Hz)",
"active": false,
"tosidebar": true,
"console": false,
"tostatus": false,
"complete": "true",
"targetType": "full",
"statusVal": "",
"statusType": "auto",
"x": 930,
"y": 120,
"wires": []
},
{
"id": "debug_nrg_split",
"type": "debug",
"z": "2141aee32c50a56e",
"name": "Getrennte Phasen",
"active": false,
"tosidebar": true,
"console": false,
"tostatus": false,
"complete": "{\n "L1 (Volt)": msg.payload_L1,\n "L2 (Volt)": msg.payload_L2,\n "L3 (Volt)": msg.payload_L3\n}",
"targetType": "jsonata",
"statusVal": "",
"statusType": "auto",
"x": 990,
"y": 200,
"wires": []
},
{
"id": "5666fee8b6aad124",
"type": "debug",
"z": "2141aee32c50a56e",
"name": "debug 22",
"active": false,
"tosidebar": true,
"console": false,
"tostatus": false,
"complete": "false",
"statusVal": "",
"statusType": "auto",
"x": 980,
"y": 320,
"wires": []
},
{
"id": "trigger_5min",
"type": "inject",
"z": "2141aee32c50a56e",
"name": "Alle 5 Min",
"props": [],
"repeat": "300",
"crontab": "",
"once": true,
"onceDelay": "10",
"topic": "",
"x": 190,
"y": 480,
"wires": [
[
"join_data"
]
]
},
{
"id": "join_data",
"type": "function",
"z": "2141aee32c50a56e",
"name": "Daten sammeln & API Payload bauen",
"func": "// 1. Werte aus dem Speicher holen (und Standardwerte setzen, falls leer)\nlet l1 = flow.get("voltage_l1");\nlet l2 = flow.get("voltage_l2");\nlet l3 = flow.get("voltage_l3");\nlet freq = flow.get("frequency");\n\n// Falls ein Wert nicht existiert oder keine Zahl ist, Standardwert nutzen\nl1 = (l1 !== undefined && !isNaN(l1)) ? parseFloat(l1) : 230.0;\nl2 = (l2 !== undefined && !isNaN(l2)) ? parseFloat(l2) : 230.0;\nl3 = (l3 !== undefined && !isNaN(l3)) ? parseFloat(l3) : 230.0;\nfreq = (freq !== undefined && !isNaN(freq)) ? parseFloat(freq) : 50.0;\n\n// 2. Koordinaten für: Am Eispfad, Mutterstadt\nlet latitude = 49.44542;\nlet longitude = 8.34593;\n\n// 3. Aktuellen ISO-Zeitstempel generieren\nlet now = new Date().toISOString();\n\n// 4. Payload exakt nach offizieller API-Vorgabe bauen (inkl. Gerätename)\nmsg.payload = {\n "observed_at": now,\n "latitude": latitude,\n "longitude": longitude,\n "l1_v": l1,\n "l2_v": l2,\n "l3_v": l3,\n "grid_frequency_hz": freq,\n "meter_model": "go-eCharger" // <-- Hier wird der Gerätename übermittelt\n};\n\n// HTTP Header setzen\nmsg.headers = {\n "Content-Type": "application/json"\n};\n\nreturn msg;",
"outputs": 1,
"timeout": "",
"noerr": 0,
"initialize": "",
"finalize": "",
"libs": [],
"x": 450,
"y": 480,
"wires": [
[
"http_request_ortsnetz"
]
]
},
{
"id": "http_request_ortsnetz",
"type": "http request",
"z": "2141aee32c50a56e",
"name": "An API senden",
"method": "POST",
"ret": "obj",
"paytoqs": "ignore",
"url": "https://www.ortsnetz-auslastung.de/v1/measurements",
"tls": "",
"persist": false,
"proxy": "",
"insecureHTTPParser": false,
"authType": "",
"senderr": false,
"headers": [],
"x": 730,
"y": 480,
"wires": [
[
"debug_api_response"
]
]
},
{
"id": "debug_api_response",
"type": "debug",
"z": "2141aee32c50a56e",
"name": "API Antwort",
"active": true,
"tosidebar": true,
"console": false,
"tostatus": false,
"complete": "payload",
"targetType": "msg",
"statusVal": "",
"statusType": "auto",
"x": 920,
"y": 480,
"wires": []
},
{
"id": "86b4ad690f39da65",
"type": "change",
"z": "2141aee32c50a56e",
"name": "",
"rules": [
{
"t": "set",
"p": "frequency",
"pt": "flow",
"to": "payload",
"tot": "msg"
}
],
"action": "",
"property": "",
"from": "",
"to": "",
"reg": false,
"x": 720,
"y": 200,
"wires": [
[
"debug_fnn"
]
]
},
{
"id": "74091428b02ef4ad",
"type": "mqtt-broker",
"name": "",
"broker": "localhost",
"port": 1883,
"clientid": "",
"autoConnect": true,
"usetls": false,
"protocolVersion": 4,
"keepalive": 60,
"cleansession": true,
"autoUnsubscribe": true,
"birthTopic": "",
"birthQos": "0",
"birthRetain": "false",
"birthPayload": "",
"birthMsg": {},
"closeTopic": "",
"closeQos": "0",
"closeRetain": "false",
"closePayload": "",
"closeMsg": {},
"willTopic": "",
"willQos": "0",
"willRetain": "false",
"willPayload": "",
"willMsg": {},
"userProps": "",
"sessionExpiry": ""
}
]
