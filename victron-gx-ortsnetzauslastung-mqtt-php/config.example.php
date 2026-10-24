<?php
/**
 * Einstellungen für victron-ortsnetz.php
 *
 * Diese Datei nach "config.php" kopieren und anpassen.
 * Das Hauptscript muss NICHT bearbeitet werden.
 */
return [

    // --- MQTT-Broker (Cerbo GX selbst oder ein Mosquitto, der den Cerbo spiegelt) ---
    'mqtt' => [
        'host'     => '192.168.1.20', // Hier IP Adresse vom Cerbo GX bzw. Venus OS eintragen.
        'port'     => 1883,
        'username' => null,      // nur falls nötig
        'password' => null,
        'tls'      => false,
    ],

    // VRM Portal-ID des GX-Geräts (Cerbo: Einstellungen -> VRM Online-Portal -> VRM-Portal-ID)
    'portal_id' => 'xxxxxxxxxxxx',

    // --- Messquelle ---
    // 'grid'  = Netzzähler (com.victronenergy.grid, z.B. EM24/ET340)  [Standard]
    // 'vebus' = Spannung am AC-Eingang eines Multi/Quattro
    'service'  => 'grid',

    // Geräteinstanz des Dienstes (z.B. 40). '+' = automatisch (nur sinnvoll,
    // wenn es genau einen solchen Dienst gibt).
    'instance' => '+',

    // 1 = einphasig (L2/L3 werden als -1 gesendet), 3 = dreiphasig
    'phases'   => 3,

    // Optional: eigene Pfade, falls die Standardpfade nicht passen. {n} = Phase 1..3
    // 'voltage_path'   => 'Ac/L{n}/Voltage',
    // 'frequency_path' => 'Ac/Frequency',   // null = keine Frequenz senden

    // --- Standort (OpenStreetMap: Rechtsklick -> "Abfrage starten") ---
    'latitude'  => 52.0000,
    'longitude' => 8.0000,

    // --- Optional ---
    'plant_capacity_kwp' => null,               // z.B. 9.8
    'smartmeter_model'   => 'Victron Cerbo GX', // max. 120 Zeichen

    // --- Kontrolle ---
    // Logdatei (null = nur Konsole/journalctl). Rotiert ab 1 MB.
    'log_file'    => __DIR__ . '/victron-ortsnetz.log',
    // Statusdatei mit letztem Erfolg, Fehlerzähler usw. (null = aus)
    'status_file' => __DIR__ . '/status.json',

    // --- Technik ---
    'interval'     => 300,   // Sekunden zwischen den Meldungen
    'max_age'      => 900,   // Messwerte älter als 15 min werden nicht gesendet
    'api_url'      => 'https://www.ortsnetz-auslastung.de/v1/measurements',
    'http_timeout' => 10,
];
