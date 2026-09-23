"""Language specs. get_spec("it", repo) returns a loaded Italian spec."""
import importlib


def spec_class(code):
    try:
        mod = importlib.import_module(f"{__name__}.{code}")
    except ModuleNotFoundError as e:
        raise SystemExit(f"packbuilder: no language module langs/{code}.py ({e})")
    return mod.SPEC


def get_spec(code, repo=None, load=True):
    spec = spec_class(code)(repo)
    return spec.load() if (load and repo) else spec
