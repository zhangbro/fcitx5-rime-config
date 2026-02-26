#!/usr/bin/env python3
"""根据 init.yaml 将各子模块拷贝到目标目录，并创建配置的软链接。可在仓库根目录执行，或用绝对路径从任意目录执行。"""
import argparse
import fnmatch
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("copy")
LINE_ENDINGS = {"LF": "\n", "CRLF": "\r\n", "CR": "\r", "NONE": None}


def find_repo_root() -> Path:
    """优先从当前目录及父目录查找含 init.yaml 的仓库根，否则用脚本所在仓库。"""
    for d in [Path.cwd()] + list(Path.cwd().resolve().parents):
        if (d / "init.yaml").exists():
            return d
    return SCRIPT_DIR.parent


def load_config(repo_root: Path):
    init_yaml = repo_root / "init.yaml"
    if not init_yaml.exists():
        print(f"未找到 {init_yaml}", file=sys.stderr)
        sys.exit(1)
    with open(init_yaml, encoding="utf-8") as f:
        return yaml.safe_load(f)


def should_ignore(name: str, ignore_patterns: list) -> bool:
    if not ignore_patterns:
        return False
    for pat in ignore_patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(name, os.path.join("*", pat)):
            return True
    return False


def copy_with_line_ending(src: Path, dst: Path, line_ending: str | None):
    """拷贝文件，可选转换换行符。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if line_ending is None:
        shutil.copy2(src, dst)
        return
    try:
        data = src.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            shutil.copy2(src, dst)
            return
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if line_ending != "\n":
            normalized = normalized.replace("\n", line_ending)
        dst.write_text(normalized, encoding="utf-8", newline="")
    except Exception:
        shutil.copy2(src, dst)


def copy_tree(
    src: Path,
    dst: Path,
    ignore_patterns: list,
    line_ending: str | None,
    symlink_entries: list,
    rel_prefix: str = "",
):
    """拷贝目录树，忽略指定模式与软链接项，可选转换换行。"""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        name = entry.name
        rel = f"{rel_prefix}/{name}" if rel_prefix else name
        if should_ignore(name, ignore_patterns) or rel in symlink_entries:
            continue
        d = dst / name
        if entry.is_dir():
            copy_tree(
                entry, d, ignore_patterns, line_ending, symlink_entries, rel
            )
        elif entry.is_file():
            if line_ending is not None:
                copy_with_line_ending(entry, d, line_ending)
            else:
                shutil.copy2(entry, d)


def apply_subdir(item: dict, target_root: Path, line_ending: str | None, repo_root: Path):
    path = repo_root / item["path"].strip().lstrip("./")
    name = item.get("name", path.name)
    ignore_patterns = item.get("ignore") or []
    symlink_entries = item.get("symlink") or []
    dest = target_root / name
    if not path.exists():
        print(f"源路径不存在，跳过: {path}", file=sys.stderr)
        return
    if path.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if line_ending is not None:
            copy_with_line_ending(path, dest, line_ending)
        else:
            shutil.copy2(path, dest)
        return
    symlink_entries = [s.strip().lstrip("/") for s in symlink_entries if s]
    copy_tree(
        path, dest, ignore_patterns, line_ending, symlink_entries, ""
    )
    for rel in symlink_entries:
        src_item = (path / rel).resolve()
        dst_item = dest / rel
        if not src_item.exists():
            print(f"软链接源不存在，跳过: {src_item}", file=sys.stderr)
            continue
        if dst_item.exists():
            dst_item.unlink()
        dst_item.parent.mkdir(parents=True, exist_ok=True)
        try:
            dst_item.symlink_to(src_item)
        except OSError as e:
            print(f"创建软链接失败 {dst_item} -> {src_item}: {e}", file=sys.stderr)


def backup_target(target_root: Path, backup_folder: Path):
    """将目标目录备份到 backup_folder/<timestamp>。"""
    if not target_root.exists() or not any(target_root.iterdir()):
        return
    backup_folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dest = backup_folder / stamp
    shutil.copytree(target_root, backup_dest, dirs_exist_ok=True)
    print(f"已备份到 {backup_dest}")


def main():
    repo_root = find_repo_root()
    parser = argparse.ArgumentParser(description="将子模块配置拷贝到目标目录")
    parser.add_argument("--target", "-t", required=True, help="目标目录（绝对或相对仓库根）")
    parser.add_argument("--no-backup", action="store_true", help="跳过备份")
    args = parser.parse_args()
    os.chdir(repo_root)
    config = load_config(repo_root)
    init_cfg = config.get("init") or {}
    line_splitter = (init_cfg.get("line-splitter") or "NONE").strip().upper()
    line_ending = LINE_ENDINGS.get(line_splitter, None)
    target_root = Path(args.target).resolve()
    if not args.no_backup:
        backup_path = (init_cfg.get("backup-folder") or "").strip().lstrip("./")
        if backup_path:
            backup_target(target_root, (repo_root / backup_path).resolve())
    target_root.mkdir(parents=True, exist_ok=True)
    for item in config.get("subdir") or []:
        apply_subdir(item, target_root, line_ending, repo_root)


if __name__ == "__main__":
    main()
