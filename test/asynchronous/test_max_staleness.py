# Copyright 2016 MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test maxStalenessSeconds support."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import warnings
from pathlib import Path

from pymongo import AsyncMongoClient
from pymongo.operations import _Op

sys.path[0:0] = [""]

from test.asynchronous import AsyncPyMongoTestCase, async_client_context, unittest
from test.asynchronous.utils_selection_tests import create_selection_tests

from pymongo.errors import ConfigurationError
from pymongo.server_selectors import writable_server_selector

_IS_SYNC = False

# Location of JSON test specifications.
if _IS_SYNC:
    TEST_PATH = os.path.join(Path(__file__).resolve().parent, "max_staleness")
else:
    TEST_PATH = os.path.join(Path(__file__).resolve().parent.parent, "max_staleness")


class TestAllScenarios(create_selection_tests(TEST_PATH)):  # type: ignore
    pass


class TestMaxStaleness(AsyncPyMongoTestCase):
    async def test_max_staleness(self):
        client = self.simple_client()
        self.assertEqual(-1, client.read_preference.max_staleness)

        client = self.simple_client("mongodb://a/?readPreference=secondary")
        self.assertEqual(-1, client.read_preference.max_staleness)

        # These tests are specified in max-staleness-tests.rst.
        with self.assertRaises(ConfigurationError):
            # Default read pref "primary" can't be used with max staleness.
            self.simple_client("mongodb://a/?maxStalenessSeconds=120")

        with self.assertRaises(ConfigurationError):
            # Read pref "primary" can't be used with max staleness.
            self.simple_client("mongodb://a/?readPreference=primary&maxStalenessSeconds=120")

        client = self.simple_client("mongodb://host/?maxStalenessSeconds=-1")
        self.assertEqual(-1, client.read_preference.max_staleness)

        client = self.simple_client("mongodb://host/?readPreference=primary&maxStalenessSeconds=-1")
        self.assertEqual(-1, client.read_preference.max_staleness)

        client = self.simple_client(
            "mongodb://host/?readPreference=secondary&maxStalenessSeconds=120"
        )
        self.assertEqual(120, client.read_preference.max_staleness)

        client = self.simple_client("mongodb://a/?readPreference=secondary&maxStalenessSeconds=1")
        self.assertEqual(1, client.read_preference.max_staleness)

        client = self.simple_client("mongodb://a/?readPreference=secondary&maxStalenessSeconds=-1")
        self.assertEqual(-1, client.read_preference.max_staleness)

        client = self.simple_client(maxStalenessSeconds=-1, readPreference="nearest")
        self.assertEqual(-1, client.read_preference.max_staleness)

        with self.assertRaises(TypeError):
            # Prohibit None.
            self.simple_client(maxStalenessSeconds=None, readPreference="nearest")

    async def test_max_staleness_float(self):
        with self.assertRaises(TypeError) as ctx:
            await self.async_rs_or_single_client(maxStalenessSeconds=1.5, readPreference="nearest")

        self.assertIn("must be an integer", str(ctx.exception))

        with warnings.catch_warnings(record=True) as ctx:
            warnings.simplefilter("always")
            client = self.simple_client(
                "mongodb://host/?maxStalenessSeconds=1.5&readPreference=nearest"
            )

            # Option was ignored.
            self.assertEqual(-1, client.read_preference.max_staleness)
            self.assertIn("must be an integer", str(ctx[0]))

    async def test_max_staleness_zero(self):
        # Zero is too small.
        with self.assertRaises(ValueError) as ctx:
            await self.async_rs_or_single_client(maxStalenessSeconds=0, readPreference="nearest")

        self.assertIn("must be a positive integer", str(ctx.exception))

        with warnings.catch_warnings(record=True) as ctx:
            warnings.simplefilter("always")
            client = self.simple_client(
                "mongodb://host/?maxStalenessSeconds=0&readPreference=nearest"
            )

            # Option was ignored.
            self.assertEqual(-1, client.read_preference.max_staleness)
            self.assertIn("must be a positive integer", str(ctx[0]))

    @async_client_context.require_replica_set
    async def test_last_write_date(self):
        # From max-staleness-tests.rst, "Parse lastWriteDate".
        client = await self.async_rs_or_single_client(heartbeatFrequencyMS=500)
        await client.pymongo_test.test.insert_one({})
        # Wait for the server description to be updated.
        await asyncio.sleep(1)
        server = await client._topology.select_server(writable_server_selector, _Op.TEST)
        first = server.description.last_write_date
        self.assertTrue(first)
        # The first last_write_date may correspond to a internal server write,
        # sleep so that the next write does not occur within the same second.
        await asyncio.sleep(1)
        await client.pymongo_test.test.insert_one({})
        # Wait for the server description to be updated.
        await asyncio.sleep(1)
        server = await client._topology.select_server(writable_server_selector, _Op.TEST)
        second = server.description.last_write_date
        assert first is not None

        assert second is not None
        self.assertGreater(second, first)
        self.assertLess(second, first + 10)


if __name__ == "__main__":
    unittest.main()
