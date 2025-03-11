from setuptools import find_packages, setup
# try to import py2exe for Windows packaging
try:
    import py2exe
except ImportError:
    pass

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
    license="MIT",
    description="Share your screen to a projector via web-browser",
    long_description=README,
    author="Evan Widloski",
    author_email="evan_github@widloski.com",
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
            'picklecast/adapter-latest.js',
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
