#!/usr/bin/python3
# Uploader for ortsnetz-auslastung.de
# Copyright (C) 2026 Johanna Karen Rödenbeck

"""

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""

"""
    Configuration in weewx.conf:
    
    [StdRESTful]
        ...
        [[Ortsnetz-Auslastung]]
            # enable or disable the uploader
            enable = true
            # dry run (skip the upload)
            skip_upload = false
            # minimum interval between uploads in seconds (at least 300)
            post_interval = 300
            # log data to send
            log_url = false
            # name of the measuring device
            smartmeter_model = ...
            # software (optional, default "WeeWX X.X.X, uploader X.X")
            integration_version = ...
            # observation types to get the grid measurements from
            # (optional. What follows, are the defaults)
            l1_v = pmGridVoltageL1
            l2_v = pmGridVoltageL2
            l3_v = pmGridVoltageL3
            grid_frequency_hz = heataccuMainsFrequency
            plant_capacity_kwp = installedPVPeakPower
            # name of the observation type to get a forecast form
            # (optional, default no value)
            pv_forecast_kwh = ...
   
   Project website:
   https://www.ortsnetz-auslastung.de/
   https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung
   
"""

import queue
from urllib.parse import urlencode, quote
import json
import sys
import time

import weedb
import weewx
import weewx.manager
import weewx.restx
import weewx.units
from weeutil.weeutil import to_bool, to_int, to_float
import weewx.xtypes
from weeutil.weeutil import TimeSpan

VERSION = "0.1"

import weeutil.logger
import logging
log = logging.getLogger('user.ortsnetzauslastunguploader')

def logdbg(msg):
    log.debug(msg)

def loginf(msg):
    log.info(msg)

def logerr(msg):
    log.error(msg)

class RESTful(weewx.restx.StdRESTful):

    DEFAULT_URL = 'https://www.ortsnetz-auslastung.de/v1/measurements'
    
    def __init__(self, engine, config_dict):
        """ initialize uploader
        """
        super(RESTful, self).__init__(engine, config_dict)
        site_dict = weewx.restx.get_site_dict(config_dict, 'Ortsnetz-Auslastung')
        if site_dict is None:
            return
            
        try:
            site_dict['manager_dict'] = weewx.manager.get_manager_dict_from_config(config_dict, site_dict.get('binding','pv_binding'))
        except weewx.UnknownBinding:
            pass

        try:
            # set the value if it not already exists, only
            site_dict.setdefault('longitude',engine.stn_info.longitude_f)
            site_dict.setdefault('latitude',engine.stn_info.latitude_f)
            site_dict.setdefault('l1_v','pmGridVoltageL1')
            site_dict.setdefault('l2_v','pmGridVoltageL2')
            site_dict.setdefault('l3_v','pmGridVoltageL3')
            site_dict.setdefault('grid_frequency_hz','heataccuMainsFrequency')
            site_dict.setdefault('plant_capacity_kwp','installedPVPeakPower')
            site_dict.setdefault('pv_forecast_kwh',None)
            site_dict.setdefault('smartmeter_model',None)
            site_dict.setdefault('integration_version','WeeWX %s, uploader %s' % (weewx.__version__,VERSION))
        except (ValueError,TypeError,IndexError) as e:
            logerr("longitude latitude %s" % e)

        # queue to pass the archive record to the uploader thread
        self.archive_queue = queue.Queue(5)

        # create and start the uploader thread
        self.archive_thread = RESTThread(self.archive_queue, **site_dict)
        self.archive_thread.start()

        # bind the uploader to the archive event
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)

    def new_archive_record(self, event):
        """ for every archive record send the data to the thread
        """
        try:
            self.archive_queue.put(event.record,timeout=10)
        except queue.Full:
            logerr('Queue is full. Thread died?')


class RESTThread(weewx.restx.RESTThread):

    def __init__(self, q, longitude, latitude,
                 l1_v, l2_v, l3_v, grid_frequency_hz, 
                 plant_capacity_kwp, pv_forecast_kwh, 
                 smartmeter_model, integration_version,
                 server_url=RESTful.DEFAULT_URL,
                 skip_upload=False, manager_dict=None,
                 post_interval=300, max_backlog=sys.maxsize, stale=None,
                 log_success=True, log_failure=True,
                 timeout=60, max_tries=3, retry_wait=5,
                 log_url=False):
        """ initialize thread
        """
        # Keep a five-minute minimum even when a shorter interval is configured.
        post_interval = max(300, to_int(post_interval) or 300)
        super(RESTThread, self).__init__(q,
            protocol_name='ortsnetz-auslastung',
                                         manager_dict=manager_dict,
                                          post_interval=post_interval,
                                          max_backlog=max_backlog,
                                          stale=stale,
                                          log_success=log_success,
                                          log_failure=log_failure,
                                          max_tries=max_tries,
                                          timeout=timeout,
                                          retry_wait=retry_wait,
                                          skip_upload=skip_upload)
        self.formatter=weewx.units.Formatter()
        # where to upload
        self.server_url = server_url
        loginf("Data will be uploaded to %s" % self.server_url)
        # log data to send
        self.log_url = to_bool(log_url)
        # station location
        self.latitude = latitude
        self.longitude = longitude
        # names of the observation types of the values to send
        self.l1_name = l1_v
        self.l2_name = l2_v
        self.l3_name = l3_v
        self.freq_name = grid_frequency_hz
        self.kwp_name = plant_capacity_kwp
        self.forecast_name = pv_forecast_kwh
        # measuring device and software version
        self.smartmeter_model = smartmeter_model
        self.integration_version = integration_version
        loginf("Data will come from %s, %s, %s, and %s" % (l1_v,l2_v,l3_v,grid_frequency_hz))

    def format_url(self, record):
        """ create the url including parameters
           required
           parameters can be added from the record
        """
        if self.log_url:
            loginf('URL: %s' % self.server_url)
        return self.server_url
    
    def get_post_body(self, record):
        """ put the payload together
        
            required for POST method, not allowed for GET method
        """
        # get the payload
        try:
            # get the grid voltages and convert them to Volt
            l1_v = weewx.units.convert(weewx.units.as_value_tuple(record,self.l1_name),'volt')[0]
            if l1_v is None: l1_v = -1
            grid_ok = l1_v>0.0
            if self.l2_name and self.l2_name.lower()!='none':
                l2_v = weewx.units.convert(weewx.units.as_value_tuple(record,self.l2_name),'volt')[0]
                if l2_v is None: l2_v = -1
                grid_ok = grid_ok and l2_v>0.0
            else:
                l2_v = -1
            if self.l3_name and self.l3_name.lower()!='none':
                l3_v = weewx.units.convert(weewx.units.as_value_tuple(record,self.l3_name),'volt')[0]
                if l3_v is None: l3_v = -1
                grid_ok = grid_ok and l3_v>0.0
            else:
                l3_v = -1
            # mandatory data
            body = {
                'observed_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(record['dateTime'])),
                'latitude': self.latitude,
                'longitude': self.longitude,
                'l1_v': round(l1_v,1),
                'l2_v': round(l2_v,1),
                'l3_v': round(l3_v,1),
            }
            # grid frequency (optional)
            if self.freq_name and self.freq_name.lower()!='none' and self.freq_name in record and grid_ok:
                freq = weewx.units.convert(weewx.units.as_value_tuple(record,self.freq_name),'hertz')[0]
                if freq is not None:
                    body['grid_frequency_hz'] = round(freq,3)
            # installed PV power (optional)
            if self.kwp_name and self.kwp_name.lower()!='none' and self.kwp_name in record:
                kwp = weewx.units.convert(weewx.units.as_value_tuple(record,self.kwp_name),'kilowatt')[0]
                if kwp is not None:
                    body['plant_capacity_kwp'] = round(kwp,1)
            # forecast (optional)
            if self.forecast_name and self.forecast_name.lower()!='none' and self.forecast_name in record:
                kwh = weewx.units.convert(weewx.units.as_value_tuple(record,self.forecast_name),'kilowatt_hour')[0]
                if kwh is not None:
                    body['pv_forecast_kwh'] = round(kwh,1)
            # measuring device
            if self.smartmeter_model:
                body['smartmeter_model'] = self.smartmeter_model
            # software that collects and posts data
            if self.integration_version:
                body['integration_version'] = self.integration_version
        except (LookupError, AttributeError, ArithmeticError, ValueError, TypeError) as e:
            raise weewx.restx.FailedPost('invalid data %s' % e)
        # convert to JSON
        try:
            body = json.dumps(body, indent=4)
        except TypeError as e:
            raise weewx.restx.FailedPost('cannot convert to JSON %s' % e)
        # logging
        if self.log_url:
            loginf('grid_ok: %s' % grid_ok)
            loginf(body)
        # return data and MIME type
        return body, 'application/json'
    

loginf("version %s" % VERSION)
