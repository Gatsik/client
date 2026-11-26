import sys


def _is_own_module(importer: str | None, name: str, fromlist: tuple[str, ...] | None) -> bool:
    return importer is not None and importer.partition(".")[0] == __package__


sys.set_lazy_imports_filter(_is_own_module)
sys.set_lazy_imports("all")
