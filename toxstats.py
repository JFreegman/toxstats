#!/usr/bin/env python

# This file is part of Toxstats.

# Toxstats is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Toxstats is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Toxstats.  If not, see <https://www.gnu.org/licenses/>.

from flask import Flask, redirect, url_for, render_template, request, make_response, g, flash
from flask.ext.cache import Cache
from contextlib import closing
import sqlite3
import json
import os
import util

# Maximum number of countries you can select for the chart
MAX_COUNTRY_SELECTION = 5

# Path to the json object containing country data
COUNTRIES_JSON_PATH = 'json/countries.json'

app = Flask(__name__)

# Default config (fill these out)
app.config.update(dict(
    DEBUG=False,
    DATABASE='crawler.db',
    SECRET_KEY='',
    USERNAME='',
    PASSWORD=''
))

# Override default settings if environment variable exists
app.config.from_envvar('TOXSTATS_SETTINGS', silent=True)

# Map country codes to full country name and load it into the app config (must be in sync with codesList)
# { 'countryCode': ('countryName', population), ... }
fp = open(COUNTRIES_JSON_PATH, 'r').read().strip()
obj = json.loads(fp)
app.config['countryDict'] = dict((k['countryCode'], (k['countryName'], int(k['population']))) for k in obj['countries']['country'])
app.config['countryDict']['ALL'] = (u'All Countries', 0, )

# Map time-level to level-code
app.config['timeMap'] = { 'Minute': 'M', 'Hour': 'H', 'Day': 'd', 'Month': 'm', 'Year': 'Y', }

cache = Cache(app, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': '/tmp'})

# Cached functions
@cache.memoize(timeout=60*5)
def getJsonCharts(countryCodes, level):
    return util.genChartsJson(g.db, countryCodes, level)

@cache.memoize(timeout=60*5)
def getJsonCountriesCurrent(countryDict):
    return util.genCountriesJson(g.db, countryDict, 'Current')

@cache.memoize(timeout=60*60)
def getJsonCountriesDay(countryDict):
    return util.genCountriesJson(g.db, countryDict, 'Day')

@cache.memoize(timeout=10)
def lastUpdate():
    return util.getLastUpdate(g.db)

@cache.memoize(timeout=60*60*8)
def refreshCodeList(countryDict):
    app.config['codesList'] = util.getCodesList(g.db, countryDict)

# Database functions
def connect_db():
    return sqlite3.connect(app.config['DATABASE'], timeout=5000)

def init_db():
    with closing(connect_db()) as db:
        with app.open_resource('crawler_schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

@app.before_request
def before_request():
    g.db = connect_db()

@app.teardown_request
def teardown_request(exception):
    db = getattr(g, 'db', None)
    if db:
        db.close()


COOKIE_SEPARATOR = '|'
CCODE_SEPARATOR  = '-'
def makeChartSettingsCookie(chartType, countryCodes, mapType):
    countryCodesStr = CCODE_SEPARATOR.join(c for c in countryCodes)
    return chartType + COOKIE_SEPARATOR + countryCodesStr + COOKIE_SEPARATOR + mapType

def validCountryCodes(countryCodes):
    if len(countryCodes) > MAX_COUNTRY_SELECTION:
        return False

    for c in countryCodes:
        if c not in app.config['countryDict']:
            return False

    return True

def getChartSettings(cookie, timeMap, countryDict):
    defaults = 'Minute', ['ALL'], 'Current'
    if not cookie or len(cookie) > 150:
        return defaults

    vals = cookie.split(COOKIE_SEPARATOR)
    if len(vals) != 3:
        return defaults

    chartType, countryCodes, mapType = vals
    if chartType not in timeMap or mapType not in ['Current', '24-Hours']:
        return defaults

    countryCodes = countryCodes.split(CCODE_SEPARATOR)
    if not validCountryCodes(countryCodes):
        return defaults

    return chartType, countryCodes, mapType

"""
Parses post data and extracts country codes list.
@return A list of country codes.
"""
def getCountryCodes(post_data):
    countryCodes = [d.split('countryCode=')[1] for d in post_data.split('&') if 'countryCode=' in d and d[-1] != '=']
    return countryCodes if validCountryCodes(countryCodes) else ['ALL']

@app.route('/', methods=['GET', 'POST'])
def main_page():
    timeMap = app.config['timeMap']

    countryDict = app.config['countryDict']
    refreshCodeList(countryDict)

    cookie = request.cookies.get('chartSettings')
    chartType, countryCodes, mapType = getChartSettings(cookie, timeMap, countryDict)
    level = timeMap[chartType]

    if request.method == 'POST':
        post_data = request.get_data()
        if 'chartType' in post_data:
            chartType = request.form['chartType']
            if chartType in timeMap:
                level = timeMap[chartType]
            if 'countryCode' in post_data:
                countryCodes = getCountryCodes(post_data)

        if 'mapType' in post_data:
            mapType = request.form['mapType']
    else:
        flash("If you'd like to help me out with server costs please consider a small donation.")

    jsonMap, jsonMapCapita, jsonPie, jsonBarCapita = [], [], [], []
    if mapType == 'Current':
        jsonMap, jsonMapCapita, jsonPie, jsonBarCapita = getJsonCountriesCurrent(countryDict)
    elif mapType == '24-Hours':
        jsonMap, jsonMapCapita, jsonPie, jsonBarCapita = getJsonCountriesDay(countryDict)

    jsonCharts = getJsonCharts(countryCodes, level)
    chartTitle = 'Unique Tox Nodes Per %s' % chartType.capitalize()

    response = make_response(render_template('index.html',
                                              chartdates=jsonCharts[0],
                                              jsonCharts=jsonCharts[1],
                                              chartTitle=chartTitle,
                                              chartType=chartType,
                                              countryDict=countryDict,
                                              codesList=app.config['codesList'],
                                              countryCodes=countryCodes,
                                              jsonMapCapita=jsonMapCapita,
                                              jsonMap=jsonMap,
                                              mapType=mapType,
                                              jsonPie=jsonPie,
                                              jsonBarCapita=jsonBarCapita,
                                              lastUpdate=lastUpdate()))

    cookie_val = makeChartSettingsCookie(chartType, countryCodes, mapType)
    response.set_cookie('chartSettings', cookie_val)
    return response

@app.route('/about', methods=['GET'])
def about():
    return render_template('about.html')

if __name__ == '__main__':
    app.run()
