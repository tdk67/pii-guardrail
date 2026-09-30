from setuptools import setup, find_packages

setup(
    name="latch",
    version="0.1.0",
    description="Ultra-fast, 100% local git pre-commit guardrail powered by Julia-1",
    author="Latch Contributors",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.12",
    install_requires=[
        "huggingface_hub>=0.20.0",
        "torch>=2.0.0",
    ],
    entry_points={
        "console_scripts": [
            "latch=latch.cli:main",
        ],
    },
)
