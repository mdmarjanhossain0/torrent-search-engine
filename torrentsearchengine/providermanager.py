from typing import List, Union, Optional
import json
import logging
import requests
from .exceptions import *
from .providervalidator import torrent_provider_validator
from .provider import TorrentProvider
from .websiteprovider import WebsiteTorrentProvider


logger = logging.getLogger(__name__)


class TorrentProviderManager:

    def __init__(self):
        self.providers = {}

    def add(self, provider: Union[str, dict, TorrentProvider]):
        if isinstance(provider, TorrentProvider):
            logger.debug("Adding provider: {}".format(provider.name))
            self._add(provider)
        elif isinstance(provider, dict):
            logger.debug("Adding provider from dictionary")
            try:
                self._add_from_dict(provider)
            except Exception as e:
                message = "Failed to add provider from dictionary: {}" \
                          .format(str(e))
                raise TorrentSearchEngineError(message) from None
        else:
            # provider can be url or path
            if provider.startswith("http"):
                # url
                logger.debug("Adding provider from url: {}".format(provider))
                try:
                    self._add_from_url(provider)
                except Exception as e:
                    message = "Failed to add provider from url {}: {}" \
                            .format(provider, str(e))
                    raise TorrentSearchEngineError(message) from None
            else:
                # path
                logger.debug("Adding provider from file: {}".format(provider))
                try:
                    self._add_from_file(provider)
                except Exception as e:
                    message = "Failed to add providers from file '{}': {}" \
                              .format(provider, str(e))
                    raise TorrentSearchEngineError(message) from None

    def get(self, name: str) -> Optional[TorrentProvider]:
        return self.providers.get(name, None)

    def get_all(self, enabled=None) -> List[TorrentProvider]:
        return [provider
                for provider in self.providers.values()
                if enabled is None or enabled == provider.enabled]

    def remove(self, *providers: List[Union[TorrentProvider, str]]):
        for provider in providers:
            self._remove(provider)

    def remove_all(self):
        providers = self.get_all()
        self.remove(*providers)

    def disable(self, *providers: List[Union[TorrentProvider, str]]):
        for provider in providers:
            self._disable(provider)

    def disable_all(self):
        providers = self.get_all()
        self.disable(*providers)

    def enable(self, *providers: List[Union[TorrentProvider, str]]):
        for provider in providers:
            self._enable(provider)

    def enable_all(self):
        providers = self.get_all()
        self.enable(*providers)

    def _add(self, provider: TorrentProvider):
        self.providers[provider.name] = provider
        logger.debug("Added provider: {}".format(provider))

    def _add_from_dict(self, provider_dict: dict):
        torrent_provider_validator.validate(provider_dict)
        provider = WebsiteTorrentProvider(**provider_dict)
        self._add(provider)

    def _add_from_file(self, path: str):
        with open(path, 'r', encoding='utf-8') as f:
            provider_dict = json.load(f)

        self._add_from_dict(provider_dict)

    def _add_from_url(self, url: str):
        response = requests.get(url)
        response.raise_for_status()
        provider_dict = json.loads(response.text)
        self._add_from_dict(provider_dict)

    def _remove(self, provider: Union[str, TorrentProvider]):
        provider = provider.name if isinstance(provider, TorrentProvider) \
                                  else provider
        if provider in self.providers:
            del self.providers[provider]
            logger.debug("Removed provider: {}".format(provider))

    def _disable(self, provider: Union[str, TorrentProvider]):
        provider = provider if isinstance(provider, TorrentProvider) \
                            else self.providers.get(provider, None)
        if provider:
            provider.disable()

    def _enable(self, provider: Union[str, TorrentProvider]):
        provider = provider if isinstance(provider, TorrentProvider) \
                            else self.providers.get(provider, None)
        if provider:
            provider.enable()
