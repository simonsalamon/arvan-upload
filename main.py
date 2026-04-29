#!/usr/bin/env python3
"""
ArvanCloud Storage CLI – Upload a file or folder to ArvanCloud Object Storage.

Credentials can be provided via:
  1. Command-line options -a / -s
  2. Environment variables ARVAN_ACCESS_KEY / ARVAN_SECRET_KEY
  3. A credentials file (INI format), default: ~/.arvan/credentials
"""

import argparse
import configparser
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError


def get_credentials_file_path(path_arg=None):
    """Return the path to the credentials file."""
    if path_arg:
        return os.path.expanduser(path_arg)
    return os.path.join(Path.home(), ".arvan", "credentials")


def read_credentials_file(filepath, profile="default"):
    """Read access/secret keys from an INI-style credentials file."""
    if not os.path.isfile(filepath):
        return None, None

    config = configparser.ConfigParser()
    config.read(filepath)

    if profile not in config:
        return None, None

    access = config[profile].get("arvan_access_key")
    secret = config[profile].get("arvan_secret_key")
    return access, secret


def resolve_credentials(args):
    """
    Determine final credentials using priority:
      1. CLI args  (-a / -s)
      2. Environment variables
      3. Credentials file (default or specified)
    """
    access = args.access_key
    secret = args.secret_key

    if access and secret:
        return access, secret

    # Try environment
    if not access:
        access = os.environ.get("ARVAN_ACCESS_KEY")
    if not secret:
        secret = os.environ.get("ARVAN_SECRET_KEY")

    if access and secret:
        return access, secret

    # Try credentials file
    cred_file = get_credentials_file_path(args.credentials_file)
    profile = args.profile or "default"
    file_access, file_secret = read_credentials_file(cred_file, profile)
    if file_access and file_secret:
        return file_access, file_secret

    return None, None


def build_client(access_key, secret_key, endpoint_url, region="ir-thr-at1"):
    """Create a boto3 S3 client pointed at ArvanCloud."""
    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint_url,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def upload_single_file(client, bucket, local_path, object_key):
    """Upload one file. Return the object key used."""
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"Not a file: {local_path}")

    print(f"  Uploading: {local_path}  ->  s3://{bucket}/{object_key}")
    client.upload_file(local_path, bucket, object_key)
    return object_key


def upload_directory(client, bucket, local_dir, prefix="", public_read=False):
    """Recursively upload all files inside a directory."""
    local_dir = os.path.abspath(local_dir)
    if not os.path.isdir(local_dir):
        raise NotADirectoryError(f"Not a directory: {local_dir}")

    if not prefix:
        prefix = os.path.basename(local_dir) + "/"
    if not prefix.endswith("/"):
        prefix += "/"

    for root, _, files in os.walk(local_dir):
        for name in files:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, local_dir).replace(os.sep, "/")
            key = prefix + rel_path
            try:
                upload_single_file(client, bucket, full_path, key)
                if public_read:
                    set_public_acl(client, bucket, key)
            except Exception as exc:
                print(f"    ⚠️  Skipped: {full_path} - {exc}", file=sys.stderr)


def set_public_acl(client, bucket, key):
    """Make an object publicly readable."""
    try:
        client.put_object_acl(ACL="public-read", Bucket=bucket, Key=key)
        print(f"    ✓ ACL public-read: s3://{bucket}/{key}")
    except ClientError as exc:
        print(f"    ⚠️  Could not set ACL on {key}: {exc}", file=sys.stderr)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Upload a file or folder to ArvanCloud Object Storage (S3 compatible).",
        epilog="For more help, visit https://docs.arvancloud.ir",
    )

    parser.add_argument("bucket", help="Target bucket name.")
    parser.add_argument("path", help="Local file or directory to upload (directories are recursive).")

    parser.add_argument("-k", "--key",
                        help="Object key for a single file, or base prefix for a directory. "
                             "If omitted, the directory’s own name is used as the prefix.")
    parser.add_argument("-e", "--endpoint",
                        default="https://s3.ir-thr-at1.arvanstorage.ir",
                        help="ArvanCloud S3 endpoint (default: %(default)s).")
    parser.add_argument("-r", "--region",
                        default="ir-thr-at1",
                        help="AWS region (default: %(default)s).")
    parser.add_argument("-a", "--access-key",
                        help="Access key ID (overrides env and file).")
    parser.add_argument("-s", "--secret-key",
                        help="Secret access key (overrides env and file).")
    parser.add_argument("--credentials-file",
                        default=None,
                        help="Path to INI credentials file (default: ~/.arvan/credentials).")
    parser.add_argument("--profile",
                        default="default",
                        help="Profile name in credentials file (default: 'default').")
    parser.add_argument("--public-read",
                        action="store_true",
                        help="Set ACL to 'public-read' on every uploaded object.")

    return parser.parse_args()


def main():
    args = parse_args()
    access_key, secret_key = resolve_credentials(args)

    if not access_key or not secret_key:
        print(
            "❌ Missing credentials. Provide them via -a/-s, environment variables, or a credentials file.\n"
            "   Use --help for details.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = build_client(access_key, secret_key, args.endpoint, args.region)

    given_path = os.path.abspath(args.path)

    if os.path.isdir(given_path):
        print(f"📁 Uploading folder: {given_path}")
        prefix = args.key if args.key else ""
        try:
            upload_directory(client, args.bucket, given_path, prefix, args.public_read)
        except Exception as exc:
            print(f"❌ Folder upload failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif os.path.isfile(given_path):
        object_key = args.key or os.path.basename(given_path)
        try:
            upload_single_file(client, args.bucket, given_path, object_key)
            if args.public_read:
                set_public_acl(client, args.bucket, object_key)
        except Exception as exc:
            print(f"❌ Upload failed: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"❌ Path not found or unsupported: {given_path}", file=sys.stderr)
        sys.exit(1)

    print("✅ Done.")


if __name__ == "__main__":
    main()
