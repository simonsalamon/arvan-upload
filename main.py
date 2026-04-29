import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

# Constants
KB = 1024
MB = KB * KB
GB = MB * KB

logging.basicConfig(level=logging.INFO)

# S3 client (fix the typo in the secret key!)
s3_client = boto3.client(
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


def upload_file(file_path: str, bucket: str, object_name: Optional[str] = None):
    """Upload a single file to S3."""
    if object_name is None:
        object_name = file_path

    try:
        config = TransferConfig(multipart_threshold=400 * MB, max_concurrency=5)
        s3_client.upload_file(
            file_path,
            bucket,
            object_name,
            ExtraArgs={'ACL': 'public-read'},
            Callback=ProgressPercentage(file_path),
            Config=config
        )
    except ClientError as e:
        logging.error(f"Failed to upload {file_path}: {e}")
        return False
    return True


def upload_directory(local_dir: str, bucket: str, s3_prefix: str = ""):
    """
    Upload all files from a local directory to an S3 bucket.
    
    :param local_dir: Path to the local directory (e.g., 'files')
    :param bucket: Target S3 bucket
    :param s3_prefix: Optional prefix (folder) inside the bucket.
                      Empty string means upload to bucket root.
    """
    base_path = Path(local_dir).resolve()
    if not base_path.is_dir():
        logging.error(f"{local_dir} is not a valid directory")
        return

    # Collect all files (change pattern if you need e.g. '*.png')
    all_files = list(base_path.rglob('*'))  # rglob includes subdirectories
    # Filter out directories, keep only files
    files = [f for f in all_files if f.is_file()]

    if not files:
        logging.warning("No files found to upload")
        return

    logging.info(f"Uploading {len(files)} files from {base_path} to s3://{bucket}/{s3_prefix}")

    for file_path in files:
        # Compute relative path from the base directory
        relative_path = file_path.relative_to(base_path)
        # Build the S3 key (join prefix and relative path, forward‑slash style)
        s3_key = (Path(s3_prefix) / relative_path).as_posix()

        logging.info(f"Uploading {file_path} -> s3://{bucket}/{s3_key}")
        success = upload_file(str(file_path), bucket, s3_key)
        if success:
            logging.info("OK")
        else:
            logging.error(f"Upload failed for {file_path}")


if __name__ == "__main__":
    # Example: upload everything from the 'files' folder
    base_directory = "/path/to/your/project"  # change this
    directory_to_upload = os.path.join(base_directory, "files")
    bucket_name = "sample_bucket"

    upload_directory(directory_to_upload, bucket_name, s3_prefix="")
