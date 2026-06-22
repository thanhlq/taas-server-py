from platform_core import BaseService
from platform_core.types.protocols import Logger
from platform_core.utils.singleton import singleton
from block_kaspa.types import ScriptPublicKeyModel, UtxoModel, UtxoResponse, TxModel
import msgspec
import httpx
from block_kaspa import KaspaSettings
from platform_core.exceptions import NotFoundException
from typing import Dict, Any

from platform_core.serialization import decode_json


@singleton
class KaspaRestClient(BaseService):
    _url: str
    _api_key: str
    _headers: Dict[str, str]
    _settings: KaspaSettings | None
    _debug: bool = False
    """ Debug this kaspa rest client """

    def __init__(self, url: str | None = None):
        self._settings = KaspaSettings()
        self._url = url or self._settings.rest_url
        self._headers = {}
        self._debug = self._settings.debug if self._settings else False
        self.logger.info(f'KaspaRestClient initialized with url: {self._url}')

    def debug(self, message: str, *args: Any) -> None:
        if self._debug:
            self.logger.debug(message, *args)
        else:
            print(f'[DEBUG] {message}', *args)

    @property
    def headers(self) -> Dict[str, str]:
        if not self._headers:
            self._headers = {
                'Accept': 'application/json',
            }
            if self._settings.rest_api_key is not None:  # type: ignore
                self._headers[self._settings.rest_api_key_header_name] = (  # ty:ignore[unresolved-attribute]
                    self._settings.rest_api_key  # ty:ignore[invalid-assignment, unresolved-attribute]
                )
            else:
                self.logger.warning(
                    'Kaspa REST API key is not set. Some endpoints may require an API key.'
                )
        return self._headers

    async def _count_utxos(self, address: str) -> int:
        _url = f'{self._url}/addresses/{address}/utxos/count'
        async with httpx.AsyncClient() as client:
            response = await client.get(_url, params=None, headers=self.headers)

        if response.status_code == 404:
            raise NotFoundException(f'Kaspa address {address} not found at {_url}')
        if response.status_code != 200:
            raise Exception(
                f'fetch_transaction failed with http status code {response.status_code}'
            )

        count = decode_json(response.content, dict[str, int])
        val: int | None = count.get('count', None)
        if val is None:
            raise Exception(f'Kaspa address {address} count is not available at {_url}')
        return val

    async def count_utxos(self, address: str) -> int:
        _utxos: int = await self._count_utxos(address)

        return _utxos

    async def _fetch_utxos(self, address: str) -> list[UtxoResponse]:
        _url = f'{self._url}/addresses/{address}/utxos'

        async with httpx.AsyncClient() as client:
            response = await client.get(_url, params=None, headers=self.headers)

        if response.status_code == 404:
            raise NotFoundException(f'Kaspa address {address} not found at {_url}')
        if response.status_code != 200:
            raise Exception(
                f'fetch_transaction failed with http status code {response.status_code}'
            )

        # The endpoint returns an array of UtxoResponse objects.
        """
        Examples:
          [
            {
              "address": "kaspa:qp2z9h8ggqshjwqucpd0hlrzepuq8v6pvq7fmgqavj9ksztxx2ulktvfeyhrr",
              "outpoint": {
                "transactionId": "5332ca78aa630e59a668e79eea0793ef7c2cab9933179aa37041e3586c2ed935",
                "index": 0
              },
              "utxoEntry": {
                "amount": "100000000",
                "scriptPublicKey": {
                  "scriptPublicKey": "205422dce8402179381cc05afbfc62c87803b341603c9da01d648b68096632b9fbac"
                },
                "blockDaaScore": "464200169",
                "isCoinbase": false
              }
            }
          ]

        """
        return decode_json(response.content, list[UtxoResponse])
        # return response.json()

    async def fetch_utxos(self, address: str) -> list[Dict[str, Any]]:
        _url = f'{self._url}/addresses/{address}/utxos'

        async with httpx.AsyncClient() as client:
            response = await client.get(_url, params=None, headers=self.headers)

        if response.status_code == 404:
            raise NotFoundException(f'Kaspa address {address} not found at {_url}')
        if response.status_code != 200:
            raise Exception(
                f'fetch_transaction failed with http status code {response.status_code}'
            )

        # The endpoint returns an array of UtxoResponse objects.
        """
        Examples:
          [
            {
              "address": "kaspa:qp2z9h8ggqshjwqucpd0hlrzepuq8v6pvq7fmgqavj9ksztxx2ulktvfeyhrr",
              "outpoint": {
                "transactionId": "5332ca78aa630e59a668e79eea0793ef7c2cab9933179aa37041e3586c2ed935",
                "index": 0
              },
              "utxoEntry": {
                "amount": "100000000",
                "scriptPublicKey": {
                  "scriptPublicKey": "205422dce8402179381cc05afbfc62c87803b341603c9da01d648b68096632b9fbac"
                },
                "blockDaaScore": "464200169",
                "isCoinbase": false
              }
            }
          ]

        """
        return decode_json(response.content, list[UtxoResponse])
        # return response.json()

    async def get_utxos(self, address: str) -> list[UtxoResponse]:
        _utxos: list[UtxoResponse] = await self.fetch_utxos(address)

        # self.debug(f'Fetched {_utxos} UTXOs for address {address}')
        # print(f'Fetched {_utxos} UTXOs for address {address}')

        # results: list[UtxoModel] = [item.utxoEntry for item in _utxos]
        return _utxos

    async def get_transaction_by_id(self, transaction_id: str) -> TxModel:
        url = f'{self._url}/transactions/{transaction_id}'
        params = {
            'inputs': 'true',
            'outputs': 'true',
            'resolve_previous_outpoints': 'light',
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=self.headers)

        if response.status_code == 404:
            raise NotFoundException(f'Kaspa tx {transaction_id} not found at {url}')
        if response.status_code != 200:
            raise Exception(
                f'fetch_transaction failed with http status code {response.status_code}'
            )
        data = response.json()
        if data.get('accepting_block_blue_score', None) is None:
            raise Exception(f'blue score is not available for tx {transaction_id}')

        return decode_json(response.content, TxModel)
