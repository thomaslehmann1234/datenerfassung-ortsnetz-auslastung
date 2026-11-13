// Shelly Pro 3EM / Pro 3EM-400 script for Ortsnetz-Auslastung.
// https://www.ortsnetz-auslastung.de/
// Authors: Thomas Lehmann / Juergen Gensicke
// Version 0.1.3, 2026-11-13. Configure latitude and longitude before starting.
// Samples stay in RAM; one measurement is sent after each five-minute interval.

const log_c = 0;

let CONFIG = {
  apiUrl: "https://www.ortsnetz-auslastung.de/v1/measurements",
  latitude: null,
  longitude: null,
  capacity: null, // Optional installed PV capacity in kWp; null = omit.
  battery: null, // Optional usable battery capacity in kWh; null = omit.
  smartmeterModel: "Shelly Pro 3EM",
  version: "0.1.3",
  SendIntervalMs: 300000,
  PeakIntervalMs: 15000,
  PRO3EMCT: 120 // 120 for 120 A CTs, 400 for 400 A CTs.
};

let SendCounter = 0;
let statistics = newStatistics();

function finiteNumber(value) {
  return typeof value === "number" && value > -Infinity && value < Infinity;
}

function validVoltage(value) {
  return finiteNumber(value) && value >= 150 && value <= 300;
}

function validCurrent(value) {
  return finiteNumber(value) && value >= 0 && value <= CONFIG.PRO3EMCT;
}

function validFrequency(value) {
  return finiteNumber(value) && value >= 45 && value <= 55;
}

function rounded(value) {
  return Math.round(value * 100) / 100;
}

function newStatistics() {
  return [
    { min: null, max: null, sum: 0, count: 0 },
    { min: null, max: null, sum: 0, count: 0 },
    { min: null, max: null, sum: 0, count: 0 }
  ];
}

function collectVoltage(index, value) {
  if (!validVoltage(value)) return;
  value = rounded(value);
  let stats = statistics[index];
  if (stats.count === 0 || value < stats.min) stats.min = value;
  if (stats.count === 0 || value > stats.max) stats.max = value;
  stats.sum += value;
  stats.count += 1;
}

function reportResult(result, errorCode, errorMessage) {
  if (errorCode !== 0) {
    console.log("Ortsnetz request failed: " + errorMessage);
    return false;
  }
  if (!result || result.code !== 202) {
    console.log("Ortsnetz API returned HTTP " + (result ? result.code : "unknown"));
    return false;
  }
  let response;
  try {
    response = JSON.parse(result.body);
  } catch (error) {
    console.log("Ortsnetz: invalid API response");
    return false;
  }
  if (!response || response.accepted !== true) {
    console.log("Ortsnetz: API did not confirm acceptance");
    return false;
  }
  console.log("Ortsnetz: measurement accepted (HTTP 202)");
  return true;
}

function sendMeasurement() {
  let em = Shelly.getComponentStatus("em:0");
  if (!em) em = {};
  let voltages = [em.a_voltage, em.b_voltage, em.c_voltage];
  let currents = [em.a_current, em.b_current, em.c_current];
  let frequencies = [em.a_freq, em.b_freq, em.c_freq];
  let index;
  for (index = 0; index < 3; index++) collectVoltage(index, voltages[index]);

  // Invalid optional readings never stop the clock or discard valid phases.
  SendCounter += 1;
  if (SendCounter * CONFIG.PeakIntervalMs < CONFIG.SendIntervalMs) return;
  SendCounter = 0;
  let intervalStatistics = statistics;
  statistics = newStatistics();

  if (!validVoltage(voltages[0]) && !validVoltage(voltages[1]) && !validVoltage(voltages[2])) {
    console.log("Ortsnetz: no valid phase voltage; interval skipped");
    return;
  }

  let payload = {
    observed_at: new Date().toISOString(),
    latitude: CONFIG.latitude,
    longitude: CONFIG.longitude,
    smartmeter_model: CONFIG.smartmeterModel,
    integration_version: "shelly-" + CONFIG.version
  };
  for (index = 0; index < 3; index++) {
    let phase = "l" + (index + 1);
    payload[phase + "_v"] = validVoltage(voltages[index]) ? rounded(voltages[index]) : -1;
    let stats = intervalStatistics[index];
    if (stats.count > 0) {
      payload[phase + "_v_min"] = stats.min;
      payload[phase + "_v_max"] = stats.max;
      // Keep min <= avg <= max even with floating-point rounding errors.
      payload[phase + "_v_avg"] = Math.max(stats.min, Math.min(stats.max, rounded(stats.sum / stats.count)));
    }
    if (validVoltage(voltages[index]) && validCurrent(currents[index])) {
      payload[phase + "_a"] = currents[index];
    }
    if (payload.grid_frequency_hz === undefined && validVoltage(voltages[index]) && validFrequency(frequencies[index])) {
      payload.grid_frequency_hz = frequencies[index];
    }
  }
  if (finiteNumber(em.total_act_power)) payload.grid_power_w = em.total_act_power;
  if (finiteNumber(em.total_aprt_power) && em.total_aprt_power >= 0) payload.apparent_power_va = em.total_aprt_power;
  if (finiteNumber(CONFIG.capacity) && CONFIG.capacity > 0 && CONFIG.capacity <= 1000) payload.plant_capacity_kwp = CONFIG.capacity;
  if (finiteNumber(CONFIG.battery) && CONFIG.battery >= 0 && CONFIG.battery <= 150) payload.battery_capacity = CONFIG.battery;

  let body = JSON.stringify(payload);
  if (log_c === 1) console.log(body);
  try {
    Shelly.call("HTTP.POST", {
      url: CONFIG.apiUrl,
      content_type: "application/json",
      ssl_ca: "*",
      timeout: 10,
      body: body
    }, reportResult);
  } catch (error) {
    console.log("Ortsnetz request failed: " + error);
  }
}

if (!finiteNumber(CONFIG.latitude) || CONFIG.latitude < -90 || CONFIG.latitude > 90 ||
    !finiteNumber(CONFIG.longitude) || CONFIG.longitude < -180 || CONFIG.longitude > 180) {
  console.log("Ortsnetz: configure latitude and longitude before starting");
} else if (!finiteNumber(CONFIG.SendIntervalMs) || CONFIG.SendIntervalMs < 300000 ||
           !finiteNumber(CONFIG.PeakIntervalMs) || CONFIG.PeakIntervalMs <= 0 || CONFIG.PeakIntervalMs > CONFIG.SendIntervalMs) {
  console.log("Ortsnetz: configure a send interval of at least 300000 ms and a valid sampling interval");
} else {
  Timer.set(CONFIG.PeakIntervalMs, true, sendMeasurement);
}
