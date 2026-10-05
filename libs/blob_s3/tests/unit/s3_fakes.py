"""In-memory fake of the aiobotocore S3 client surface used by S3BlobAdapter (raises botocore ClientError)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from botocore.exceptions import ClientError


def client_error(code: str, operation: str, status: int = 400) -> ClientError:
    return ClientError(
        {
            'Error': {'Code': code, 'Message': code},
            'ResponseMetadata': {'HTTPStatusCode': status},
        },
        operation,
    )


@dataclass
class _Object:
    body: bytes
    content_type: str
    metadata: dict[str, str]
    etag: str
    last_modified: datetime


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self) -> _Body:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._data


@dataclass
class FakeS3Client:
    buckets: dict[str, dict[str, _Object]] = field(
        default_factory=dict[str, dict[str, _Object]]
    )
    calls: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    other_account_buckets: set[str] = field(default_factory=set[str])

    def _bucket(self, name: str, operation: str) -> dict[str, _Object]:
        if name not in self.buckets:
            raise client_error('NoSuchBucket', operation, 404)
        return self.buckets[name]

    async def create_bucket(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(('create_bucket', kw))
        if kw['Bucket'] in self.other_account_buckets:
            raise client_error('BucketAlreadyExists', 'CreateBucket', 409)
        if kw['Bucket'] in self.buckets:
            raise client_error('BucketAlreadyOwnedByYou', 'CreateBucket', 409)
        self.buckets[kw['Bucket']] = {}
        return {}

    async def head_bucket(self, **kw: Any) -> dict[str, Any]:
        if kw['Bucket'] in self.other_account_buckets:
            raise client_error('403', 'HeadBucket', 403)
        if kw['Bucket'] not in self.buckets:
            raise client_error('404', 'HeadBucket', 404)
        return {}

    async def delete_bucket(self, **kw: Any) -> dict[str, Any]:
        bucket = self._bucket(kw['Bucket'], 'DeleteBucket')
        if bucket:
            raise client_error('BucketNotEmpty', 'DeleteBucket', 409)
        del self.buckets[kw['Bucket']]
        return {}

    async def put_object(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(('put_object', kw))
        bucket = self._bucket(kw['Bucket'], 'PutObject')
        body: bytes = kw['Body']
        etag = hashlib.md5(body, usedforsecurity=False).hexdigest()
        bucket[kw['Key']] = _Object(
            body=body,
            content_type=kw.get('ContentType', 'binary/octet-stream'),
            metadata={k.lower(): v for k, v in kw.get('Metadata', {}).items()},
            etag=etag,
            last_modified=datetime.now(UTC),
        )
        return {'ETag': f'"{etag}"'}

    def _head(self, obj: _Object) -> dict[str, Any]:
        return {
            'ContentLength': len(obj.body),
            'ContentType': obj.content_type,
            'ETag': f'"{obj.etag}"',
            'LastModified': obj.last_modified,
            'Metadata': dict(obj.metadata),
        }

    async def get_object(self, **kw: Any) -> dict[str, Any]:
        obj = self._bucket(kw['Bucket'], 'GetObject').get(kw['Key'])
        if obj is None:
            raise client_error('NoSuchKey', 'GetObject', 404)
        return {**self._head(obj), 'Body': _Body(obj.body)}

    async def head_object(self, **kw: Any) -> dict[str, Any]:
        obj = self.buckets.get(kw['Bucket'], {}).get(kw['Key'])
        if obj is None:
            raise client_error('404', 'HeadObject', 404)
        return self._head(obj)

    async def delete_object(self, **kw: Any) -> dict[str, Any]:
        self._bucket(kw['Bucket'], 'DeleteObject').pop(kw['Key'], None)
        return {}

    async def delete_objects(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(('delete_objects', kw))
        bucket = self._bucket(kw['Bucket'], 'DeleteObjects')
        objects = kw['Delete']['Objects']
        assert len(objects) <= 1000
        for item in objects:
            bucket.pop(item['Key'], None)
        return {}

    async def copy_object(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(('copy_object', kw))
        bucket = self._bucket(kw['Bucket'], 'CopyObject')
        source = self._bucket(kw['CopySource']['Bucket'], 'CopyObject').get(
            kw['CopySource']['Key']
        )
        if source is None:
            raise client_error('NoSuchKey', 'CopyObject', 404)
        assert kw.get('MetadataDirective') == 'COPY'
        bucket[kw['Key']] = _Object(
            body=source.body,
            content_type=source.content_type,
            metadata=dict(source.metadata),
            etag=source.etag,
            last_modified=datetime.now(UTC),
        )
        return {}

    async def list_objects_v2(self, **kw: Any) -> dict[str, Any]:
        bucket = self._bucket(kw['Bucket'], 'ListObjectsV2')
        keys = sorted(k for k in bucket if k.startswith(kw.get('Prefix', '')))
        token = kw.get('ContinuationToken')
        if token:
            keys = [k for k in keys if k > token]
        page = keys[: kw['MaxKeys']]
        truncated = len(keys) > kw['MaxKeys']
        response: dict[str, Any] = {
            'IsTruncated': truncated,
            'Contents': [
                {
                    'Key': k,
                    'Size': len(bucket[k].body),
                    'ETag': f'"{bucket[k].etag}"',
                    'LastModified': bucket[k].last_modified,
                }
                for k in page
            ],
        }
        if truncated:
            response['NextContinuationToken'] = page[-1]
        return response

    async def generate_presigned_url(
        self, method: str, Params: dict[str, Any], ExpiresIn: int
    ) -> str:  # noqa: N803
        self.calls.append(
            (
                'generate_presigned_url',
                {'method': method, 'Params': Params, 'ExpiresIn': ExpiresIn},
            )
        )
        return f'https://fake-s3/{Params["Bucket"]}/{quote(Params["Key"])}?X-Amz-Expires={ExpiresIn}'
