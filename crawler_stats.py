#!/usr/bin/env python2

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

import os
import time
import pytz
import sqlite3
from sys import argv, exit
from datetime import datetime

import GeoIP
gi = GeoIP.new(GeoIP.GEOIP_MEMORY_CACHE)

DATABASE_PATH = 'crawler.db'

# Smallest time unit (in minutes) for which to store stats
TIMETICK_INTERVAL = 5

# Key for unknown geolocations
UNKNOWN_COUNTRY = '??'

"""
Returns the closest timetick to minute, rounded down. e.g. lowestTimeTick(11) == 10, lowestTimeTick(19) == 15
"""
def lowestTimeTick(minute):
    return "%02d" % (minute - (minute % TIMETICK_INTERVAL))

class CrawlerStats(object):
    def __init__(self, do_log_cleanup, logs_directory):
        self.do_log_cleanup = do_log_cleanup
        self.logs_directory = logs_directory

    def get_db(self):
        db = sqlite3.connect(DATABASE_PATH, timeout=5000)
        return db

    """
    Returns a sorted list containing all files from the logs directory
    with a more recent timetsamp than lastUpdate.
    """
    def getLogDirectories(self, lastUpdate):
        log_dirs = next(os.walk(self.logs_directory))

        if len(log_dirs) < 2:
            return []

        L = []
        base_dir = log_dirs[0]

        for date in sorted(log_dirs[1]):  # IMPORTANT: THIS MUST BE SORTED
            date_dir = base_dir + date
            for filename in os.listdir(date_dir):
                if filename[-4:] == '.cwl' and int(filename[:-4]) > lastUpdate:
                    L.append(date_dir + '/' + filename)

        return sorted(L)

    """
    Returns a tuple containing a list of all IP addresses found in logfile, and the length of the list.
    """
    def getIPList(self, logfile):
        IPlist = set(open(logfile, 'r').read().strip().split(' '))
        return IPlist, len(IPlist)

    """
    Clears all db entries from ips table where the time_period has passed.
    WARNING: This relies on the fact that logs are always loaded chronologically.
    """
    def dbCleanup(self, db, old, current):
        if not old or not current:
            return

        garbage = []
        for i in xrange(1, len(old)):
            if int(current[-i]) >= int(old[-i]):   # skips index[-1], this is not a bug
                break

            garbage.append("-".join(old[:-i]))

        for skype in garbage:
            db.execute('DELETE FROM ips ' +
                       'WHERE time_period = (?)',
                       (skype,))
        if garbage:
            db.commit()

    """
    Creates/updates a SQL database containing statistics retreived from crawler logs.
    If cleanup is set to True, this function will delete superfluous logs from
    the crawler_logs directory, meaning only one log file per TIMETICK_INTERVAL is retained.
    """
    def generateStats(self):
        db = self.get_db()
        cur = db.execute('SELECT value FROM miscStats ' +
                         'WHERE name = "lastUpdate"').fetchone()

        lastUpdate = 0 if not cur else cur[0]
        last_time_period = []
        if lastUpdate:
            last_time_period = datetime.fromtimestamp(lastUpdate, tz=pytz.utc).strftime("%Y %m %d %H %M").split()
            last_time_period[-1] = lowestTimeTick(int(last_time_period[-1]))

        logs = self.getLogDirectories(lastUpdate)
        num_logs = len(logs)
        count = 0
        cleanup = []

        for file in logs:
            ts = int(file[max((file.rfind('/'), 0)) + 1 : file.rfind('.')])  # extract timestamp from path
            Y, m, d, H, M = datetime.fromtimestamp(ts, tz=pytz.utc).strftime("%Y %m %d %H %M").split()
            tick = lowestTimeTick(int(M))
            time_period = [Y, m, d, H, tick]

            if self.do_log_cleanup and last_time_period == time_period:
                cleanup.append(file)
                continue

            self.dbCleanup(db, last_time_period, time_period)
            last_time_period = time_period

            IPlist, numIPs = self.getIPList(file)
            if numIPs < 1500:
                cleanup.append(file)
                continue

            if ts <= lastUpdate:
                continue

            lastUpdate = ts
            db.execute('INSERT OR REPLACE INTO miscStats ' +
                       '(name, value) VALUES (?, ?)',
                       ("lastUpdate", lastUpdate))

            for ip in IPlist:
                self.update_db(db, Y, m, d, H, tick, ip)

            db.commit()

            os.system('clear')
            count += 1
            pct = round(float(count) / num_logs * 100.0, 2)
            print "Complete: " + str(pct) + "%" + " (" + str(count) + " of " + str(num_logs) + ")"

        for file in cleanup:
            try:
                os.remove(file)
            except OSError:
                continue

        db.close()

    def update_db(self, db, Y, m, d, H, tick, ip):
        country = gi.country_code_by_addr(ip)
        if not country:
            country = UNKNOWN_COUNTRY

        time_period = Y + '-' + m + '-' + d + '-' + H + '-' + tick
        self.updateNodesDatabase(db, time_period, country)
        self.updateNodesDatabase(db, time_period, 'ALL')

        for i in xrange(3, 13, 3):  # magic
            t = time_period[:-i]
            if self.ipInDatabase(db, ip, t):
                break

            self.addIpDatabase(db, ip, t)
            self.updateNodesDatabase(db, t, country)
            self.updateNodesDatabase(db, t, 'ALL')

    def updateNodesDatabase(self, db, time_period, country):
        entry = db.execute('SELECT nodes FROM nodeCounts ' +
                           'WHERE time_period = (?) ' +
                           'AND country = (?)',
                           (time_period, country)).fetchone()

        numNodes = entry[0] + 1 if entry else 1
        db.execute('INSERT OR REPLACE INTO nodeCounts ' +
                   '(nodes, time_period, country) VALUES (?, ?, ?)',
                   (numNodes, time_period, country))

    def addIpDatabase(self, db, ip, time_period):
        db.execute('INSERT INTO ips (ip, time_period) ' +
                   'VALUES (?, ?)',
                   (ip, time_period))

    """
    Returns True if ip is in database for given time period.
    """
    def ipInDatabase(self, db, ip, time_period):
        return db.execute('SELECT EXISTS (SELECT 1 FROM ips ' +
                                         'WHERE ip = (?) ' +
                                         'AND time_period = (?) ' +
                                         'LIMIT 1)',
                                         (ip, time_period)).fetchone()[0]


if __name__ == '__main__':
    if (len(argv) != 3):
        print "Usage: crawler_stats [cleanup] [path]"
        exit(1)

    start = time.time()

    stats = CrawlerStats(True, argv[2]) if (len(argv) > 1 and argv[1].lower() == 'cleanup') else CrawlerStats(False, argv[2])
    stats.generateStats()

    end = time.time()
    print "Finished in %.2f seconds" % (end - start)
