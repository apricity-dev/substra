from copy import deepcopy
import logging

from .config import ConfigManager
from . import requests_wrapper, utils, exceptions, assets

logger = logging.getLogger(__name__)
SIMPLE_ASSETS = [assets.DATA_SAMPLE, assets.TRAINTUPLE, assets.TESTTUPLE]


class Client(object):
    def __init__(self):
        self._configManager = ConfigManager()
        self.config = self._configManager.get('default')

    def create_config(self, profile, url='http://127.0.0.1:8000',
                      version='0.0', auth=False, insecure=False):
        """Create new config profile."""
        return self._configManager.create(profile=profile,
                                          url=url,
                                          version=version,
                                          auth=auth,
                                          insecure=insecure)

    def set_config(self, profile='default'):
        """Set config profile."""
        self.config = self._configManager.get(profile)
        return self.config

    def get_config(self):
        """Get current config."""
        return self.config

    def _get_url(self, *parts):
        """Build url from config and list of strings."""
        url_parts = [self.config['url']]
        url_parts.extend(parts)
        url = '/'.join(url_parts)
        return f'{url}/'  # django requires a suffix /

    def _get_asset_url(self, asset_name, *parts):
        """Build url from config and list of strings."""
        asset_name = assets.to_server_name(asset_name)
        parts = list(parts)
        parts.insert(0, asset_name)
        return self._get_url(*parts)

    def _post(self, asset, url, data, files, timeout):
        """Helper to do a POST request to the backend.

        In case of timeout, block till object is created.
        """
        try:
            res = requests_wrapper.post(self.config, url, data, files=files)

        except exceptions.RequestTimeout as e:
            # XXX could be handled directly by the backend (async create)
            logger.warning(
                'Request timeout, will block till asset is available')
            key = e.pkhash
            is_many = isinstance(key, list)
            if not timeout or is_many:
                # FIXME timeout on many objects is too complicated to handle.
                #       avoid operation on many objects:
                #       https://github.com/SubstraFoundation/substra-sdk-py/issues/25
                raise e
            # TODO retry only on NotFound exceptions when backend has been fixed:
            #      https://github.com/SubstraFoundation/substrabac/issues/196
            retry = utils.retry_on_exception(
                exceptions=(exceptions.NotFound, exceptions.InvalidRequest),
                timeout=float(timeout),
            )
            res = retry(self.get)(asset, key)

        return res

    def add(self, asset, data, dryrun=False, timeout=False):
        """Add asset."""
        data = deepcopy(data)  # make a deep copy for avoiding modification by reference
        if 'permissions' not in data:
            data['permissions'] = 'all'

        if dryrun:
            data['dryrun'] = True

        url = self._get_asset_url(asset)

        with utils.extract_files(asset, data) as (data, files):
            return self._post(asset, url, data, files, timeout)

    def register(self, asset, data, dryrun=False, timeout=False):
        """Register asset."""
        data = deepcopy(data)  # make a deep copy for avoiding modification by reference
        if 'permissions' not in data:
            data['permissions'] = 'all'

        if dryrun:
            data['dryrun'] = True

        url = self._get_asset_url(asset)

        with utils.extract_files(asset, data, extract_data_sample=False) \
                as (data, files):
            return self._post(asset, url, data, files, timeout)

    def get(self, asset, pkhash):
        """Get asset by key."""
        url = self._get_asset_url(asset, pkhash)
        return requests_wrapper.get(self.config, url)

    def options(self, asset, pkhash=None):
        """Options asset by key."""
        if pkhash is not None:
            url = self._get_asset_url(asset, pkhash)
        else:
            url = self._get_asset_url(asset)
        return requests_wrapper.options(self.config, url)

    def list(self, asset, filters=None, is_complex=False):
        """List assets."""
        kwargs = {}
        if filters:
            kwargs['params'] = utils.parse_filters(filters)

        url = self._get_asset_url(asset)
        result = requests_wrapper.get(self.config, url, **kwargs)
        if not is_complex and asset not in SIMPLE_ASSETS:
            result = utils.flatten(result)
        return result

    def path(self, asset, pkhash, path):
        """Get asset path."""
        url = self._get_asset_url(asset, pkhash, path)
        return requests_wrapper.get(self.config, url)

    def update(self, asset, pkhash, data):
        """Update asset by key."""
        url = self._get_asset_url(asset, pkhash, 'update_ledger')
        return requests_wrapper.post(self.config, url, data)

    def bulk_update(self, asset, data):
        """Update several assets."""
        url = self._get_asset_url(asset, 'bulk_update')
        return requests_wrapper.post(self.config, url, data)
