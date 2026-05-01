from setuptools import Extension, setup

try:
    from Cython.Build import cythonize
except Exception as exc:
    raise SystemExit("Cython is required. Install with: pip install cython") from exc

ext_modules = cythonize(
    [
        Extension(
            name="cache_sim_fast",
            sources=["cache_sim_fast.pyx"],
        )
    ],
    compiler_directives={"language_level": 3},
)

setup(
    name="cache_sim_fast",
    version="0.1.0",
    ext_modules=ext_modules,
)
