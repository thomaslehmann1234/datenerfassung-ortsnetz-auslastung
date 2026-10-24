<?php
declare(strict_types=1);

/**
 * Victron GX (MQTT) -> ortsnetz-auslastung.de
 *
 * Dieses Script muss nicht bearbeitet werden. Alle Einstellungen stehen in config.php.
 *
 * Installation:
 *   composer require php-mqtt/client
 *   cp config.example.php config.php   (und anpassen)
 *
 * Aufruf:
 *   php victron-ortsnetz.php --test    20 s lauschen, Werte anzeigen, nichts senden
 *   php victron-ortsnetz.php           Dauerbetrieb (als Dienst)
 *   php victron-ortsnetz.php --config=/pfad/zur/config.php
 */

require_once __DIR__ . '/vendor/autoload.php';

use PhpMqtt\Client\ConnectionSettings;
use PhpMqtt\Client\MqttClient;

const INTEGRATION_VERSION = 'php-victron-mqtt-0.1.0';

function logmsg(string $m): void
{
    $line = '[' . date('Y-m-d H:i:s') . '] ' . $m . PHP_EOL;
    echo $line;
    $file = $GLOBALS['LOG_FILE'] ?? null;
    if ($file) {
        // einfache Rotation: ab 1 MB wird die alte Datei zu .1
        if (is_file($file) && filesize($file) > 1048576) {
            @rename($file, $file . '.1');
        }
        @file_put_contents($file, $line, FILE_APPEND);
    }
}

