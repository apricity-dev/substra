import json

from click.testing import CliRunner
import pytest

import substra
from substra.cli.interface import cli

from . import datastore


@pytest.fixture
def workdir(tmp_path):
    d = tmp_path / "substra-cli"
    d.mkdir()
    return d


def execute(command, exit_code=0):
    runner = CliRunner()
    result = runner.invoke(cli, command)
    assert result.exit_code == exit_code
    return result.output


def client_execute(tmpdir, command, exit_code=0):
    # force using a new config file and a new profile
    if '--config' not in command:
        cfgpath = tmpdir / 'substra.cfg'
        substra.sdk.config.Manager(str(cfgpath)).add_profile(
            'default', url='http://foo')
        command.extend(['--config', str(cfgpath)])
    return execute(command, exit_code=exit_code)


def test_command_help():
    output = execute(['--help'])
    assert 'Usage:' in output


def test_command_version():
    output = execute(['--version'])
    assert substra.__version__ in output


def test_command_config(workdir):
    cfgfile = workdir / "cli.cfg"

    assert cfgfile.exists() is False

    new_url = 'http://foo'
    new_profile = 'foo'
    execute([
        'config',
        new_url,
        '--profile', new_profile,
        '--config', str(cfgfile),
    ])
    assert cfgfile.exists()

    # check new profile has been created, check also that default profile
    # has been created
    with cfgfile.open() as fp:
        cfg = json.load(fp)
    expected_profiles = ['default', 'foo']
    assert list(cfg.keys()) == expected_profiles


def mock_client_call(mocker, method_name, response=""):
    return mocker.patch(f'substra.cli.interface.sdk.Client.{method_name}',
                        return_value=response)


@pytest.mark.parametrize('asset_name', ['objective', 'dataset'])
def test_command_list(asset_name, workdir, mocker):
    item = getattr(datastore, asset_name.upper())
    method_name = f'list_{asset_name}'
    with mock_client_call(mocker, method_name, [item]) as m:
        output = client_execute(workdir, ['list', asset_name])
    assert m.is_called()
    assert item['key'] in output


@pytest.mark.parametrize('asset_name', ['objective', 'dataset'])
def test_command_get(asset_name, workdir, mocker):
    item = getattr(datastore, asset_name.upper())
    method_name = f'get_{asset_name}'
    with mock_client_call(mocker, method_name, item) as m:
        output = client_execute(workdir, ['get', asset_name, 'fakekey'])
    assert m.is_called()
    assert item['key'] in output


def test_command_describe(workdir, mocker):
    response = "My description."
    with mock_client_call(mocker, 'describe_objective', response) as m:
        output = client_execute(workdir, ['describe', 'objective', 'fakekey'])
    assert m.is_called()
    assert response in output


def test_command_download(workdir, mocker):
    with mock_client_call(mocker, 'download_objective') as m:
        client_execute(workdir, ['download', 'objective', 'fakekey'])
    assert m.is_called()


def test_command_update_dataset(workdir, mocker):
    with mock_client_call(mocker, 'update_dataset') as m:
        client_execute(workdir, ['update', 'dataset', 'key1', 'key2'])
    assert m.is_called()


def test_command_update_data_sample(workdir, mocker):
    data_samples = {
        'keys': ['key1', 'key2'],
    }
    data_samples_path = workdir / 'data_samples.json'
    with data_samples_path.open(mode='w') as fp:
        json.dump(data_samples, fp)

    with mock_client_call(mocker, 'link_dataset_with_data_samples') as m:
        client_execute(
            workdir, ['update', 'data_sample', str(data_samples_path), 'key1'])
    assert m.is_called()
