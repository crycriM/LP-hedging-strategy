from setuptools import setup, find_packages

setup(
    name="lp_hedging_strategy",
    version="0.1.0",
    description="Automated hedging and rebalancing pipeline for DEX liquidity pool positions",
    license="MIT",
    packages=find_packages(where="python"),
    package_dir={"": "python"},
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=[
        "ccxt>=4.0.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "python-dotenv>=1.0.0",
        "pyyaml>=6.0",
        "numba>=0.58.0",
        "aiohttp>=3.9.0",
        "websockets>=12.0",
        "requests>=2.31.0",
    ],
    entry_points={
        # Optionally define command line scripts if needed:
        # "console_scripts": [
        #     "lp-workflow=hedging_strategy.some_module:main",
        # ],
    },
)
