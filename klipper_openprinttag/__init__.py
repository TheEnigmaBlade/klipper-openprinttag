from pathlib import Path

try:
	import tomllib
except ModuleNotFoundError:
	# To support Python 3.10
	import tomli as tomllib

_meta_file = Path(__file__).parent.parent / "pyproject.toml"
with _meta_file.open("rb") as file:
	_project = tomllib.load(file)["project"]

APP_NAME = _project["name"]
__version__ = _project["version"]
