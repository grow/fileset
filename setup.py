import setuptools


setuptools.setup(
    name='fileset',
    version='1.0.0',
    license='MIT',
    author='Grow SDK Authors',
    author_email='hello@grow.io',
    package_data={
        'fileset': ['include.yaml'],
    },
    packages=[
        'fileset',
    ],
)