/** Schreibt/aktualisiert die Statusdatei (JSON). */
function updateStatus(?string $file, array $update): void
{
    if (!$file) {
        return;
    }
    $cur = is_file($file) ? (json_decode((string)@file_get_contents($file), true) ?: []) : [];
    @file_put_contents($file, json_encode($update + $cur, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
}

// ---------------------------------------------------------------- Konfiguration
$opts = getopt('', ['test', 'config::']);
$test = isset($opts['test']);
$configFile = $opts['config'] ?? (__DIR__ . '/config.php');

if (!is_file($configFile)) {
    fwrite(STDERR, "Konfigurationsdatei fehlt: $configFile\nBitte config.example.php nach config.php kopieren.\n");
    exit(2);
}
$cfg = require $configFile;

foreach (['mqtt', 'portal_id', 'latitude', 'longitude'] as $key) {
    if (!isset($cfg[$key])) {
        fwrite(STDERR, "Fehlender Eintrag in der Konfiguration: $key\n");
        exit(2);
    }
}

$LOG_FILE    = $cfg['log_file'] ?? null;
$STATUS_FILE = $cfg['status_file'] ?? null;
$portal   = (string)$cfg['portal_id'];
$service  = (string)($cfg['service'] ?? 'grid');
$instance = (string)($cfg['instance'] ?? '+');
$phases   = max(1, min(3, (int)($cfg['phases'] ?? 3)));
$interval = max(60, (int)($cfg['interval'] ?? 300));
$maxAge   = (int)($cfg['max_age'] ?? 900);

// Standardpfade je Dienst
$presets = [
    'grid'  => ['volt' => 'Ac/L{n}/Voltage',        'freq' => 'Ac/Frequency'],
    'vebus' => ['volt' => 'Ac/ActiveIn/L{n}/V',     'freq' => 'Ac/ActiveIn/L1/F'],
];
$preset  = $presets[$service] ?? $presets['grid'];
$voltPath = $cfg['voltage_path'] ?? $preset['volt'];
$freqPath = array_key_exists('frequency_path', $cfg) ? $cfg['frequency_path'] : $preset['freq'];

// ---------------------------------------------------------------- Zustand
$values = ['l1' => null, 'l2' => null, 'l3' => null, 'freq' => null];
$stamps = ['l1' => 0.0, 'l2' => 0.0, 'l3' => 0.0, 'freq' => 0.0];
$seenTopics = [];

// ---------------------------------------------------------------- MQTT
$m = $cfg['mqtt'];
$mqtt = new MqttClient($m['host'], (int)($m['port'] ?? 1883), 'ortsnetz_victron_' . uniqid());
$settings = (new ConnectionSettings())
    ->setKeepAliveInterval(60)
    ->setUseTls((bool)($m['tls'] ?? false));
if (!empty($m['username'])) {
    $settings = $settings->setUsername($m['username'])->setPassword($m['password'] ?? null);
}
$mqtt->connect($settings, true);
logmsg("Verbunden mit {$m['host']}:" . ($m['port'] ?? 1883));

$subscribe = function (string $key, string $path) use ($mqtt, $portal, $service, $instance, &$values, &$stamps, &$seenTopics) {
    $topic = "N/$portal/$service/$instance/$path";
    $mqtt->subscribe($topic, function (string $t, string $message) use ($key, &$values, &$stamps, &$seenTopics) {
        $seenTopics[$t] = true;
        $data = json_decode($message, true);
        $v = is_array($data) ? ($data['value'] ?? null) : null;   // null = Gerät meldet "ungültig"
        $values[$key] = is_numeric($v) ? (float)$v : null;
        $stamps[$key] = microtime(true);
    }, 0);
    logmsg("Abonniert: $topic");
};

for ($n = 1; $n <= $phases; $n++) {
    $subscribe("l$n", str_replace('{n}', (string)$n, $voltPath));
}
if ($freqPath !== null) {
    $subscribe('freq', $freqPath);
}

/** Fragt beim GX alle Werte an (volle Ausgabe) bzw. hält den Strom am Laufen. */
$keepalive = function (bool $full) use ($mqtt, $portal) {
    $payload = $full ? '' : json_encode(['keepalive-options' => ['suppress-republish']]);
    $mqtt->publish("R/$portal/keepalive", $payload, 0);
};
$keepalive(true);

// ---------------------------------------------------------------- Senden
$buildPayload = function () use (&$values, &$stamps, $cfg, $phases, $maxAge): ?array {
    $now = microtime(true);
    $get = function (string $k) use (&$values, &$stamps, $now, $maxAge): ?float {
        if ($values[$k] === null || ($now - $stamps[$k]) > $maxAge) {
            return null;
        }
        return $values[$k];
    };
    $ok = fn(?float $v) => $v !== null && $v >= 150.0 && $v <= 300.0;

    $l1 = $get('l1');
    if (!$ok($l1)) {
        logmsg('L1 fehlt oder unplausibel -> nichts gesendet.');
        return null;
    }
    $out = ['l1_v' => round($l1, 1), 'l2_v' => -1, 'l3_v' => -1];
    foreach ([2, 3] as $n) {
        if ($n > $phases) {
            continue;
        }
        $v = $get("l$n");
        if (!$ok($v)) {
            logmsg("L$n fehlt oder unplausibel -> nichts gesendet.");
            return null;
        }
        $out["l{$n}_v"] = round($v, 1);
    }

    $p = [
        'observed_at'         => gmdate('Y-m-d\TH:i:s\Z'),
        'latitude'            => (float)$cfg['latitude'],
        'longitude'           => (float)$cfg['longitude'],
    ] + $out + ['integration_version' => INTEGRATION_VERSION];

    $f = $get('freq');
    if ($f !== null && $f >= 45 && $f <= 55) {
        $p['grid_frequency_hz'] = round($f, 2);
    }
    if (!empty($cfg['plant_capacity_kwp'])) {
        $p['plant_capacity_kwp'] = (float)$cfg['plant_capacity_kwp'];
    }
    if (!empty($cfg['smartmeter_model'])) {
        $p['smartmeter_model'] = mb_substr((string)$cfg['smartmeter_model'], 0, 120);
    }
    return $p;
};

$send = function (array $payload) use ($cfg): void {
    $ctx = stream_context_create(['http' => [
        'method'        => 'POST',
        'header'        => "Content-Type: application/json\r\nAccept: application/json\r\nUser-Agent: php-victron-ortsnetz\r\n",
        'content'       => json_encode($payload, JSON_THROW_ON_ERROR),
        'timeout'       => (int)($cfg['http_timeout'] ?? 10),
        'ignore_errors' => true,
    ]]);
    $url  = $cfg['api_url'] ?? 'https://www.ortsnetz-auslastung.de/v1/measurements';
    $body = @file_get_contents($url, false, $ctx);
    $status = 0;
    foreach ($http_response_header ?? [] as $h) {
        if (preg_match('#^HTTP/\S+\s+(\d{3})#', $h, $mm)) {
            $status = (int)$mm[1];
        }
    }
    $summary = sprintf('L1=%s L2=%s L3=%s f=%s',
        $payload['l1_v'], $payload['l2_v'], $payload['l3_v'], $payload['grid_frequency_hz'] ?? 'n/a');
    $stat = $GLOBALS['STATUS_FILE'];
    $now  = gmdate('Y-m-d\TH:i:s\Z');
    $prev = is_file((string)$stat) ? (json_decode((string)@file_get_contents($stat), true) ?: []) : [];

    if ($status === 202) {
        $r = json_decode((string)$body, true);
        $ampel = $r['status']['overall'] ?? '?';
        logmsg("Gesendet OK (202): $summary | Ampel: $ampel");
        updateStatus($stat, [
            'last_success'        => $now,
            'last_http_status'    => 202,
            'last_values'         => $summary,
            'last_ampel'          => $ampel,
            'success_count'       => ($prev['success_count'] ?? 0) + 1,
            'consecutive_errors'  => 0,
        ]);
    } else {
        $msg = $status === 0 ? 'API nicht erreichbar' : "API-Antwort $status: " . substr((string)$body, 0, 300);
        logmsg("FEHLER beim Senden ($summary): $msg");
        updateStatus($stat, [
            'last_error'          => $now,
            'last_error_message'  => $msg,
            'last_http_status'    => $status,
            'error_count'         => ($prev['error_count'] ?? 0) + 1,
            'consecutive_errors'  => ($prev['consecutive_errors'] ?? 0) + 1,
        ]);
    }
};

// ---------------------------------------------------------------- Hauptschleife
if (function_exists('pcntl_signal')) {
    pcntl_async_signals(true);
    foreach ([SIGTERM, SIGINT] as $sig) {
        pcntl_signal($sig, fn() => $mqtt->interrupt());
    }
}

$startedAt     = microtime(true);
$nextSend      = null;
$nextKeepalive = $startedAt + 30;

$mqtt->registerLoopEventHandler(function (MqttClient $client, float $elapsed) use (
    &$nextSend, &$nextKeepalive, $startedAt, $interval, $test, &$values, &$stamps, &$seenTopics,
    $buildPayload, $send, $keepalive
) {
    $now = microtime(true);

    if ($test) {
        if ($now - $startedAt >= 20) {
            logmsg('--- Testergebnis nach 20 s ---');
            logmsg(sprintf('L1=%s  L2=%s  L3=%s  f=%s',
                $values['l1'] ?? 'n/a', $values['l2'] ?? 'n/a', $values['l3'] ?? 'n/a', $values['freq'] ?? 'n/a'));
            logmsg($seenTopics ? 'Empfangene Topics: ' . implode(', ', array_keys($seenTopics))
                               : 'Nichts empfangen: Portal-ID, Dienst, Instanz bzw. Keepalive prüfen.');
            $p = $buildPayload();
            if ($p) {
                logmsg('Payload wäre: ' . json_encode($p));
            }
            $client->interrupt();
        }
        return;
    }

    if ($now >= $nextKeepalive) {
        $keepalive(false);
        $nextKeepalive = $now + 30;
    }

    // Erste Meldung kurz nach dem Start (sobald Werte da sind, spätestens nach 30 s), dann im Intervall
    if ($nextSend === null) {
        if ($values['l1'] !== null || ($now - $startedAt) >= 30) {
            $nextSend = $now;
        } else {
            return;
        }
    }
    if ($now >= $nextSend) {
        $nextSend += $interval;
        if ($nextSend < $now) {
            $nextSend = $now + $interval;
        }
        $p = $buildPayload();
        if ($p !== null) {
            $send($p);
        } else {
            updateStatus($GLOBALS['STATUS_FILE'], ['last_skipped' => gmdate('Y-m-d\TH:i:s\Z'), 'last_skipped_reason' => 'Messwerte fehlen/unplausibel']);
        }
    }
});

$mqtt->loop(true);
$mqtt->disconnect();
logmsg('Beendet.');
