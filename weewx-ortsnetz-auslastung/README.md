# Uploader to Ortsnetz-Auslastung for WeeWX
Uploader for the Ortsnetzauslastung project

## Prerequisites

You need a WeeWX services that fetches data from your PV system. Refer to
the documentation of that service for the names of the observation types
of grid voltages and grid frequency.

Examples for such services are:
* [weewx-photovoltaics](https://github.com/roe-dl/weewx-photovoltaics)
* [weewx-snmp](https://github.com/roe-dl/weewx-snmp)
* [WeeWX-MQTTSubscribe](https://github.com/weewx-mqtt/subscribe)

## Installation instructions

1) clone the repository

   ```shell
   git clone https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung
   ```

2) run the installer

   WeeWX up to version 4.X

   ```shell
   sudo wee_extension --install ~/datenerfassung-ortsnetz-auslastung/weewx-ortsnetz-auslastung
   ```

   WeeWX from version 5.0 on and WeeWX packet installation

   ```shell
   sudo weectl extension install ~/datenerfassung-ortsnetz-auslastung/weewx-ortsnetz-auslastung
   ```

   WeeWX from version 5.0 on and WeeWX pip installation into an virtual environment

   ```shell
   source ~/weewx-venv/bin/activate
   weectl extension install ~/datenerfassung-ortsnetz-auslastung/weewx-ortsnetz-auslastung
   ```
   
3) edit configuration in `skin.conf`

   Add the name of the measuring device to the key `smartmeter_model`

5) restart weewx

   for SysVinit systems:

   ```shell
   sudo /etc/init.d/weewx stop
   sudo /etc/init.d/weewx start
   ```

   for systemd systems:

   ```shell
   sudo systemctl stop weewx
   sudo systemctl start weewx
   ```

## Configuration instructions

The configuration section in `weewx.conf` looks like this:

```
[StdRESTful]
    ...
    [[Ortsnetz-Auslastung]]
        # enable or disable the uploader
        enable = true
        # dry run (skip the upload)
        skip_upload = false
        # log data to send
        log_url = false
        # name of the measuring device
        smartmeter_model = replace_me
        # software (optional, default "WeeWX X.X.X, uploader X.X")
        #integration_version = replace_me
        # observation types to get the grid measurements from
        # (optional. What follows, are the defaults)
        l1_v = pmGridVoltageL1
        l2_v = pmGridVoltageL2
        l3_v = pmGridVoltageL3
        grid_frequency_hz = heataccuMainsFrequency
        plant_capacity_kwp = installedPVPeakPower
        # name of the observation type to get a forecast form
        # (optional, default no value)
        #pv_forecast_kwh = replace_me

...
[Engine]
    [[Services]]
        ...
        restful_services = ..., user.ortsnetzauslastunguploader.RESTful
```

* `enable`: Switch the uploader on and off. Optional. Default is on.
* `skip_upload`: If set to `true` run in dry run mode. Calculate data
  but do not upload them.
* `log_url`: If set to `true` log data to send on syslog.
* `smartmeter_model`: Set it to the name of the measuring device that
  measures the grid voltages.
* `integration_version`: Normally you do **not** need this key. The 
  default is enough. Set it only, if you really know what you do.
* `l1_v`, `l2_v`, `l3_v`: Names of the observation types of the grid
  voltages. Mandatory. If you have a one phase system, set `l2_v` and 
  `l3_v` to `none`.
* `grid_frequency_hz`: Name of the observation type of the grid
  frequency. Optional. Set to `none` if your measuring device does not
  provide the frequency.
* `pv_forecast_kwh`: Name of the observation type that provides a 
  forecast of the daily earnings. Optional. Default is not provided.

## Links

Project websites of the Ortsnetz-Auslastung project:
* https://www.ortsnetz-auslastung.de/
* https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung

WeeWX:
* [weather software WeeWX](https://weewx.com)
* [fetch data from E3/DC converter](https://github.com/roe-dl/weewx-photovoltaics)
