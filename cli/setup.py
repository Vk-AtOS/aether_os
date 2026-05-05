from setuptools import setup, find_packages

setup(
    name="aetheros-cli",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "click",
        "requests",
    ],
    entry_points={
        "console_scripts": [
            "aetheros=cli.aetheros:cli",
        ],
    },
)
