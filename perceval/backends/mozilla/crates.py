# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2019 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Authors:
#     Valerio Cosentino <valcos@bitergia.com>
#     Quan Zhou <quan@bitergia.com>
#

import json
import logging

import requests

from grimoirelab_toolkit.datetime import (datetime_utcnow,
                                          datetime_to_utc,
                                          str_to_datetime)
from grimoirelab_toolkit.uris import urijoin

from ...backend import (Backend,
                        BackendCommand,
                        BackendCommandArgumentParser)
from ...client import HttpClient
from ...utils import DEFAULT_DATETIME

CRATES_URL = "https://crates.io/"
CRATES_API_URL = 'https://crates.io/api/v1/'

CATEGORY_CRATES = 'crates'
CATEGORY_SUMMARY = 'summary'

SLEEP_TIME = 60

logger = logging.getLogger(__name__)


class Crates(Backend):
    """Crates.io backend for Perceval.

    This class allows the fetch the packages stored in Crates.io

    :param sleep_time: sleep time in case of connection lost
    :param tag: label used to mark the data
    :param archive: archive to store/retrieve items
    :param ssl_verify: enable/disable SSL verification
    """
    version = '1.0.0'

    CATEGORIES = [CATEGORY_CRATES, CATEGORY_SUMMARY]

    def __init__(self, sleep_time=SLEEP_TIME, tag=None, archive=None, ssl_verify=True):
        origin = CRATES_URL

        super().__init__(origin, tag=tag, archive=archive, ssl_verify=ssl_verify)
        self.sleep_time = sleep_time

        self.client = None

    def fetch(self, category=CATEGORY_CRATES, from_date=DEFAULT_DATETIME):
        """Fetch package data.

        The method retrieves packages and summary from Crates.io.

        :param category: the category of items to fetch
        :param from_date: obtain packages updated since this date

        :returns: a summary and crate items
        """
        if not from_date:
            from_date = DEFAULT_DATETIME

        from_date = datetime_to_utc(from_date)

        kwargs = {"from_date": from_date}
        items = super().fetch(category, **kwargs)

        return items

    def fetch_items(self, category, **kwargs):
        """Fetch packages and summary from Crates.io

        :param category: the category of items to fetch
        :param kwargs: backend arguments

        :returns: a generator of items
        """
        from_date = kwargs['from_date']

        if category == CATEGORY_CRATES:
            return self.__fetch_crates(from_date)
        else:
            return self.__fetch_summary()

    @classmethod
    def has_archiving(cls):
        """Returns whether it supports archiving items on the fetch process.

        :returns: this backend supports items archive
        """
        return True

    @classmethod
    def has_resuming(cls):
        """Returns whether it supports to resume the fetch process.

        :returns: this backend supports items resuming
        """
        return False

    @staticmethod
    def metadata_id(item):
        """Extracts the identifier from an item depending on its type."""

        if Crates.metadata_category(item) == CATEGORY_CRATES:
            return str(item['id'])
        else:
            ts = item['fetched_on']
            ts = str_to_datetime(ts)
            return str(ts.timestamp())

    @staticmethod
    def metadata_updated_on(item):
        """Extracts the update time from an item.

        Depending on the item, the timestamp is extracted from the
        'updated_at' or 'fetched_on' fields.
        This date is converted to UNIX timestamp format.

        :param item: item generated by the backend

        :returns: a UNIX timestamp
        """
        if Crates.metadata_category(item) == CATEGORY_CRATES:
            ts = item['updated_at']
        else:
            ts = item['fetched_on']

        ts = str_to_datetime(ts)

        return ts.timestamp()

    @staticmethod
    def metadata_category(item):
        """Extracts the category from an item.

        This backend generates two types of item: 'summary' and 'crate'.
        """
        if 'num_downloads' in item:
            return CATEGORY_SUMMARY
        else:
            return CATEGORY_CRATES

    def _init_client(self, from_archive=False):
        """Init client"""

        return CratesClient(self.sleep_time, self.archive, from_archive, self.ssl_verify)

    def __fetch_summary(self):
        """Fetch summary"""

        raw_summary = self.client.summary()
        summary = json.loads(raw_summary)
        summary['fetched_on'] = str(datetime_utcnow())

        yield summary

    def __fetch_crates(self, from_date):
        """Fetch crates"""

        from_date = datetime_to_utc(from_date)

        crates_groups = self.client.crates()

        for raw_crates in crates_groups:
            crates = json.loads(raw_crates)

            for crate_container in crates['crates']:

                if str_to_datetime(crate_container['updated_at']) < from_date:
                    continue

                crate_id = crate_container['id']

                crate = self.__fetch_crate_data(crate_id)
                crate['owner_team_data'] = self.__fetch_crate_owner_team(crate_id)
                crate['owner_user_data'] = self.__fetch_crate_owner_user(crate_id)
                crate['version_downloads_data'] = self.__fetch_crate_version_downloads(crate_id)
                crate['versions_data'] = self.__fetch_crate_versions(crate_id)

                yield crate

    def __fetch_crate_owner_team(self, crate_id):
        """Get crate team owner"""

        raw_owner_team = self.client.crate_attribute(crate_id, 'owner_team')

        owner_team = json.loads(raw_owner_team)

        return owner_team

    def __fetch_crate_owner_user(self, crate_id):
        """Get crate user owners"""

        raw_owner_user = self.client.crate_attribute(crate_id, 'owner_user')

        owner_user = json.loads(raw_owner_user)

        return owner_user

    def __fetch_crate_versions(self, crate_id):
        """Get crate versions data"""

        raw_versions = self.client.crate_attribute(crate_id, "versions")

        version_downloads = json.loads(raw_versions)

        return version_downloads

    def __fetch_crate_version_downloads(self, crate_id):
        """Get crate version downloads"""

        raw_version_downloads = self.client.crate_attribute(crate_id, "downloads")

        version_downloads = json.loads(raw_version_downloads)

        return version_downloads

    def __fetch_crate_data(self, crate_id):
        """Get crate data"""

        raw_crate = self.client.crate(crate_id)

        crate = json.loads(raw_crate)
        return crate['crate']


