import json
import functools
import os

import click
import consolemd

from substra import __version__, runner, sdk
from substra.cli import parsers
from substra.sdk import assets, exceptions
from substra.sdk import config as configuration


def get_client(config_path, profile_name):
    """Initialize substra client from config file and profile name."""
    help_command = "substra config <url> ..."

    try:
        client = sdk.Client(config_path, profile_name)

    except FileNotFoundError:
        raise click.ClickException(
            f"Config file '{config_path}' not found. Please run '{help_command}'.")

    except configuration.ProfileNotFoundError:
        raise click.ClickException(
            f"Profile '{profile_name}' not found. Please run '{help_command}'.")

    return client


def load_json(path):
    """Load dict from JSON file."""
    with open(path, 'rb') as fp:
        return json.load(fp)


def load_data_samples_json(path):
    """Load data sample keys from JSON file."""
    data = load_json(path)
    return data['keys']


def dict_append_to_optional_field(data, key, value):
    """Append value to a list that may be null."""
    if key in data:
        data[key].append(value)
    else:
        data[key] = [value]


def display(res):
    """Display result."""
    if res is None:
        return
    if isinstance(res, dict) or isinstance(res, list):
        res = json.dumps(res, indent=2)
    print(res)


# TODO profile, config, json and verbose options should be handled in a single
#      decorator to populate a GlobalOption object stored in the context


def click_option_profile(f):
    """Add profile option to command."""
    return click.option(
        '--profile',
        default='default',
        help='Profile name to use.')(f)


def click_option_config(f):
    """Add config option to command."""
    return click.option(
        '--config',
        type=click.Path(exists=True, resolve_path=True),
        default=os.path.expanduser('~/.substra'),
        help='Config path (default ~/.substra).')(f)


def click_option_json(f):
    """Add json option to command."""
    return click.option(
        '--json', 'json_output',
        is_flag=True,
        help='Display output as json.'
    )(f)


def click_option_verbose(f):
    """Add verbose option to command."""
    return click.option(
        '--verbose',
        is_flag=True,
        help='Enable verbose mode.'
    )(f)


