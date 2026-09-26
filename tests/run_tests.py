#!/usr/bin/env python3
"""无 pytest 时的简易测试运行器：python -m tests.run_tests。"""
import sys
import traceback
import inspect


def _install_pytest_shim():
    import sys, types

    class _Raises:
        def __init__(self, exc):
            self.exc = exc
        def __enter__(self):
            return self
        def __exit__(self, et, ev, tb):
            return et is not None and issubclass(et, self.exc)

    class _Approx:
        def __init__(self, v, tol=1e-6):
            self.v, self.tol = v, tol
        def __eq__(self, other):
            return abs(other - self.v) <= self.tol

    class _PytestShim:
        raises = staticmethod(lambda e: _Raises(e))
        approx = staticmethod(lambda v, **kw: _Approx(v))
        @staticmethod
        def fixture(fn=None, **kw):
            if fn is None:
                return lambda f: f
            return fn

    shim = types.ModuleType("pytest")
    shim.raises = _PytestShim.raises
    shim.approx = _PytestShim.approx
    shim.fixture = _PytestShim.fixture
    sys.modules["pytest"] = shim


def main():
    _install_pytest_shim()
    from . import test_models, test_graph, test_planner, test_sample

    class TmpPath:
        def __truediv__(self, name):
            import pathlib, tempfile
            d = pathlib.Path(tempfile.mkdtemp())
            return d / name

    modules = [test_models, test_graph, test_planner, test_sample]
    passed = failed = 0
    failures = []

    def fixtures_for(fn):
        sig = inspect.signature(fn)
        kwargs = {}
        for name in sig.parameters:
            if name == "small_zoo":
                from .conftest import small_zoo
                kwargs["small_zoo"] = small_zoo()
            elif name == "tmp_path":
                kwargs["tmp_path"] = TmpPath()
        return kwargs

    for mod in modules:
        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn(**fixtures_for(fn))
                passed += 1
                print(f"  PASS {mod.__name__.split('.')[-1]}.{name}")
            except Exception:
                failed += 1
                failures.append((name, traceback.format_exc()))
                print(f"  FAIL {mod.__name__.split('.')[-1]}.{name}")

    for name, tb in failures:
        print("\n" + "=" * 70 + f"\nFAILURE: {name}\n" + tb)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
