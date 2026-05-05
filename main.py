import json
import logging
import os
import sys
import threading
import time                               # added for retry delay
from pathlib import Path
from typing import Optional

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

# Constants
KB = 1024
MB = KB * KB
GB = MB * KB
MULTIPART_THRESHOLD = 400 * MB

logging.basicConfig(level=logging.INFO)

# S3 clients
s3_client = boto3.client(
    's3',
    endpoint_url='endpoint_url',
    aws_access_key_id='access_key',
    aws_secret_access_key='secret_key'
)

s3_resource = boto3.resource(
    's3',
    endpoint_url='endpoint_url',
    aws_access_key_id='access_key',
    aws_secret_access_key='secret_key'
)


class ProgressPercentage:
    def __init__(self, file_path: str):
        self._file_path = file_path
        self._size = float(os.path.getsize(file_path))
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def __call__(self, bytes_amount):
        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = (self._seen_so_far / self._size) * 100
            sys.stdout.write(
                "\r%s  %s / %s  (%.2f%%)" % (
                    self._file_path, self._seen_so_far, self._size, percentage
                )
            )
            sys.stdout.flush()


def upload_file(file_path: str, bucket: str, object_name: Optional[str] = None,
                acl: str = 'public-read') -> bool:
    """
    Uploads a file to an S3 bucket, retrying indefinitely on any error.
    Returns True once the upload succeeds (never returns False).
    """
    if object_name is None:
        object_name = file_path

    file_size = os.path.getsize(file_path)
    logging.info(f"File size: {file_size / MB:.2f} MB")

    while True:   # retry forever until success
        try:
            if file_size <= MULTIPART_THRESHOLD:
                with open(file_path, "rb") as f:
                    s3_resource.Bucket(bucket).put_object(
                        ACL=acl,
                        Body=f,
                        Key=object_name
                    )
                logging.info("Uploaded with simple put_object")
            else:
                config = TransferConfig(
                    multipart_threshold=MULTIPART_THRESHOLD,
                    max_concurrency=5
                )
                s3_client.upload_file(
                    file_path,
                    bucket,
                    object_name,
                    ExtraArgs={'ACL': acl},
                    Callback=ProgressPercentage(file_path),
                    Config=config
                )
                logging.info("Uploaded with multipart upload")
            return True   # success, exit the loop

        except Exception as e:   # catch all errors to guarantee a retry
            logging.error(f"Upload failed: {e}. Retrying in 5 seconds...")
            time.sleep(5)        # short delay before retrying


def upload_directory(local_dir: str, bucket: str, s3_prefix: str = ""):
    base_path = Path(local_dir).resolve()
    if not base_path.is_dir():
        logging.error(f"{local_dir} is not a valid directory")
        return

    all_files = list(base_path.rglob('*'))
    files = [f for f in all_files if f.is_file()]

    if not files:
        logging.warning("No files found to upload")
        return

    logging.info(f"Uploading {len(files)} files from {base_path} to s3://{bucket}/{s3_prefix}")

    for file_path in files:
        relative_path = file_path.relative_to(base_path)
        s3_key = (Path(s3_prefix) / relative_path).as_posix()
        logging.info(f"Uploading {file_path} -> s3://{bucket}/{s3_key}")

        # upload_file now blocks until success (never returns False)
        upload_file(str(file_path), bucket, s3_key)
        logging.info("Upload successful. Deleting local file.")
        os.remove(file_path)      # remove the local copy after successful upload


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py <directory_path>")
        sys.exit(1)

    directory_to_upload = sys.argv[1]
    if not os.path.isdir(directory_to_upload):
        logging.error(f"'{directory_to_upload}' is not a valid directory")
        sys.exit(1)

    bucket_name = "sample_bucket"   # change to your bucket name
    upload_directory(directory_to_upload, bucket_name)
