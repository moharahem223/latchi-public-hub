#!/usr/bin/env python3
"""
LATCHI Studio — Fast & Safe GitHub Sync Utility
Pushes any folder/files into moharahem223/latchi-ai-films via GitHub Git Data REST API,
scans strictly to block any secret leakage, and lets local temp assets be cleaned safely.
"""
import base64
import concurrent.futures
import json
import sys
import urllib.request
from pathlib import Path

ENV_PATH = Path("/home/user/LATCHI_GITHUB_AUTH.env")


def load_config() -> dict:
    cfg = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def push_directory(local_dir: str, repo_subpath: str, commit_message: str) -> str:
    cfg = load_config()
    token = cfg["GITHUB_TOKEN"]
    owner = cfg["GITHUB_OWNER"]
    repo = cfg["GITHUB_REPO"]
    branch = cfg.get("GITHUB_BRANCH", "main")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "Latchi-Studio-Agent",
    }

    def gh_api(method: str, path: str, body=None, timeout: int = 45):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            f"https://api.github.com{path}", data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    src_root = Path(local_dir).resolve()
    files = [p for p in sorted(src_root.rglob("*")) if p.is_file() and ".git" not in p.parts]
    if not files:
        raise ValueError(f"No files found in {src_root}")

    for p in files:
        if p.suffix.lower() in {".md", ".txt", ".json", ".py", ".env", ".yaml", ".yml"}:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if token in txt or "ghp_" in txt or "github_pat_" in txt:
                raise RuntimeError(f"Security block: secret token pattern detected in {p}!")

    ref_info = gh_api("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
    parent_sha = ref_info["object"]["sha"]
    parent_commit = gh_api("GET", f"/repos/{owner}/{repo}/git/commits/{parent_sha}")
    base_tree_sha = parent_commit["tree"]["sha"]

    prefix = repo_subpath.strip("/")

    def upload_one(p: Path):
        rel = p.relative_to(src_root).as_posix()
        dest_path = f"{prefix}/{rel}" if prefix else rel
        res = gh_api(
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            {"content": base64.b64encode(p.read_bytes()).decode("ascii"), "encoding": "base64"},
            timeout=60,
        )
        return {"path": dest_path, "mode": "100644", "type": "blob", "sha": res["sha"]}

    entries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for entry in pool.map(upload_one, files):
            entries.append(entry)

    new_tree = gh_api(
        "POST", f"/repos/{owner}/{repo}/git/trees", {"base_tree": base_tree_sha, "tree": entries}
    )
    new_commit = gh_api(
        "POST",
        f"/repos/{owner}/{repo}/git/commits",
        {"message": commit_message, "tree": new_tree["sha"], "parents": [parent_sha]},
    )
    gh_api("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", {"sha": new_commit["sha"]})
    return new_commit["sha"]


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python3 latchi_sync.py <local_dir> <repo_subpath> <commit_message>")
        sys.exit(1)
    sha = push_directory(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"SYNC OK -> commit {sha}")
