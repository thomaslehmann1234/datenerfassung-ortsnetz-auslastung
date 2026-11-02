"""Validate YAML examples with Home Assistant installed: python test_templates.py."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml
from homeassistant.components.automation.config import PLATFORM_SCHEMA as AUTOMATION_SCHEMA
from homeassistant.components.rest_command import CONFIG_SCHEMA as REST_COMMAND_SCHEMA
from homeassistant.core import HomeAssistant

DIRECTORY = Path(__file__).parent


class TemplateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.hass = HomeAssistant(directory.name)

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)

    def setUp(self):
        self.config = yaml.safe_load((DIRECTORY / "configuration.yaml").read_text())
        self.automation = yaml.safe_load((DIRECTORY / "ortsnetz-auslastung.yaml").read_text())

    async def test_rest_command_configuration_is_valid(self):
        REST_COMMAND_SCHEMA(self.config)

    async def test_automation_configuration_is_valid(self):
        AUTOMATION_SCHEMA(self.automation)

    def test_automation_calls_the_defined_command(self):
        self.assertIn("ortsnetz_auslastung_de", self.config["rest_command"])
        actions = [item["action"] for item in self.automation["actions"] if "action" in item]
        commands = [action.removeprefix("rest_command.") for action in actions if action.startswith("rest_command.")]
        self.assertEqual(commands, ["ortsnetz_auslastung_de"])
        self.assertIn(commands[0], self.config["rest_command"])
        self.assertEqual(self.config["rest_command"][commands[0]]["url"],
                         "https://www.ortsnetz-auslastung.de/v1/measurements")


if __name__ == "__main__":
    unittest.main()
