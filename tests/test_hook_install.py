import os
import stat
import sys
import pytest
from latch.hook import install_pre_commit_hook, find_git_dir, HookInstallError


def test_install_hook_in_valid_git_repo(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    
    hook_path = install_pre_commit_hook(repo_root=str(tmp_path))
    assert os.path.exists(hook_path)
    assert os.path.isfile(hook_path)

    content = hook_path.read_text(encoding="utf-8")
    assert content.startswith("#!/bin/sh")
    assert "-m latch.cli check" in content
    
    # Python executable path must be present in the script with forward slashes
    clean_py = sys.executable.replace("\\", "/")
    assert clean_py in content


def test_install_hook_missing_git_dir_raises_error(tmp_path):
    empty_dir = tmp_path / "not_a_git_repo"
    empty_dir.mkdir()

    with pytest.raises(HookInstallError) as excinfo:
        install_pre_commit_hook(repo_root=str(empty_dir))
    assert "not a git repository" in str(excinfo.value).lower()


def test_install_hook_backs_up_existing_hook(tmp_path):
    git_dir = tmp_path / ".git"
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    existing_hook = hooks_dir / "pre-commit"
    existing_hook.write_text("#!/bin/sh\necho 'old hook'", encoding="utf-8")

    install_pre_commit_hook(repo_root=str(tmp_path))

    backup_path = hooks_dir / "pre-commit.latch.bak"
    assert os.path.exists(backup_path)
    assert "old hook" in backup_path.read_text(encoding="utf-8")
