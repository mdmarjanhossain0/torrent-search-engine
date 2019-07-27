from typing import Any, List, Optional
import re
import requests
import logging
import time
import jsonschema
from .utils import urljoin, urlfix
from .providervalidator import torrent_provider_validator
from .exceptions import *
from .scraper import Scraper
from .scraper.selector import Selector, NullSelector
from .torrent import Torrent


logger = logging.getLogger(__name__)


class TorrentProvider:

    def __init__(self, validate=True, **kwargs):
        if validate:
            self._validate(kwargs)

        self.enabled = True
        # extract data
        self.name = kwargs.get('name')
        self.fullname = kwargs.get('fullname', self.name)
        self.url = kwargs.get('url')

        list_section = kwargs.get('list', {})
        list_item_section = list_section.get('item', {})
        item_section = kwargs.get('item', {})

        self.headers = kwargs.get('headers')
        self.search_path = kwargs.get('search')
        self.categories = kwargs.get('categories')
        self.whitespace_char = kwargs.get('whitespace')

        # parse selectors
        self.next_page_selector = Selector.parse(list_section.get('next', ""))
        self.items_selector = Selector.parse(list_section.get('items', ""))
        self.list_item_selectors = {key: Selector.parse(sel)
                                    for key, sel in list_item_section.items()}
        self.item_selectors = {key: Selector.parse(sel)
                               for key, sel in item_section.items()}

    def search(self, query: str, category=None, limit=None, timeout=None):
        """
        Search torrents using this provider.

        Parameters:
            query: str - The query to perform.
            category: str - The category to search.
            limit: int - The number of results to return.
            timeout: int - The max number of seconds to wait.
                           If the search lasts longer than timeout,
                           raise TimeoutError.

        Yields:
            Torrent - The search results are yielded as they are retrieved.

        Raises:
            ParseError - Something went wrong parsing the page received.
            RequestError - Something went wrong requesting the search page.
            Timeout - The search lasted longer than timeout.
            FormatError - There was an error formatting the search path.
            NotSupportedError - The category is not supported.
        """

        if timeout is not None:
            start_time = time.time()
            elapsed_time = 0

        remaining = limit

        path = self._format_search_path(query)

        while path and (not limit or remaining > 0):
            if timeout is not None:
                elapsed_time = time.time() - start_time
                current_timeout = timeout - elapsed_time
            else:
                current_timeout = None

            response = self.fetch(path, headers=self.headers,
                                  timeout=current_timeout)

            try:
                scraper = Scraper(response.text)
            except ValueError as e:
                raise ParseError(e) from e

            items = scraper.select_elements(self.items_selector,
                                            limit=remaining)
            for item in items:
                torrent_data = self._get_torrent_data(item)
                try:
                    torrent = Torrent(**torrent_data)
                    yield torrent
                except ValueError:
                    # the torrent is missing some important properties
                    # in this case we dont return the torrent
                    pass

            remaining -= len(items)

            path = scraper.select_one(self.next_page_selector)

    def fetch_details_data(self, torrent: Torrent, timeout=None) -> dict:
        """
        Fetch torrent details data (e.g link, description, files, ecc)
        from the Torrent's info_url.

        Parameters:
            torrent: Torrent - The torrent that we want the details of.
            timeout: int - Timeout in seconds.

        Returns:
            dict - Torrent details.

        Raises:
            ParseError - Something went wrong parsing the page received.
            RequestError - Something went wrong requesting the search page.
            Timeout - The search lasted longer than timeout.
        """

        # retrieve the info page url
        path = torrent.info_url
        if not path:
            # basically we return the same data of the torrent
            return {}

        # fetch the torrent info page and scrape
        response = self.fetch(path, timeout=timeout)
        try:
            scraper = Scraper(response.text)
        except ValueError as e:
            raise ParseError(e) from e

        details_data = self._get_torrent_details_data(scraper)

        return details_data

    def fetch(self, url: str, **kwargs) -> requests.Response:
        """
        Retrieve a page.

        Raises:
            RequestError - Something went wrong.
            Timeout - Request timed out.
        """
        if not url.startswith('http'):
            url = urljoin(self.url, url)
        url = urlfix(url)

        logger.debug("{}: GET {}".format(self.name, url))

        try:
            response = requests.get(url, **kwargs)
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            raise Timeout(e) from e
        except requests.exceptions.RequestException as e:
            raise RequestError(e) from e

        return response

    def enable(self):
        self.enabled = True
        logger.debug("{}: enabled.".format(self))

    def disable(self):
        self.enabled = False
        logger.debug("{}: disabled.".format(self))

    def asdict(self) -> dict:
        return {
            "name": self.name,
            "fullname": self.fullname,
            "url": self.url,
            "enabled": self.enabled
        }

    def __str__(self):
        return self.name

    def _validate(self, data: dict):
        try:
            torrent_provider_validator.validate(data)
        except jsonschema.ValidationError as e:
            raise ValidationError(e) from e

    def _format_search_path(self, query, category):
        query = query.strip()
        # replace whitespace with whitespace character
        if self.whitespace_char:
            query = re.sub(r"\s+", self.whitespace_char, query)

        category_path = self._get_category_path(category)

        try:
            if category_path is not None:
                category_path = category_path.format(query=query)
            path = path.format(category=category_path, query=query)
        except KeyError as e:
            message = "{} with query = {} and category = {}" \
                      .format(self.search_path, query, category)
            raise FormatError(message)
        return path

    def _get_category_path(self, category):
        if category is None:
            category == "all"
        if not self.categories:
            if category == "all":
                return None
            else:
                message = "{}: category {} is not supported." \
                          .format(self.name, category)
                raise NotSupportedError(message)
        else:
            if category in self.categories:
                return self.categories.get(category)
            else:
                message = "{}: category {} is not supported." \
                          .format(self.name, category)
                raise NotSupportedError(message)

    def _get_torrent_data(self, element):
        props = {"provider": self}
        for key, selector in self.list_item_selectors.items():
            prop = element.select_one(selector)
            props[key] = prop

        # make the url full (with the host)
        url = props.get('info_url', '')
        if url and not url.startswith('http'):
            url = urljoin(self.url, url)
            url = urlfix(url)
            props['info_url'] = url

        return props

    def _get_torrent_details_data(self, element):
        props = {}
        # retrieve the info page selectors
        for key, selector in self.item_selectors.items():
            # for some properties we need to select all elements that match
            if key == "files" or key == "trackers":
                prop = element.select(selector)
            else:
                prop = element.select_one(selector)
            props[key] = prop

        # make the uploader url full (add the host)
        url = props.get('uploader_url', None)
        if url and not url.startswith('http'):
            url = urljoin(self.url, url)
            url = urlfix(url)
            props['uploader_url'] = url
        return props