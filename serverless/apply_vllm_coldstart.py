#!/usr/bin/env python3
"""Tune the live chat vLLM serverless endpoint for faster cold starts.

Does not set workersMin=1 (that bills a 48GB GPU 24/7). Instead:

  * idleTimeout=900 (15 minutes)
  * scalerValue=1
  * MODEL_NAME for RunPod host-side cached Qwen 14B AWQ
  * DOWNLOAD_DIR/HF_HOME on the host cache mount (/runpod-volume/huggingface-cache)
  * ENFORCE_EAGER so vLLM skips CUDA-graph capture on boot
  * No user network volume by default — attaching one pins the endpoint to a
    single DC, shadows the host cache, and workers sit THROTTLED for minutes

Usage:
  python3 serverless/apply_vllm_coldstart.py --dry-run
  python3 serverless/apply_vllm_coldstart.py
  python3 serverless/apply_vllm_coldstart.py --attach-volume   # opt-in, slower

Reads RUNPOD_API_KEY and endpoint/template IDs from the environment or tokens.env.
Never prints secret values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

REST = os.environ.get("RUNPOD_REST_URL", "https://rest.runpod.io/v1").rstrip("/")
REST_V2 = os.environ.get("RUNPOD_REST_V2_URL", "https://v2-rest.runpod.io/v2").rstrip("/")
ENDPOINT_ID_DEFAULT = "4kjnsgh3pek3vu"
TEMPLATE_ID_DEFAULT = "oynmb132ae"
VOLUME_NAME = "pastor-ai-vllm-cache"
VOLUME_SIZE_GB = 80
CANDIDATE_DCS = ("US-KS-2", "US-GA-1", "US-NC-1", "EU-RO-1")
FORBIDDEN_DCS = {"US-NE-1"}
MODEL_NAME = "Qwen/Qwen2.5-14B-Instruct-AWQ"
HF_CACHE = "/runpod-volume/huggingface-cache"
VLLM_CACHE = "/runpod-volume/vllm_cache"
IDLE_TIMEOUT = 900
SCALER_VALUE = 1
SECRET_KEYS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "AUTH")


def log(msg: str) -> None:
    print(f"[*] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[!] {msg}", file=sys.stderr, flush=True)


def die(msg: str) -> None:
    print(f"[✘] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            upper = str(key).upper()
            if any(token in upper for token in SECRET_KEYS) and isinstance(value, str) and value:
                out[key] = value[:4] + "***redacted***"
            else:
                out[key] = redact(value)
        return out
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    return obj


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def env_as_dict(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("name")
            if not key:
                continue
            out[str(key)] = "" if item.get("value") is None else str(item.get("value"))
        return out
    return {}


# Qwen2.5-14B native context. 48GB AWQ+LoRA has VRAM for 32k if concurrency stays low.
# Default MAX_NUM_SEQS=256 would OOM at 32k; cap it for single-worker chat.
SERVERLESS_MAX_MODEL_LEN = "32768"
SERVERLESS_MAX_NUM_SEQS = "4"


def merge_vllm_env(existing: dict[str, str]) -> dict[str, str]:
    merged = dict(existing)
    merged["MODEL_NAME"] = merged.get("MODEL_NAME") or MODEL_NAME
    # Host-side RunPod cached models mount here when no user volume is attached.
    merged["DOWNLOAD_DIR"] = HF_CACHE
    merged["HF_HOME"] = HF_CACHE
    merged["VLLM_CACHE_ROOT"] = VLLM_CACHE
    # Skip CUDA-graph capture on cold start (large share of vLLM boot time).
    merged["ENFORCE_EAGER"] = merged.get("ENFORCE_EAGER") or "true"
    merged["DISABLE_LOG_STATS"] = merged.get("DISABLE_LOG_STATS") or "1"
    merged["DISABLE_LOG_REQUESTS"] = merged.get("DISABLE_LOG_REQUESTS") or "1"
    merged["MAX_MODEL_LEN"] = SERVERLESS_MAX_MODEL_LEN
    merged["MAX_NUM_SEQS"] = SERVERLESS_MAX_NUM_SEQS
    merged["MAX_NUM_BATCHED_TOKENS"] = SERVERLESS_MAX_MODEL_LEN
    return merged


def api_key() -> str:
    key = (os.environ.get("RUNPOD_API_KEY") or "").strip()
    if not key or "paste_here" in key.lower():
        die("RUNPOD_API_KEY is required")
    return key


def request(method: str, url: str, body: Optional[dict] = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = json.dumps(redact(parsed), indent=2)
        except Exception:
            detail = detail[:800]
        raise RuntimeError(f"{method} {url} → HTTP {exc.code}\n{detail}") from exc


def rest(method: str, path: str, body: Optional[dict] = None) -> Any:
    return request(method, f"{REST}{path}", body)


def pick_volume(volumes: list[dict], requested_id: str, requested_dc: str) -> Optional[dict]:
    if requested_id:
        for vol in volumes:
            if str(vol.get("id") or "") == requested_id:
                return vol
    named = [
        vol
        for vol in volumes
        if str(vol.get("name") or "") == VOLUME_NAME
        and str(vol.get("dataCenterId") or "") not in FORBIDDEN_DCS
    ]
    if requested_dc:
        for vol in named:
            if str(vol.get("dataCenterId") or "") == requested_dc:
                return vol
    return named[0] if named else None


def create_volume(data_center: str, dry_run: bool) -> dict:
    payload = {"name": VOLUME_NAME, "size": VOLUME_SIZE_GB, "dataCenterId": data_center}
    log(f"Creating {VOLUME_SIZE_GB}GB volume {VOLUME_NAME} in {data_center}")
    if dry_run:
        return {"id": "dry-run-volume", "dataCenterId": data_center, "name": VOLUME_NAME, "size": VOLUME_SIZE_GB}
    last_error = None
    for dc in (data_center, *CANDIDATE_DCS):
        if dc in FORBIDDEN_DCS:
            continue
        try:
            created = rest("POST", "/networkvolumes", {**payload, "dataCenterId": dc})
            log(f"Created volume {created.get('id')} in {created.get('dataCenterId') or dc}")
            return created
        except Exception as exc:
            last_error = exc
            warn(f"Could not create volume in {dc}: {exc}")
    die(f"Could not create a serverless network volume: {last_error}")
    raise AssertionError("unreachable")


def try_set_cached_model(endpoint_id: str, dry_run: bool) -> bool:
    """Official vLLM workers honor MODEL_NAME for RunPod's host-side cache.

    REST v2 has no Model field; GraphQL EndpointInput also rejects `model`.
    """
    log(f"Cached weights use MODEL_NAME={MODEL_NAME} (host cache + {HF_CACHE})")
    if dry_run:
        return True
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--endpoint-id", default=os.environ.get("RUNPOD_VLLM_ENDPOINT_ID", ENDPOINT_ID_DEFAULT))
    parser.add_argument("--template-id", default=os.environ.get("RUNPOD_VLLM_TEMPLATE_ID", TEMPLATE_ID_DEFAULT))
    parser.add_argument("--volume-id", default=os.environ.get("RUNPOD_NETWORK_VOLUME_ID", ""))
    parser.add_argument("--data-center", default=os.environ.get("RUNPOD_DATA_CENTER_IDS", "").split(",")[0].strip())
    parser.add_argument(
        "--attach-volume",
        action="store_true",
        help="Pin a user network volume (slower: one DC + shadows host model cache)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / "tokens.env")
    load_dotenv(root / "config.env")

    endpoint_id = args.endpoint_id.strip() or ENDPOINT_ID_DEFAULT
    template_id = args.template_id.strip() or TEMPLATE_ID_DEFAULT
    requested_dc = args.data_center.strip()
    if requested_dc in FORBIDDEN_DCS:
        die(f"{requested_dc} is the CPU-pod data center and cannot host serverless vLLM")

    log(f"Endpoint {endpoint_id} template {template_id}")
    endpoint = rest("GET", f"/endpoints/{endpoint_id}")
    template = rest("GET", f"/templates/{template_id}")
    volumes_raw = rest("GET", "/networkvolumes")
    volumes = volumes_raw if isinstance(volumes_raw, list) else volumes_raw.get("networkVolumes") or volumes_raw.get("data") or []
    if not isinstance(volumes, list):
        volumes = []

    cpu_volume = next((vol for vol in volumes if str(vol.get("id") or "") == "int0elzo4l"), None)
    if cpu_volume:
        log("CPU volume int0elzo4l is present and will not be attached to serverless")

    volume_id = ""
    data_center = ""
    if args.attach_volume:
        volume = pick_volume(volumes, args.volume_id.strip(), requested_dc)
        if volume and str(volume.get("dataCenterId") or "") in FORBIDDEN_DCS:
            die("Refusing to attach a US-NE-1 / CPU-pod volume to serverless vLLM")
        if volume is None:
            volume = create_volume(requested_dc or CANDIDATE_DCS[0], args.dry_run)
        volume_id = str(volume.get("id") or "")
        data_center = str(volume.get("dataCenterId") or requested_dc or "")
        log(f"Using volume {volume_id} in {data_center} ({volume.get('name')}, {volume.get('size')}GB)")
    else:
        log("Leaving user network volumes detached so workers can use host-cached MODEL_NAME in any DC")

    existing_env = env_as_dict(template.get("env"))
    new_env = merge_vllm_env(existing_env)
    log("Template env keys after merge: " + ", ".join(sorted(new_env)))
    print(json.dumps(redact({"DOWNLOAD_DIR": new_env.get("DOWNLOAD_DIR"), "HF_HOME": new_env.get("HF_HOME"), "VLLM_CACHE_ROOT": new_env.get("VLLM_CACHE_ROOT"), "MODEL_NAME": new_env.get("MODEL_NAME"), "ENFORCE_EAGER": new_env.get("ENFORCE_EAGER")}), indent=2))

    endpoint_patch = {
        "idleTimeout": IDLE_TIMEOUT,
        "scalerType": "QUEUE_DELAY",
        "scalerValue": SCALER_VALUE,
        "flashboot": True,
        "workersMin": int(endpoint.get("workersMin") or 0),
        "workersMax": int(endpoint.get("workersMax") or 1),
    }
    if volume_id:
        endpoint_patch["networkVolumeId"] = volume_id
        if data_center:
            endpoint_patch["dataCenterIds"] = [data_center]
    else:
        endpoint_patch["networkVolumeId"] = ""
        endpoint_patch["dataCenterIds"] = []
    if endpoint_patch["workersMin"] != 0:
        warn(f"Leaving workersMin={endpoint_patch['workersMin']} unchanged (not forcing 1)")
    log("Endpoint patch (redacted):")
    print(json.dumps(redact(endpoint_patch), indent=2))

    if args.dry_run:
        log("Dry run only — no template/endpoint changes were sent.")
        return 0

    rest("PATCH", f"/templates/{template_id}", {"env": new_env})
    log("Patched vLLM template env (full merge, secrets preserved)")
    rest("PATCH", f"/endpoints/{endpoint_id}", endpoint_patch)
    log("Patched vLLM endpoint idleTimeout/scaler")
    v2_body = {
        "networkVolumes": [volume_id] if volume_id else [],
        "dataCenterIds": [data_center] if data_center else [],
        "env": new_env,
    }
    try:
        request("PATCH", f"{REST_V2}/serverless/{endpoint_id}", v2_body)
        log(f"v2 networkVolumes={v2_body['networkVolumes']} dataCenterIds={v2_body['dataCenterIds']}")
    except Exception as exc:
        warn(f"v2 volume/DC patch skipped: {exc}")
    try_set_cached_model(endpoint_id, dry_run=False)

    updated = rest("GET", f"/endpoints/{endpoint_id}")
    log(
        "Live endpoint: "
        f"idleTimeout={updated.get('idleTimeout')} "
        f"scalerValue={updated.get('scalerValue')} "
        f"workersMin={updated.get('workersMin')} "
        f"networkVolumeId={updated.get('networkVolumeId')} "
        f"dataCenterIds={updated.get('dataCenterIds')}"
    )
    if volume_id:
        print(f"RUNPOD_NETWORK_VOLUME_ID={volume_id}")
        print(f"RUNPOD_DATA_CENTER_IDS={data_center}")
    else:
        print("RUNPOD_NETWORK_VOLUME_ID=")
        print("RUNPOD_DATA_CENTER_IDS=")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
