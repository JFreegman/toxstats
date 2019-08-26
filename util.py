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

import json
import pytz
import datetime
import sqlite3

# Smallest time unit (in minutes) for which to store stats. Should align with
# the constant with the same name in crawler_stats.py
TIMETICK_INTERVAL = 5

# time levels and corresponding time_period string length in the database
LEVELS = {'Y': 4, 'm': 7, 'd': 10, 'H': 13, 'M': 16, 'all': 16}

# Max number of data points for line charts according to level
LEVEL_POINTS = {'Y': 100, 'm': 1200, 'd': 1200, 'H': 3031, 'M': 28800, 'all': 28800}

ALL_COUNTRIES = 'ALL'

"""
Returns the closest timetick to minute, rounded down. e.g. lowestTimeTick(11) == 10, lowestTimeTick(19) == 15
"""
def lowestTimeTick(minute):
    return minute - (minute % TIMETICK_INTERVAL)

"""
Creates a list of json objects containing the node counts for all specified countries and
all specified data points contained in the database.

@db The SQL database created by crawler_stats.py
@countries A list of two character country code specifying the countries for which to collect data.
@level Specifies the smallest time level for which to collect data.
  Must be one of the strings from the LEVELS array.

@return a tuple containing dates, and a list countaining countrycodes and string-formatted node counts.
"""
def genChartsJson(db, countries=['ALL'], level='all'):
    if not db or len(countries) > 5 or level not in LEVELS:
        return []

    dataList = []
    dateset = set()
    for country in countries:
        if len(country) > 3:
            continue

        entries = db.execute('SELECT * FROM ' +
                             '(SELECT nodes, time_period FROM nodeCounts ' +
                             'WHERE LENGTH(time_period) = (?) ' +
                             'AND country = (?) ' +
                             'LIMIT (?)) sub ' +
                             'ORDER BY time_period DESC',
                             (LEVELS[level], country, LEVEL_POINTS[level] * len(countries))).fetchall()
        flatObj = []
        for entry in entries:
            date = makeDate(entry[1], level)
            if date:
                dateset.add(date)
                flatObj.append({"nodes": entry[0], "label": date})

        if level == 'd' or level == 'H' or level == 'm':
            dataList.append((country, sorted(flatObj, key=lambda v: v['label'])[:-1]))
        else:
            dataList.append((country, sorted(flatObj, key=lambda v: v['label'])))

    L = []
    for entry in dataList:
        L.append((entry[0], '|'.join(str(n['nodes']) for n in entry[1])))

    return ("|".join(d for d in sorted(list(dateset))), L)

"""
Deconstructs a time_period string from the database and returns it as a date string
appropriate for a chart.
"""
def makeDate(entry, level):
    chars = entry.split('-')
    if not chars:
        return None

    if level in ['Y', 'm', 'd']:
        return "-".join(chars)

    if level in ['ALL', 'M']:
        Y, m, d, H, M = chars
        return Y + '-' + m + '-' + d + ' ' + H + ':' + M

    if level == 'H':
        Y, m, d, H = chars
        return Y + '-' + m + '-' + d + ' ' + H + ':' + '00'

    return None


"""
@db The database created by crawler_stats.py
@return The previous day's full data in db. Tries a full month before giving up.
"""
def getLastDay(db, year, month, day):
    if not db:
        return None

    for i in range(1, 32):
        date = datetime.date(year, month, day) - datetime.timedelta(i)
        time_period = date.strftime("%Y-%m-%d")
        if db.execute('SELECT 1 FROM nodeCounts ' +
                      'WHERE time_period = (?) ' +
                      'LIMIT 1', (time_period,)).fetchone():
            return time_period

    return None

