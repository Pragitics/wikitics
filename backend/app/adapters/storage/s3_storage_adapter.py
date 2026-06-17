from pathlib import PurePosixPath

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class S3DocumentStorageAdapter:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        region: str = "us-east-1",
        auto_create_bucket: bool = False,
        force_path_style: bool = True,
    ) -> None:
        if not bucket:
            raise ValueError("S3 bucket is required")
        self.bucket = bucket
        self.region = region
        self.auto_create_bucket = auto_create_bucket
        self._bucket_checked = False
        config = Config(s3={"addressing_style": "path"}) if force_path_style else None
        client_kwargs = {
            "service_name": "s3",
            "region_name": region,
            "config": config,
        }
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key_id:
            client_kwargs["aws_access_key_id"] = access_key_id
        if secret_access_key:
            client_kwargs["aws_secret_access_key"] = secret_access_key
        self.client = boto3.client(**client_kwargs)

    def save_bytes(self, path: str, content: bytes) -> str:
        key = self._key(path)
        self._ensure_bucket()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content)
        return key

    def read_bytes(self, path: str) -> bytes:
        key = self._key(path)
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def save_text(self, path: str, content: str) -> str:
        return self.save_bytes(path, content.encode("utf-8"))

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def exists(self, path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except ClientError as exc:
            if _client_error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete(self, path: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(path))

    def delete_prefix(self, prefix: str) -> None:
        prefix_key = self._key(prefix).rstrip("/") + "/"
        continuation_token: str | None = None
        while True:
            params = {"Bucket": self.bucket, "Prefix": prefix_key}
            if continuation_token:
                params["ContinuationToken"] = continuation_token
            response = self.client.list_objects_v2(**params)
            objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True})
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")

    def _ensure_bucket(self) -> None:
        if self._bucket_checked:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if not self.auto_create_bucket or _client_error_code(exc) not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            create_args = {"Bucket": self.bucket}
            if self.region != "us-east-1":
                create_args["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            self.client.create_bucket(**create_args)
        self._bucket_checked = True

    def _key(self, path: str) -> str:
        parsed = PurePosixPath(path)
        key = str(parsed)
        if not key or key == "." or key.startswith("/") or ".." in parsed.parts:
            raise ValueError("invalid storage path")
        return key


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))