def error_printer(fn):
    """Command decorator to pretty print a few selected exceptions from sdk."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        if ctx.params.get('verbose', False):
            # disable pretty print of errors if verbose mode is activated
            return fn(*args, **kwargs)

        try:
            return fn(*args, **kwargs)

        except exceptions.HTTPError as e:
            try:
                error = e.response.json()
            except ValueError:
                error = e.response.content
            raise click.ClickException(f"Request failed: {e}:\n{error}")

        except (exceptions.ConnectionError,
                exceptions.InvalidResponse) as e:
            raise click.ClickException(str(e))

    return wrapper


@click.group()
@click.version_option(__version__)
@click.pass_context
def cli(ctx):
    """Substra Command Line Interface.

    For help using this tool, please open an issue on the Github repository:
    https://github.com/SubstraFoundation/substra-cli
    """
    pass


@cli.command('config')
@click.argument('url')
@click.option('--config', type=click.Path(),
              default=configuration.DEFAULT_PATH,
              help='Config path (default ~/.substra).')
@click.option('--profile', default='default',
              help='Profile name to add')
@click.option('--insecure', '-k', is_flag=True,
              help='Do not verify SSL certificates')
@click.option('--version', '-v', default=configuration.DEFAULT_VERSION)
@click.option('--user', '-u')
@click.option('--password', '-p')
def add_profile_to_config(url, config, profile, insecure, version, user, password):
    """Add profile to config file."""
    configuration.Manager(config).add_profile(
        profile,
        url,
        version=version,
        insecure=insecure,
        user=user,
        password=password,
    )


@cli.group()
@click.pass_context
def add(ctx):
    """Add new asset to Substra platform."""
    pass


@add.command('data_sample')
@click.argument('path', type=click.Path(exists=True))
@click.option('--dataset-key', required=True)
@click.option('--local/--remote', 'local', is_flag=True, default=True,
              help='Data sample(s) location.')
@click.option('--multiple', is_flag=True, default=False,
              help='Add multiple data samples at once.')
@click.option('--test-only', is_flag=True, default=False,
              help='Data sample(s) used as test data only.')
@click.option('--dry-run', 'dryrun', is_flag=True)
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def add_data_sample(ctx, path, dataset_key, local, multiple, test_only,
                    dryrun, config, profile, verbose):
    """Add data sample(s).


    The path is either a directory reprensenting a data sample or a parent
    directory containing data samples directories (if --multiple option is
    set).
    """
    client = get_client(config, profile)
    if multiple and local:
        subdirs = next(os.walk(path))[1]
        paths = [os.path.join(path, s) for s in subdirs]
        if not paths:
            raise click.UsageError(f'No data sample directory in {path}')

    else:
        paths = [path]

    data = {
        'paths': paths,
        'data_manager_keys': [dataset_key],
        'multiple': multiple,
    }
    if test_only:
        data['test_only'] = True
    res = client.add_data_sample(data, local=local, dryrun=dryrun)
    display(res)


@add.command('dataset')
@click.argument('path', type=click.Path(exists=True))
@click.option('--objective-key')
@click.option('--dry-run', 'dryrun', is_flag=True)
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def add_dataset(ctx, path, objective_key, dryrun, config, profile, verbose):
    """Add dataset.

    The path must point to a valid JSON file with the following schema:

    \b
    {
        "name": str,
        "description": path,
        "type": str,
        "data_opener": path,
        "permissions": str,
    }

    \b
    Where:
    - name: name of the dataset
    - description: path to a markdown file describing the dataset
    - type: short description of the type of data that will be attached to this
      dataset (common values are 'Images', 'Tabular', 'Time series',
      'Spatial time series' and 'Hierarchical images')
    - data_opener: path to the opener python script
    - permissions: define asset access permissions
    """
    client = get_client(config, profile)
    data = load_json(path)
    dict_append_to_optional_field(data, 'objective_keys', objective_key)
    res = client.add_dataset(data, dryrun=dryrun)
    display(res)


@add.command('objective')
@click.argument('path', type=click.Path(exists=True))
@click.option('--dataset-key')
@click.option('--data-samples-path',
              type=click.Path(exists=True, resolve_path=True),
              help='test data samples')
@click.option('--dry-run', 'dryrun', is_flag=True)
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def add_objective(ctx, path, dataset_key, data_samples_path, dryrun, config,
                  profile, verbose):
    """Add objective.

    The path must point to a valid JSON file with the following schema:

    \b
    {
        "name": str,
        "description": path,
        "metrics_name": str,
        "metrics": path,
        "permissions": str,
    }

    \b
    Where:
    - name: name of the objective
    - description: path to a markdown file describing the objective
    - metrics_name: name of the metrics
    - metrics: path to tar.gz or zip archive containing the metrics python
      script and its Dockerfile
    - permissions: define asset access permissions

    The option --data-samples-path must point to a valid JSON file with the
    following schema:

    \b
    {
        "keys": list[str],
    }

    \b
    Where:
    - keys: list of test only data sample keys
    """
    client = get_client(config, profile)
    data = load_json(path)

    if dataset_key:
        data['test_data_manager_key'] = dataset_key

    if data_samples_path:
        data_sample_keys = load_data_samples_json(data_samples_path)
        data['test_data_sample_keys'] = data_sample_keys

    res = client.add_objective(data, dryrun=dryrun)
    display(res)


@add.command('algo')
@click.argument('path', type=click.Path(exists=True))
@click.option('--dry-run', 'dryrun', is_flag=True)
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def add_algo(ctx, path, dryrun, config, profile, verbose):
    """Add algo.

    The path must point to a valid JSON file with the following schema:

    \b
    {
        "name": str,
        "description": path,
        "file": path,
        "permissions": str,
    }

    \b
    Where:
    - name: name of the algorithm
    - description: path to a markdown file describing the algo
    - file: path to tar.gz or zip archive containing the algorithm python
      script and its Dockerfile
    - permissions: define asset access permissions
    """
    client = get_client(config, profile)
    data = load_json(path)
    res = client.add_algo(data, dryrun=dryrun)
    display(res)


@add.command('traintuple')
@click.option('--objective-key', required=True)
@click.option('--algo-key', required=True)
@click.option('--dataset-key', required=True)
@click.option('--data-samples-path', required=True,
              type=click.Path(exists=True, resolve_path=True))
@click.option('--dry-run', 'dryrun', is_flag=True)
@click.option('--tag', is_flag=True)
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def add_traintuple(ctx, objective_key, algo_key, dataset_key,
                   data_samples_path, dryrun, tag, config, profile, verbose):
    """Add traintuple.

    The option --data-samples-path must point to a valid JSON file with the
    following schema:

    \b
    {
        "keys": list[str],
    }

    \b
    Where:
    - keys: list of data sample keys
    """
    # TODO add missing inmodel keys?
    client = get_client(config, profile)
    data = {
        'algo_key': algo_key,
        'objective_key': objective_key,
        'data_manager_key': dataset_key,
    }

    if data_samples_path:
        data_sample_keys = load_data_samples_json(data_samples_path)
        data['train_data_sample_keys'] = data_sample_keys

    if tag:
        data['tag'] = tag
    res = client.add_traintuple(data, dryrun=dryrun)
    display(res)


@add.command('testtuple')
@click.option('--dataset-key')
@click.option('--traintuple-key', required=True)
@click.option('--data-samples-path',
              type=click.Path(exists=True, resolve_path=True))
@click.option('--dry-run', 'dryrun', is_flag=True)
@click.option('--tag', is_flag=True)
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def add_testtuple(ctx, dataset_key, traintuple_key,
                  data_samples_path, dryrun, tag, config, profile, verbose):
    """Add testtuple.


    The option --data-samples-path must point to a valid JSON file with the
    following schema:

    \b
    {
        "keys": list[str],
    }

    \b
    Where:
    - keys: list of data sample keys
    """
    client = get_client(config, profile)
    data = {
        'data_manager_key': dataset_key,
        'traintuple_key': traintuple_key,
    }

    if data_samples_path:
        data_sample_keys = load_data_samples_json(data_samples_path)
        data['test_data_sample_keys'] = data_sample_keys

    if tag:
        data['tag'] = tag
    res = client.add_testtuple(data, dryrun=dryrun)
    display(res)


@cli.command()
@click.argument('asset-name', type=click.Choice([
    assets.ALGO,
    assets.DATASET,
    assets.OBJECTIVE,
    assets.TESTTUPLE,
    assets.TRAINTUPLE,
]))
@click.argument('asset-key')
@click.option(
    '--expand', is_flag=True,
    help="Display associated assets (available for dataset and traintuple)."
)
@click_option_json
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def get(ctx, asset_name, asset_key, expand, json_output, config, profile, verbose):
    """Get asset definition."""
    expand_valid_assets = (assets.DATASET, assets.TRAINTUPLE)
    if expand and asset_name not in expand_valid_assets:  # fail fast
        raise click.UsageError(
            f'--expand option is available with assets {expand_valid_assets}')

    client = get_client(config, profile)
    # method must exist in sdk
    method = getattr(client, f'get_{asset_name.lower()}')
    res = method(asset_key)

    def _count_data_sample(items):
        key = 'data sample key'
        n = len(items)
        return f'{n} {key}' if n == 1 else f'{n} {key}s'

    if asset_name == assets.DATASET:
        if not expand:
            res['trainDataSampleKeys'] = _count_data_sample(
                res['trainDataSampleKeys'])
            res['testDataSampleKeys'] = _count_data_sample(
                res['testDataSampleKeys'])

    elif asset_name == assets.TRAINTUPLE:
        if expand:
            # get traintuple associated testtuples
            # TODO should we also get non certified testtuples?
            model = client.get(
                assets.MODEL, asset_key)
            testtuple = model.get('testtuple')
            if testtuple:
                res['testtuples'] = [testtuple]

    parser = parsers.get_parser(asset_name)
    parser.print_single(res, json_output)


@cli.command('list')
@click.argument('asset-name', type=click.Choice([
    assets.ALGO,
    assets.DATA_SAMPLE,
    assets.DATASET,
    assets.OBJECTIVE,
    assets.TESTTUPLE,
    assets.TRAINTUPLE,
]))
@click.argument('filters', required=False)
@click.option(
    '--is-complex', is_flag=True,
    help=(
        "When using filters the server will return a list of assets for "
        "each filter item. By default these lists are merged into a single "
        "list. When set, this option disables the lists aggregation."
    ),
)
@click_option_json
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def _list(ctx, asset_name, filters, is_complex, json_output, config, profile, verbose):
    """List assets."""
    client = get_client(config, profile)
    # method must exist in sdk
    method = getattr(client, f'list_{asset_name.lower()}')
    res = method(filters, is_complex)
    parser = parsers.get_parser(asset_name)
    parser.print_list(res, json_output)


@cli.command()
@click.argument('asset-name', type=click.Choice([
    assets.ALGO,
    assets.DATASET,
    assets.OBJECTIVE,
]))
@click.argument('asset-key')
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def describe(ctx, asset_name, asset_key, config, profile, verbose):
    """Display asset description."""
    client = get_client(config, profile)
    # method must exist in sdk
    method = getattr(client, f'describe_{asset_name.lower()}')
    description = method(asset_key)
    renderer = consolemd.Renderer()
    renderer.render(description)


@cli.command()
@click.argument('asset-name', type=click.Choice([
    assets.ALGO,
    assets.DATASET,
    assets.OBJECTIVE,
]))
@click.argument('key')
@click.option('--folder', type=click.Path(), help='destination folder',
              default='.')
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def download(ctx, asset_name, key, folder, config, profile, verbose):
    """Download asset implementation.

    \b
    - algo: the algo and its dependencies
    - dataset: the opener script
    - objective: the metrics and its dependencies
    """
    client = get_client(config, profile)
    # method must exist in sdk
    method = getattr(client, f'download_{asset_name.lower()}')
    res = method(key, folder)
    display(res)


@cli.command()
@click.argument('algo_path')
# TODO add helper for parameters
@click.option('--train-opener', type=click.Path(exists=True))
@click.option('--test-opener', type=click.Path(exists=True))
@click.option('--metrics', type=click.Path(exists=True))
@click.option('--rank', type=click.INT, default=0)
@click.option('--train-data-samples', type=click.Path(exists=True))
@click.option('--test-data-samples', type=click.Path(exists=True))
@click.option('--inmodel', type=click.Path(exists=True), multiple=True)
@click.option('--fake-data-samples', is_flag=True)
def run_local(algo_path, train_opener, test_opener, metrics, rank,
              train_data_samples, test_data_samples, inmodel,
              fake_data_samples):
    """Run local.

    This command can be used to check that objective, dataset and algo assets
    implementations are compatible.

    It will execute sequentially 4 tasks in docker:

    \b
    - train algo using train data samples
    - get model perf
    - test model using test data samples
    - get model perf

    \b
    It will create several output files:
    - sandbox/model/model
    - sandbox/pred_train/perf.json
    - sandbox/pred_train/pred
    - sandbox/pred_test/perf.json
    - sandbox/pred_test/pred
    """
    inmodels = inmodel  # multiple option
    # TODO merge runner.setup and runner.compute methods
    config = runner.setup(algo_path,
                          train_opener,
                          test_opener,
                          metrics,
                          train_data_samples,
                          test_data_samples)
    runner.compute(config, rank, inmodels, dry_run=fake_data_samples)


@cli.group()
@click.pass_context
def update(ctx):
    """Update asset."""
    pass


@update.command('data_sample')
@click.argument('data-samples-path', type=click.Path(exists=True))
@click.argument('dataset-key')
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def update_data_sample(ctx, data_samples_path, dataset_key, config, profile, verbose):
    """Link data samples with dataset.

    The data samples path must point to a valid JSON file with the following
    schema:

    \b
    {
        "keys": list[str],
    }

    \b
    Where:
    - keys: list of data sample keys
    """
    client = get_client(config, profile)
    data_sample_keys = load_data_samples_json(data_samples_path)
    res = client.link_dataset_with_data_samples(dataset_key, data_sample_keys)
    display(res)


@update.command('dataset')
@click.argument('dataset-key')
@click.argument('objective-key')
@click_option_config
@click_option_profile
@click_option_verbose
@click.pass_context
@error_printer
def update_dataset(ctx, dataset_key, objective_key, config, profile, verbose):
    """Link dataset with objective."""
    client = get_client(config, profile)
    res = client.link_dataset_with_objective(dataset_key, objective_key)
    display(res)


if __name__ == '__main__':
    cli()