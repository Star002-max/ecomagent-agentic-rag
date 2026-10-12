"""Check ignored .env, current tracked/untracked files, and staged content.

Print only filenames and check names, never matching values or line contents.
"""

import os
import re
import subprocess

from dotenv import dotenv_values

from src.config import PROJECT_ROOT


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=PROJECT_ROOT)


def main() -> None:
    local = dotenv_values(PROJECT_ROOT / ".env")
    keys = {
        value for value in (
            os.environ.get("LLM_API_KEY") or local.get("LLM_API_KEY") or "",
            os.environ.get("EMBEDDING_API_KEY")
            or local.get("EMBEDDING_API_KEY") or "",
        ) if value
    }
    patterns = re.compile(rb"sk-[A-Za-z0-9_.-]{20,}")

    def contains_secret(content: bytes) -> bool:
        return bool(any(key.encode() in content for key in keys)
                    or patterns.search(content))

    failures = []
    if git("ls-files", "--", ".env").strip():
        failures.append(".env被Git跟踪")
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=PROJECT_ROOT)
    if ignored.returncode != 0:
        failures.append(".env未被忽略")
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    paths = sorted(set(name.decode() for name in names.split(b"\0") if name))
    for name in paths:
        path = PROJECT_ROOT / name
        if path.is_file() and contains_secret(path.read_bytes()):
            failures.append(f"文件包含疑似密钥：{name}")
    if contains_secret(git("diff", "--no-ext-diff", "--binary")):
        failures.append("工作区Git Diff包含疑似密钥")
    if contains_secret(git("diff", "--cached", "--no-ext-diff", "--binary")):
        failures.append("暂存Git Diff包含疑似密钥")
    # Inspect the whole index too: diff alone can omit unchanged staged secrets.
    for name in git("ls-files", "-z").split(b"\0"):
        if name and contains_secret(git("show", ":" + name.decode())):
            failures.append(f"Git index包含疑似密钥：{name.decode()}")
    if failures:
        print("\n".join(failures))
        raise SystemExit(1)
    print(f"PASS：.env未跟踪且被忽略；{len(paths)}个可提交文件、Git Diff和index未发现密钥。")


if __name__ == "__main__":
    main()
