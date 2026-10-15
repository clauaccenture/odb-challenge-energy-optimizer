import json
import os

import boto3
from dotenv import load_dotenv

load_dotenv()
BUCKET = os.getenv("S3_BUCKET")


def upload_json(obj, key):
    """Guarda un objeto como JSON en s3://BUCKET/key (acceso por rol IAM)."""
    boto3.client("s3").put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
