"""Render a reviewable JSON plan. Never calls Docker, Azure, DNS or a network.

This renderer is preparation, not deployment approval. Its stdout can be saved
inside this isolated deploy directory for owner review. It creates no credentials.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def render(template: dict, values: dict[str, str]) -> dict:
    name = values["__APP_NAME__"]
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,30}[a-z0-9]", name):
        raise ValueError("Use a lowercase app name of 4-32 characters")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", values["__RELEASE_SUFFIX__"]):
        raise ValueError("Invalid release suffix")
    origin = urlsplit(values["__APPROVED_HTTPS_ORIGIN__"])
    if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}:
        raise ValueError("Origin must be one HTTPS origin without credentials/path/query")
    values = {**values, "__APPROVED_HTTPS_HOST__": origin.netloc}
    if not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", values["__APPROVED_IMAGE_WITH_SHA256_DIGEST__"]):
        raise ValueError("Container image must be pinned by SHA-256 digest")
    if not re.fullmatch(r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[A-Za-z0-9_.()-]+/providers/Microsoft\.App/managedEnvironments/[A-Za-z0-9-]+", values["__APPROVED_ENVIRONMENT_RESOURCE_ID__"]):
        raise ValueError("An explicitly approved environment resource ID is required")
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,40}", values["__APPROVED_ENVIRONMENT_STORAGE_LINK__"]):
        raise ValueError("Invalid existing environment storage link")

    def replace(node):
        if isinstance(node, dict):
            return {key: replace(value) for key, value in node.items()}
        if isinstance(node, list):
            return [replace(value) for value in node]
        if isinstance(node, str):
            return values.get(node, node)
        return node

    result = replace(template)
    if re.search(r"__[A-Z0-9_]+__", json.dumps(result)):
        raise ValueError("Template contains unresolved placeholders")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--environment-resource-id", required=True)
    parser.add_argument("--storage-link", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    values = {
        "__APP_NAME__": args.app_name,
        "__APPROVED_ENVIRONMENT_RESOURCE_ID__": args.environment_resource_id,
        "__APPROVED_ENVIRONMENT_STORAGE_LINK__": args.storage_link,
        "__APPROVED_IMAGE_WITH_SHA256_DIGEST__": args.image,
        "__APPROVED_HTTPS_ORIGIN__": args.origin.rstrip("/"),
        "__RELEASE_SUFFIX__": args.release,
    }
    template = json.loads(Path(__file__).with_name("aca.template.json").read_text(encoding="utf-8"))
    print(json.dumps(render(template, values), indent=2))


if __name__ == "__main__":
    main()