"""
Helper function to extract a set of country:nodes pairs from the database.
@return a tuple containing the object corresponding to the latest data for the given level
    and the node count.
"""
def getEntries(db, level):
    if not db:
        return None

    entry = db.execute('SELECT value FROM miscStats ' +
                       'WHERE name = "lastUpdate"').fetchone()
    if not entry:
        return None

    lastUpdate = entry[0]
    Y, m, d, H, M = datetime.datetime.fromtimestamp(int(lastUpdate), tz=pytz.utc).strftime("%Y %m %d %H %M").split()
    time_period = ""

    if level == 'Day':
        prevTime = getLastDay(db, int(Y), int(m), int(d))
        time_period = prevTime if prevTime else Y + '-' + m + '-' + d
    else:
        tick = "%02d" % lowestTimeTick(int(M))
        time_period = Y + '-' + m + '-' + d + '-' + H + '-' + tick

    entries = db.execute('SELECT country, nodes FROM nodeCounts ' +
                         'WHERE time_period = (?) ' +
                         'AND country IS NOT (?)', (time_period, ALL_COUNTRIES))

    obj = dict((e[0], e[1]) for e in entries.fetchall())

    nodes = db.execute('SELECT nodes FROM nodeCounts ' +
                       'WHERE time_period = (?) ' +
                       'AND country = (?)', (time_period, ALL_COUNTRIES)).fetchone()

    numNodes = nodes[0] if nodes else 1
    return (obj, numNodes)

"""
Creates four flat json objects containing the node count and per-capita node count for every country
in countryDict, as well as separate objects with only the top 10 countries, respectively for
the most recent data point at 'level'.

@db The database created by crawler_stats.py
@countryDict A dictionary containing countries and their respective country codes and populations.
    keys are the ISO country code, names and populations are in the value as a tuple.
@level If level is 'Current' get the most up-to-date timetick. If it's set to 'Day', get data
    for the last full 24 hours.

@return A tuple containing four json objects
"""
def genCountriesJson(db, countryDict, level='Current'):
    if not db or not countryDict or level not in ['Current', 'Day']:
        return [], []

    # flatObj's amcharts map format; flatObjPie/Bar canvasjs pie/bar format
    flatObj, flatObjPC, flatObjPie, flatObjBarPC = [], [], [], []
    obj, numNodes = getEntries(db, level)

    for k, v in countryDict.items():
        if k in obj:
            val = obj[k]
            flatObj.append({"id": k, "value": val})
            flatObjPie.append({"value": round((float(val) / numNodes), 4) * 100, "label": countryDict[k][0]})

            PCval = round((float(val) / v[1]) * 1000000, 2) if v[1] >= 1000000 else 0   # only real countries
            flatObjPC.append({"id": k, "value": PCval})
            flatObjBarPC.append({"value": PCval, "label": countryDict[k][0]})
        else:
            flatObj.append({"id": k, "value": 0})
            flatObjPC.append({"id": k, "value": 0})

    # Unknowns not in countryDict but we still want to include them in the stats
    if '??' in obj:
        flatObjPie.append({"value": round((float(obj['??']) / numNodes), 4) * 100, "label": "Unknown/IPv6"})

    flatObjPie.sort(reverse=True, key=lambda c: c['value'])
    flatObjBarPC.sort(reverse=True, key=lambda c: c['value'])

    # We only want the top 10 for the donut/bar charts
    donutTop10 = flatObjPie[:10]
    donutTop10.append({"value": sum(v['value'] for v in flatObjPie[10:]), "label": "Others"})
    donutTop10PC = flatObjBarPC[:10]
    return (json.dumps(flatObj), json.dumps(flatObjPC), json.dumps(donutTop10), json.dumps(donutTop10PC))

"""
@return The string-formatted time the database was last updated with new entries.
"""
def getLastUpdate(db):
    if not db:
        return None

    entry = db.execute('SELECT value FROM miscStats ' +
                       'WHERE name = "lastUpdate"').fetchone()
    if entry:
        return datetime.datetime.fromtimestamp(int(entry[0]), tz=pytz.utc).strftime("%Y-%m-%d %H:%M:%S")

"""
@db The database created by crawler_stats.py
@return A sorted list of country codes that exist in db.
"""
def getCodesList(db, countryDict):
    if not db:
        return []

    entries = db.execute('SELECT country FROM nodeCounts ' +
                         'WHERE LENGTH(time_period) = (?)', (LEVELS['Y'],)).fetchall()
    if not entries:
        return []

    return sorted(set([e[0] for e in entries if e[0] in countryDict]), key=lambda c: countryDict[c][0])  # sort by country name
