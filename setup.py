from setuptools import find_namespace_packages, setup


setup(
    name='perdir',
    version='1',
    url='https://github.com/twiebe/perdir',
    license='BSD',
    author='Thomas Wiebe',
    author_email='code@heimblick.net',
    description='Execute commands per directory easily and concurrently',
    long_description='Execute commands per directory easily and concurrently',
    package_dir={'': 'src'},
    packages=find_namespace_packages(where='src'),
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=['progressbar2', 'termcolor'],
    entry_points={
        'console_scripts': ['perdir=perdir.main:entrypoint']
    },
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
