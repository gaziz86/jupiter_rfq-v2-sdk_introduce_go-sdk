"""Setup configuration for Jupiter RFQv2 SDK.

The Python protobuf stubs (``src/protos/market_maker_pb2*.py``) are not
checked into git — see ``.gitignore``. They are produced from
``../protos/market_maker.proto`` and need to be generated before importing
the SDK.

Generation strategy:

* Editable installs (``pip install -e .``) and any build that can see the
  sibling ``../protos/`` directory: the :class:`BuildPy` / :class:`Develop`
  commands run :func:`generate_protos.generate` automatically.
* Isolated PEP 517 builds (``pip install .`` from a fresh checkout): the
  parent ``../protos/`` directory is **not** copied into the build sandbox,
  so we skip generation and rely on the user running
  ``python scripts/generate_protos.py`` first.

Run the generator manually any time::

    python scripts/generate_protos.py
"""

import sys
from pathlib import Path

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py
from setuptools.command.develop import develop

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()


def _try_generate_protos() -> None:
    """Regenerate stubs in place when the proto file is reachable.

    For a clone of the repo (where ``../protos/market_maker.proto`` is a
    sibling directory) this regenerates the stubs every build. For an
    isolated PEP 517 build the parent directory is **not** copied into the
    build sandbox — in that case we leave whatever stubs are already present
    in ``src/protos/`` alone and let the import-time check in
    ``protos/__init__.py`` give the user a clear error.
    """
    here = Path(__file__).resolve().parent
    proto_file = here.parent / "protos" / "market_maker.proto"
    stubs_present = (here / "src" / "protos" / "market_maker_pb2.py").exists()

    if not proto_file.is_file():
        if not stubs_present:
            sys.stderr.write(
                "\n[setup.py] WARNING: protobuf stubs are not generated and the "
                "source proto file is not reachable from this build sandbox.\n"
                "           Run from a fresh clone:\n"
                "             python scripts/generate_protos.py\n"
                "             pip install .\n\n"
            )
        return

    sys.path.insert(0, str(here / "scripts"))
    try:
        from generate_protos import generate  # type: ignore[import-not-found]

        generate(here)
    finally:
        if str(here / "scripts") in sys.path:
            sys.path.remove(str(here / "scripts"))


class BuildPy(build_py):
    """``build_py`` step that regenerates the proto stubs first."""

    def run(self):
        _try_generate_protos()
        super().run()


class Develop(develop):
    """``develop`` (editable install) — also generate protos in-place."""

    def run(self):
        _try_generate_protos()
        super().run()


setup(
    name="jupiter-rfq-sdk",
    version="0.1.0",
    author="Jupiter",
    author_email="",
    description="Python SDK for Jupiter RFQv2 integration via gRPC streaming",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jup-ag/rfq-v2-sdk",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "grpcio>=1.60.0",
        "grpcio-tools>=1.60.0",
        "grpcio-reflection>=1.60.0",
        "protobuf>=4.25.0",
        "solders>=0.18.0",
        "base58>=2.1.1",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
            "pylint>=2.17.0",
            "requests>=2.28.0",
        ],
    },
    cmdclass={"build_py": BuildPy, "develop": Develop},
)
