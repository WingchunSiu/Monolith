"""Configuration constants for DeepRecurse."""

# S3 / CloudBucketMount
BUCKET_NAME = "deeprecurse-transcripts"  # single bucket, repos as subdirectories
MOUNT_PATH = "/transcripts"  # where the bucket is mounted inside Modal

# Models
ROOT_MODEL = "gpt-5"
RECURSIVE_MODEL = "gpt-5-nano"

# RLM
MAX_ITERATIONS = 10

# Modal
MODAL_APP_NAME = "deeprecurse"
MODAL_SECRET_NAME = "aws-creds"
MODAL_IMAGE_PYTHON = "3.12"
