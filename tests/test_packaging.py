import tomllib
from pathlib import Path


def test_build_backend_uses_the_vca_module():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    module_name = project["tool"]["uv"]["build-backend"]["module-name"]
    assert module_name == "vca"
    assert (Path("src") / module_name / "__init__.py").is_file()
