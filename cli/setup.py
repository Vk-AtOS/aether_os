from setuptools import setup, find_packages

setup(
    name="aetheros-cli",
    version="2.0.0",
    description="AetherOS Factory CLI — build production apps from a single prompt",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "typer[all]>=0.9",
        "rich>=13.0",
        "requests>=2.28",
        "sseclient-py>=1.7",
    ],
    entry_points={
        "console_scripts": [
            "aether=cli.aetheros:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
    ],
)
