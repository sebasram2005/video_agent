#!/usr/bin/env python3
"""
upload_to_r2.py — Upload local gameplay clips to Cloudflare R2.

Reads credentials from .env or environment variables:
  R2_ACCOUNT_ID      Cloudflare account ID (from R2 dashboard)
  R2_ACCESS_KEY_ID   R2 API token access key
  R2_SECRET_ACCESS_KEY  R2 API token secret
  R2_BUCKET_NAME     Bucket name (e.g. reddit-gameplay)
  R2_PUBLIC_URL      Public base URL (e.g. https://pub.r2.dev/reddit-gameplay)
                     or custom domain (https://clips.yourdomain.com)

Usage:
  python scripts/upload_to_r2.py              # upload all new clips
  python scripts/upload_to_r2.py --force      # re-upload even if already there
  python scripts/upload_to_r2.py --list       # show what's in R2

Setup (one time):
  1. Go to dash.cloudflare.com → R2 → Create bucket
  2. Enable "Public Access" on the bucket
  3. Go to Manage R2 API Tokens → Create Token (Object Read & Write)
  4. Add credentials to .env
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR     = Path(__file__).parent.parent
GAMEPLAY_DIR = BASE_DIR / "assets" / "gameplay"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def _get_cfg() -> dict:
    cfg = {
        "account_id":   os.getenv("R2_ACCOUNT_ID", "").strip(),
        "access_key":   os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        "secret_key":   os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        "bucket":       os.getenv("R2_BUCKET_NAME", "reddit-gameplay").strip(),
        "public_url":   os.getenv("R2_PUBLIC_URL", "").strip().rstrip("/"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        print("ERROR: Missing environment variables:")
        for k in missing:
            env_key = f"R2_{k.upper()}" if k != "access_key" else "R2_ACCESS_KEY_ID"
            print(f"  {env_key}")
        print("\nAdd them to your .env file.")
        sys.exit(1)
    return cfg


def _s3_client(cfg: dict):
    try:
        import boto3
    except ImportError:
        print("ERROR: boto3 not installed. Run: pip install boto3")
        sys.exit(1)
    return boto3.client(
        "s3",
        endpoint_url=f"https://{cfg['account_id']}.r2.cloudflarestorage.com",
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name="auto",
    )


def _list_r2_keys(s3, bucket: str) -> set[str]:
    keys: set[str] = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


def _upload_clip(s3, bucket: str, clip: Path) -> bool:
    key = f"clips/{clip.name}"
    size_mb = clip.stat().st_size / 1_048_576
    print(f"  Uploading {clip.name}  ({size_mb:.1f} MB) ...", end=" ", flush=True)
    try:
        s3.upload_file(
            str(clip), bucket, key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def _build_manifest(s3, bucket: str, public_url: str) -> dict:
    """Fetch all clips from R2 and build a manifest JSON."""
    keys = _list_r2_keys(s3, bucket)
    clip_keys = sorted(k for k in keys if k.startswith("clips/") and k.endswith(".mp4"))

    clips = []
    for key in clip_keys:
        name  = key.split("/")[-1]   # e.g. minecraft_003.mp4
        style = name.split("_")[0]   # e.g. minecraft
        clips.append({
            "key":   key,
            "url":   f"{public_url}/{key}",
            "name":  name,
            "style": style,
        })

    return {"total": len(clips), "clips": clips}


def _push_manifest(s3, bucket: str, manifest: dict) -> None:
    body = json.dumps(manifest, indent=2, ensure_ascii=False).encode()
    s3.put_object(
        Bucket=bucket,
        Key="manifest.json",
        Body=body,
        ContentType="application/json",
    )
    print(f"  manifest.json updated — {manifest['total']} clips indexed")


def main():
    parser = argparse.ArgumentParser(description="Upload gameplay clips to Cloudflare R2")
    parser.add_argument("--force", action="store_true", help="Re-upload even if already in R2")
    parser.add_argument("--list",  action="store_true", help="List clips currently in R2")
    args = parser.parse_args()

    cfg = _get_cfg()
    s3  = _s3_client(cfg)

    if args.list:
        print(f"\nFetching R2 bucket: {cfg['bucket']} ...")
        manifest_obj = None
        try:
            resp = s3.get_object(Bucket=cfg["bucket"], Key="manifest.json")
            manifest_obj = json.loads(resp["Body"].read())
        except Exception:
            pass

        if manifest_obj:
            print(f"\nmanifest.json: {manifest_obj['total']} clips\n")
            by_style: dict[str, int] = {}
            for c in manifest_obj["clips"]:
                by_style[c["style"]] = by_style.get(c["style"], 0) + 1
            for style, count in sorted(by_style.items()):
                print(f"  {style}: {count} clips")
        else:
            keys = _list_r2_keys(s3, cfg["bucket"])
            clip_keys = [k for k in keys if k.startswith("clips/")]
            print(f"\nR2 clips: {len(clip_keys)} (no manifest.json yet)")
            for k in sorted(clip_keys)[:20]:
                print(f"  {k}")
            if len(clip_keys) > 20:
                print(f"  ... and {len(clip_keys) - 20} more")
        return

    # ── Upload ────────────────────────────────────────────────────────────────
    local_clips = sorted(GAMEPLAY_DIR.glob("*.mp4"))
    if not local_clips:
        print(f"No clips in {GAMEPLAY_DIR}")
        print("Run: python scripts/download_gameplay_batch.py")
        sys.exit(1)

    existing_keys = _list_r2_keys(s3, cfg["bucket"]) if not args.force else set()

    uploaded = 0
    skipped  = 0
    failed   = 0

    print(f"\nUploading to R2 bucket '{cfg['bucket']}' ...")
    print(f"{'─'*50}")

    for clip in local_clips:
        key = f"clips/{clip.name}"
        if key in existing_keys:
            print(f"  Skipping {clip.name} (already in R2)")
            skipped += 1
            continue
        ok = _upload_clip(s3, cfg["bucket"], clip)
        if ok:
            uploaded += 1
        else:
            failed += 1

    print(f"{'─'*50}")
    print(f"Uploaded: {uploaded}  Skipped: {skipped}  Failed: {failed}")

    # Always rebuild manifest after upload
    print("\nRebuilding manifest.json ...")
    manifest = _build_manifest(s3, cfg["bucket"], cfg["public_url"])
    _push_manifest(s3, cfg["bucket"], manifest)

    print(f"\nPublic URL: {cfg['public_url']}/manifest.json")
    print("Add to GitHub Secrets: R2_PUBLIC_URL")
    print("Done.\n")


if __name__ == "__main__":
    main()
