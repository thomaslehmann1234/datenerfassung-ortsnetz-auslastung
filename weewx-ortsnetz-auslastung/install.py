# installer Ortsnetz-Auslastung
# Copyright 2026 Johanna Karen Roedenbeck
# Distributed under the terms of the GNU Public License (GPLv3)

from weecfg.extension import ExtensionInstaller
from weeutil.config import config_from_str

CONFIG = """[StdRESTful]
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
"""

def loader():
    return OrtsnetzInstaller()

class OrtsnetzInstaller(ExtensionInstaller):
    def __init__(self):
        super(OrtsnetzInstaller, self).__init__(
            version="0.1",
            name='Ortsnetz-Auslastung',
            description='upload grid voltages and frequency to the Ortsnetz-Auslastung project',
            author="Johanna Karen Roedenbeck",
            author_email="",
            restful_services='user.ortsnetzauslastunguploader.RESTful',
            config=config_from_str(CONFIG),
            files=[('bin/user', ['bin/user/ortsnetzauslastunguploader.py'])]
            )
