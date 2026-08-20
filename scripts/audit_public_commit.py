from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_PUBLIC_FILE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int | None = None


HIGH_CONFIDENCE_RULES = (
    (
        "疑似 OpenAI/中转格式密钥",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "疑似 Anthropic 格式密钥",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "疑似 GitHub Token",
        re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    (
        "疑似 AWS Access Key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    (
        "疑似私有 Windows 绝对路径",
        re.compile(
            r"(?i)\b[A-Z]:[\\/](?:Users[\\/][^\\/\s]+|求职)(?:[\\/]|\b)"
        ),
    ),
)

STATIC_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password|authorization|base[_-]?url)"
    r"\b\s*[:=]\s*([\"'])([^\"']{5,})\1"
)
SAFE_EXAMPLE_MARKERS = (
    "example",
    "placeholder",
    "dummy",
    "unit-secret",
    "test-secret",
    "your-",
    "<",
    "${",
    "********",
    "provider/",
)
DENIED_BASENAMES = {
    ".env",
    "secrets.toml",
    "credentials.json",
    "default-profile.json",
}
DENIED_SUFFIXES = {
    ".pem",
    ".p12",
    ".pfx",
    ".key",
    ".dpapi",
    ".har",
    ".trace",
    ".sqlite",
    ".sqlite3",
    ".db",
}
DENIED_PARTS = {".venv", ".bootstrap", ".codex", ".claude"}
ALLOWED_ARTIFACT = (
    "artifacts/scientific_v2/executions/"
    "scientific-v2-20260804-a-recovery-4/machine_final_report.json"
)
SCIENTIFIC_V3_ROOT = "datasets/scientific_v3"
SCIENTIFIC_V3_CASE_FILES = (
    "rule_development.jsonl",
    "technical_probes.jsonl",
    "judge_validation_cases.jsonl",
    "target_comparison.jsonl",
    "regression.jsonl",
)


def _run_git(*args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("Git 索引读取失败；请确认当前目录已经暂存公开候选。")
    return completed.stdout


def _staged_paths() -> tuple[str, ...]:
    raw = _run_git(
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
    )
    return tuple(part.decode("utf-8") for part in raw.split(b"\0") if part)


def _index_blob(path: str) -> bytes:
    return _run_git("show", f":{path}")


def _safe_example(value: str, path: str) -> bool:
    normalized = value.strip().casefold()
    if not normalized or any(marker in normalized for marker in SAFE_EXAMPLE_MARKERS):
        return True
    return (
        path.startswith("tests/")
        and len(normalized) < 20
        and any(
            marker in normalized
            for marker in ("test", "unit", "dummy", "fake", "example", "secret")
        )
    )


def _sha256_blob(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_blob(serialized.encode("utf-8"))


def _audit_scientific_v3_index_seal() -> list[Finding]:
    manifest_path = f"{SCIENTIFIC_V3_ROOT}/manifest.json"
    seal_path = f"{SCIENTIFIC_V3_ROOT}/seal.json"
    findings: list[Finding] = []
    try:
        manifest_blob = _index_blob(manifest_path)
        seal_blob = _index_blob(seal_path)
        manifest = json.loads(manifest_blob)
        seal = json.loads(seal_blob)
        file_hashes = manifest["file_sha256"]
        for name, expected_hash in file_hashes.items():
            path = f"{SCIENTIFIC_V3_ROOT}/{name}"
            if _sha256_blob(_index_blob(path)) != expected_hash:
                findings.append(Finding("V3 内容文件与 manifest 不一致", path))

        if _sha256_blob(manifest_blob) != seal["manifest_sha256"]:
            findings.append(Finding("V3 manifest 与 seal 不一致", manifest_path))
        if _sha256_value(file_hashes) != seal["aggregate_content_sha256"]:
            findings.append(Finding("V3 聚合内容哈希与 seal 不一致", seal_path))

        source_audit_path = PurePosixPath(manifest["source_audit_path"])
        if source_audit_path.is_absolute() or ".." in source_audit_path.parts:
            findings.append(Finding("V3 来源审计路径越界", manifest_path))
        else:
            source_path = source_audit_path.as_posix()
            source_hash = _sha256_blob(_index_blob(source_path))
            if source_hash != manifest["source_audit_sha256"]:
                findings.append(Finding("V3 来源审计与 manifest 不一致", source_path))
            if source_hash != seal["source_audit_sha256"]:
                findings.append(Finding("V3 来源审计与 seal 不一致", source_path))

        case_ids: list[str] = []
        for name in SCIENTIFIC_V3_CASE_FILES:
            blob = _index_blob(f"{SCIENTIFIC_V3_ROOT}/{name}")
            for line in blob.decode("utf-8").splitlines():
                if line.strip():
                    case_ids.append(str(json.loads(line)["case_id"]))
        if _sha256_value(sorted(case_ids)) != seal["case_ids_sha256"]:
            findings.append(Finding("V3 case ID 集合与 seal 不一致", seal_path))
    except (KeyError, TypeError, ValueError, UnicodeError, RuntimeError):
        findings.append(Finding("V3 Git 索引封印无法解析", manifest_path))
    return findings


def audit_staged_commit() -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for path in _staged_paths():
        pure_path = PurePosixPath(path)
        lowered_name = pure_path.name.casefold()
        lowered_suffix = pure_path.suffix.casefold()
        lowered_parts = {part.casefold() for part in pure_path.parts}

        if lowered_parts & DENIED_PARTS:
            findings.append(Finding("禁止提交的本地目录", path))
        if lowered_name in DENIED_BASENAMES or (
            lowered_name.startswith(".env.") and lowered_name != ".env.example"
        ):
            findings.append(Finding("禁止提交的凭据配置文件", path))
        if lowered_suffix in DENIED_SUFFIXES:
            findings.append(Finding("禁止提交的敏感文件类型", path))
        if path.startswith("artifacts/") and path not in {
            "artifacts/README.md",
            ALLOWED_ARTIFACT,
        }:
            findings.append(Finding("不在允许列表中的运行工件", path))

        content = _index_blob(path)
        if len(content) > MAX_PUBLIC_FILE_BYTES:
            findings.append(Finding("单文件超过 5 MiB", path))
        if b"\0" in content:
            continue

        text = content.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule_name, pattern in HIGH_CONFIDENCE_RULES:
                if pattern.search(line):
                    findings.append(Finding(rule_name, path, line_number))
            for match in STATIC_SECRET_ASSIGNMENT.finditer(line):
                if not _safe_example(match.group(2), path):
                    findings.append(
                        Finding("疑似静态凭据或私有接口赋值", path, line_number)
                    )

    findings.extend(_audit_scientific_v3_index_seal())
    return tuple(findings)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        staged_paths = _staged_paths()
        findings = audit_staged_commit()
    except (OSError, RuntimeError, UnicodeError) as error:
        print(f"公开提交审计未完成：{error}", file=sys.stderr)
        return 2

    if not staged_paths:
        print("没有已暂存文件；请先使用 git add 建立公开候选索引。")
        return 2
    if findings:
        print(f"公开提交审计失败：发现 {len(findings)} 个待处理项。")
        for finding in sorted(
            findings,
            key=lambda item: (item.path, item.line or 0, item.rule),
        ):
            location = (
                f"{finding.path}:{finding.line}"
                if finding.line is not None
                else finding.path
            )
            print(f"- [{finding.rule}] {location}")
        print("审计器不会显示命中的原文；请在本机单独检查对应位置。")
        return 1

    print(f"公开提交审计通过：{len(staged_paths)} 个暂存文件，未发现凭据或越界工件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
