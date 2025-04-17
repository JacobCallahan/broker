import os
import pytest
from pathlib import Path
from broker import settings


def pytest_sessionstart(session):
    """Put Broker into test mode."""
    os.environ["BROKER_TEST_MODE"] = "True"


@pytest.fixture(scope="session")
def broker_data_dir():
    """Return path to the test data directory"""
    return Path(os.path.dirname(__file__)) / "data"


@pytest.fixture(scope="session", autouse=True)
def set_broker_dir(broker_data_dir):
    """Set the Broker directory to the test data directory"""
    settings.BROKER_DIRECTORY = broker_data_dir
    settings.inventory_path = broker_data_dir / "inventory.yaml"


@pytest.fixture(scope="session")
def broker_settings_path(broker_data_dir):
    """Return path to test settings file"""
    return broker_data_dir / "broker_settings.yaml"


@pytest.fixture(scope="session")
def broker_settings(broker_settings_path):
    """Create and return a broker settings object for testing"""
    return settings.create_settings(
        config_file=broker_settings_path,
        perform_migrations=False
    )


@pytest.fixture
def set_envars(monkeypatch, request):
    """Set environment variables for a test and clean up afterward"""
    for envar, value in request.param:
        monkeypatch.setenv(envar, value)
    yield
