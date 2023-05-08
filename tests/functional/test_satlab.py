from pathlib import Path
from tempfile import NamedTemporaryFile
import pytest
from click.testing import CliRunner
from broker import Broker
from broker.commands import cli
from broker.providers.ansible_tower import AnsibleTower
from broker.settings import inventory_path

SCENARIO_DIR = Path("tests/data/cli_scenarios/satlab")


@pytest.fixture(scope="module", autouse=True)
def skip_if_not_configured():
    try:
        AnsibleTower()
    except Exception as err:
        pytest.skip(f"AnsibleTower is not configured correctly: {err}")


@pytest.fixture(scope="module")
def temp_inventory():
    """Temporarily move the local inventory, then move it back when done"""
    backup_path = inventory_path.rename(f"{inventory_path.absolute()}.bak")
    yield
    CliRunner().invoke(
        cli, ["checkin", "--all", "--filter", "_broker_provider<AnsibleTower"]
    )
    inventory_path.unlink()
    backup_path.rename(inventory_path)


@pytest.mark.parametrize(
    "args_file", [f for f in SCENARIO_DIR.iterdir() if f.name.startswith("checkout_")]
)
def test_checkout_scenarios(args_file, temp_inventory):
    result = CliRunner().invoke(cli, ["checkout", "--args-file", args_file])
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "args_file", [f for f in SCENARIO_DIR.iterdir() if f.name.startswith("execute_")]
)
def test_execute_scenarios(args_file):
    result = CliRunner().invoke(cli, ["execute", "--args-file", args_file])
    assert result.exit_code == 0


def test_inventory_sync():
    result = CliRunner().invoke(cli, ["inventory", "--sync", "AnsibleTower"])
    assert result.exit_code == 0


def test_workflows_list():
    result = CliRunner().invoke(cli, ["providers", "AnsibleTower", "--workflows"])
    assert result.exit_code == 0


def test_workflow_query():
    result = CliRunner().invoke(
        cli, ["providers", "AnsibleTower", "--workflow", "list-templates"]
    )
    assert result.exit_code == 0


# ----- Broker API Tests -----

def test_tower_host():
    with Broker(workflow="deploy-base-rhel") as r_host:
        res = r_host.execute("hostname")
        assert res.stdout.strip() == r_host.hostname
        loc_settings_path = Path("broker_settings.yaml")
        remote_dir = "/tmp/fake"
        r_host.session.sftp_write(loc_settings_path.name, f"{remote_dir}/")
        res = r_host.execute(f"ls {remote_dir}")
        assert str(loc_settings_path) in res.stdout
        with NamedTemporaryFile() as tmp:
            r_host.session.sftp_read(f"{remote_dir}/{loc_settings_path.name}", tmp.file.name)
            data = r_host.session.sftp_read(
                f"{remote_dir}/{loc_settings_path.name}", return_data=True
            )
            assert (
                loc_settings_path.read_bytes() == Path(tmp.file.name).read_bytes()
            ), "Local file is different from the received one"
            assert (
                loc_settings_path.read_bytes() == data
            ), "Local file is different from the received one (return_data=True)"
            assert data == Path(tmp.file.name).read_bytes(), "Received files do not match"
        # test the tail_file context manager
        tailed_file = f"{remote_dir}/tail_me.txt"
        r_host.execute(f"echo 'hello world' > {tailed_file}")
        with r_host.session.tail_file(tailed_file) as tf:
            r_host.execute(f"echo 'this is a new line' >> {tailed_file}")
        assert 'this is a new line' in tf.stdout
        assert 'hello world' not in tf.stdout


def test_tower_host_mp():
    with Broker(workflow="deploy-base-rhel", _count=3) as r_hosts:
        for r_host in r_hosts:
            res = r_host.execute("hostname")
            assert res.stdout.strip() == r_host.hostname
            loc_settings_path = Path("broker_settings.yaml")
            remote_dir = "/tmp/fake"
            r_host.session.sftp_write(loc_settings_path.name, f"{remote_dir}/")
            res = r_host.execute(f"ls {remote_dir}")
            assert str(loc_settings_path) in res.stdout
            with NamedTemporaryFile() as tmp:
                r_host.session.sftp_read(f"{remote_dir}/{loc_settings_path.name}", tmp.file.name)
                data = r_host.session.sftp_read(
                    f"{remote_dir}/{loc_settings_path.name}", return_data=True
                )
                assert (
                    loc_settings_path.read_bytes() == Path(tmp.file.name).read_bytes()
                ), "Local file is different from the received one"
                assert (
                    loc_settings_path.read_bytes() == data
                ), "Local file is different from the received one (return_data=True)"
                assert data == Path(tmp.file.name).read_bytes(), "Received files do not match"
