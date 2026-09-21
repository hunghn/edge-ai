# Python 3.6-compatible (JetPack 4.6). Runtime deps are pinned in requirements/*.txt;
# numpy, cv2 and tensorrt come from JetPack apt packages on the Nano, so they are not
# listed in install_requires (pip would try to build them from source on arm64).
from setuptools import find_packages, setup

setup(
    name="edgeface",
    version="0.1.0",
    description="Edge face recognition with RGB anti-spoofing for Jetson Nano",
    package_dir={"": "src"},
    packages=find_packages("src"),
    package_data={"edgeface": ["storage/schema/*.sql"]},
    python_requires=">=3.6",
    install_requires=[],
)
