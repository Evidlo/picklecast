from setuptools import find_packages, setup

with open("README.md") as f:
    README = f.read()

version = {}
# manually read version from file
with open("picklecast/version.py") as file:
    exec(file.read(), version)

setup(
    # some basic project information
    name="picklecast",
    version=version["__version__"],
    license="GPL3",
    description="Example python project",
    long_description=README,
    author="Evan Widloski",
    author_email="evan_ex@widloski.com",
    url="https://github.com/evidlo/picklecast",
    # your project's pip dependencies
    install_requires=[
        "websockets"
    ],
    include_package_data=True,
    # automatically look for subfolders with __init__.py
    packages=find_packages(),
    data_files=[
        ('', [
            'picklecast/localhost.pem',
            'picklecast/index.html',
            'picklecast/display.html',
            'picklecast/webrtc.js',
            'picklecast/background.jpg',
        ]),
    ],
    # if you want your code to be able to run directly from command line
    entry_points={
        'console_scripts': [
            'picklecast = picklecast.picklecast:main',
        ]
    },
)
