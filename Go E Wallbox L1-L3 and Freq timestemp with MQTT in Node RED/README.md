Was brauche ich: Ein laufenden MQTT Broker Moskito oder den integrierten des Shirpstak Servers
Ein installiertes Node-RED, im Node-RED muss das Node MQTT vorhanden sein und die Brokeradresse mit Passwort sofern vorhanden genannt werden
Logisch eine Go E Wallbox, es gehen alle mit der APP, in der APP muss das MQTT freigeschaltet werden und der MQTT Broker genannt werden mit Mqtt://ipadresse:1883
ohne Passwort das übernimmt Node RED.
Es werden alle 5min die Daten von L1 L2 L3 in Volt übergeben sowie ein timstemp und die Netzfrequenz, sowie die fixen Parameter wie Gerätename und natürlich der ORT,
in der Funktion Node sind diese Parameter im js Script anzupassen!

What do I need: A running MQTT broker (Moskito) or the one built into the Shirpstak server
Node-RED must be installed; the MQTT node must be present in Node-RED, and the broker address and password (if applicable) must be specified
Of course, you’ll need a Go E Wallbox—all models are compatible with the app. In the app, MQTT must be enabled, and the MQTT broker must be specified as `mqtt://ip-address:1883`
No password is required; Node-RED handles that.
Every 5 minutes, the data from L1, L2, and L3 (in volts) is transmitted, along with a timestamp and the grid frequency, as well as fixed parameters such as the device name and, of course, the LOCATION.
These parameters must be adjusted in the JavaScript script within the Node function!
Starting from the square bracket, the JavaScript script must then be imported into Node-RED 
