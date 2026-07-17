"""测试 artifact 模块。"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.artifact import Artifact, ArtifactManager


def test_artifact_create():
    """测试创建制品。"""
    manager = ArtifactManager()
    artifact = manager.create("测试页面", "html", "<h1>Hello</h1>")

    assert artifact.name == "测试页面"
    assert artifact.type == "html"
    assert artifact.content == "<h1>Hello</h1>"
    assert artifact.id
    assert artifact.size == len("<h1>Hello</h1>")

    print(f"✓ create: {artifact.id} ({artifact.size}B)")


def test_artifact_get():
    """测试获取制品。"""
    manager = ArtifactManager()
    created = manager.create("测试", "text", "内容")
    fetched = manager.get(created.id)

    assert fetched is not None
    assert fetched.name == "测试"
    assert fetched.content == "内容"

    # 不存在的 ID
    assert manager.get("nonexistent") is None

    print("✓ get: 通过")


def test_artifact_list():
    """测试列出制品。"""
    manager = ArtifactManager()
    manager.create("A", "html", "<a>")
    manager.create("B", "js", "console.log(1)")
    manager.create("C", "css", "body {}")

    artifacts = manager.list()
    assert len(artifacts) == 3

    types = [a["type"] for a in artifacts]
    assert "html" in types
    assert "js" in types
    assert "css" in types

    print(f"✓ list: {len(artifacts)} 个制品")


def test_artifact_delete():
    """测试删除制品。"""
    manager = ArtifactManager()
    artifact = manager.create("待删除", "text", "delete me")

    assert manager.delete(artifact.id) is True
    assert manager.get(artifact.id) is None
    assert manager.delete("nonexistent") is False

    print("✓ delete: 通过")


def test_artifact_clear():
    """测试清空制品。"""
    manager = ArtifactManager()
    manager.create("A", "text", "a")
    manager.create("B", "text", "b")

    manager.clear()
    assert len(manager.list()) == 0

    print("✓ clear: 通过")


def test_artifact_save_to_disk():
    """测试保存制品到磁盘。"""
    manager = ArtifactManager()
    artifact = manager.create("磁盘测试", "html", "<html><body>测试</body></html>")

    filepath = artifact.save()
    assert os.path.exists(filepath)

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == "<html><body>测试</body></html>"

    # 清理
    os.remove(filepath)
    print(f"✓ save: {filepath}")


def test_artifact_types():
    """测试不同制品类型。"""
    manager = ArtifactManager()

    types = ["html", "js", "css", "json", "text", "markdown", "svg"]
    for t in types:
        artifact = manager.create(f"test.{t}", t, f"content for {t}")
        assert artifact.type == t
        filepath = artifact.save()
        assert os.path.exists(filepath)
        os.remove(filepath)

    print(f"✓ types: {len(types)} 种类型全部通过")


if __name__ == "__main__":
    test_artifact_create()
    test_artifact_get()
    test_artifact_list()
    test_artifact_delete()
    test_artifact_clear()
    test_artifact_save_to_disk()
    test_artifact_types()
    print("\n✅ 所有 artifact 测试通过!")
