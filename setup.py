import setuptools


setuptools.setup(
    name='fileset',
    version='1.0.0',
    license='MIT',
    author='Grow SDK Authors',
    author_email='hello@grow.io',
    package_data={
        'fileset': [
            'cron.yaml',
            'include.yaml',
            'index.yaml',
        ],
    },
    packages=setuptools.find_packages(),
    install_requires=[
        'GoogleAppEngineCloudStorageClient',
        'babel',
        'pytz',
    ],
)
