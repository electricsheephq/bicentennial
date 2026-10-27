"""Configuration structure checks."""

import unittest

from service.app import flags, routes, settings


class ConfigTests(unittest.TestCase):
    def test_tables(self):
        for table in (flags(), routes(), settings()):
            self.assertIsInstance(table, dict)
            for key, value in table.items():
                self.assertIsInstance(key, str)
                self.assertIsInstance(value, str)
                self.assertTrue(key and value)

    def test_routes(self):
        values = list(routes().values())
        self.assertEqual(len(values), len(set(values)))
