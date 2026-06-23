from setuptools import find_packages, setup

setup(
    name="model-upgrade",
    version="0.1.0",
    description="Competitive maximum clique solver for Bittensor subnet 83 (CliqueAI)",
    packages=find_packages(),
    python_requires=">=3.12",
    install_requires=[
        "numpy>=2.0",
    ],
)