class CratesClient(HttpClient):
    """Crates API client.

    Client for fetching information from the Crates API.

    :param sleep_time: time to sleep in case
        of connection problems
    :param archive: an archive to store/read fetched data
    :param from_archive: it tells whether to write/read the archive
    :param ssl_verify: enable/disable SSL verification
    """

    MAX_RETRIES = 5

    def __init__(self, sleep_time=SLEEP_TIME, archive=None, from_archive=False, ssl_verify=True):
        super().__init__(CRATES_API_URL, sleep_time=sleep_time, max_retries=CratesClient.MAX_RETRIES,
                         extra_headers={'Content-type': 'application/json'},
                         archive=archive, from_archive=from_archive, ssl_verify=ssl_verify)

    def summary(self):
        """Get Crates.io summary"""

        path = urijoin(CRATES_API_URL, CATEGORY_SUMMARY)
        raw_content = self.fetch(path)

        return raw_content

    def crates(self, from_page=1):
        """Get crates in alphabetical order"""

        path = urijoin(CRATES_API_URL, CATEGORY_CRATES)
        raw_crates = self.__fetch_items(path, from_page)

        return raw_crates

    def crate(self, crate_id):
        """Get a crate by its ID"""

        path = urijoin(CRATES_API_URL, CATEGORY_CRATES, crate_id)
        raw_crate = self.fetch(path)

        return raw_crate

    def crate_attribute(self, crate_id, attribute):
        """Get crate attribute"""

        path = urijoin(CRATES_API_URL, CATEGORY_CRATES, crate_id, attribute)
        raw_attribute_data = self.fetch(path)

        return raw_attribute_data

    def __fetch_items(self, path, page=1):
        """Return the items from Crates.io API using pagination"""

        fetch_data = True
        parsed_crates = 0
        total_crates = 0

        while fetch_data:
            logger.debug("Fetching page: %i", page)

            try:
                payload = {'sort': 'alphabetical', 'page': page}
                raw_content = self.fetch(path, payload=payload)
                content = json.loads(raw_content)

                parsed_crates += len(content['crates'])

                if not total_crates:
                    total_crates = content['meta']['total']

            except requests.exceptions.HTTPError as e:
                logger.error("HTTP exception raised - %s", e.response.text)
                raise e

            yield raw_content
            page += 1

            if parsed_crates >= total_crates:
                fetch_data = False

    def fetch(self, url, payload=None):
        """Return the textual content associated to the Response object"""

        response = super().fetch(url, payload=payload)

        return response.text


class CratesCommand(BackendCommand):
    """Class to run Crates.io backend from the command line."""

    BACKEND = Crates

    @classmethod
    def setup_cmd_parser(cls):
        """Returns the Crates argument parser."""

        parser = BackendCommandArgumentParser(cls.BACKEND,
                                              from_date=True,
                                              archive=True,
                                              token_auth=True,
                                              ssl_verify=True)

        # Optional arguments
        group = parser.parser.add_argument_group('Crates.io arguments')
        group.add_argument('--sleep-time', dest='sleep_time',
                           default=SLEEP_TIME, type=int,
                           help="Sleep time in case of connection lost")

        return parser
