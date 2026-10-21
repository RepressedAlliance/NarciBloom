"""Exact runtime-license scope reviews for the Ubuntu 22.04 package build.

These do not waive source/relinking obligations or approve arbitrary package
files. Package/source versions, primary notice bytes and shipped filenames must
all match. Retain each complete package notice, including its other scopes.
"""

RUNTIME_LICENSE_REVIEWS = (
    {
        'package_manager': 'dpkg',
        'package': 'libffi8:amd64',
        'version': '3.4.2-4',
        'source_package': 'libffi',
        'source_version': '3.4.2-4',
        'shipped_basenames': ('libffi.so.8',),
        'runtime_license': 'MIT',
        'primary_notices': (
            {'path': 'doc/libffi8/copyright',
             'sha256': '7258c8acc378030d8dbe1fcdf394e915769fa31dcbaf3d2991d9a79891f3bcdc'},
        ),
        'primary_sources': (
            'https://changelogs.ubuntu.com/changelogs/pool/main/libf/libffi/libffi_3.4.2-4/copyright',
        ),
        'excluded_scopes': (
            {'scope': 'Documentation and doc/*', 'license': 'GPL-2.0-or-later'},
            {'scope': 'Debian packaging', 'license': 'GPL'},
        ),
        'reason': 'The exact package notice grants the libffi runtime the MIT permission; '
                  'its separate GPL sections identify documentation and Debian packaging, '
                  'neither of which is in this shipped runtime-file set.',
    },
    {
        'package_manager': 'dpkg',
        'package': 'libssl3:amd64',
        'version': '3.0.2-0ubuntu1.30',
        'source_package': 'openssl',
        'source_version': '3.0.2-0ubuntu1.30',
        'shipped_basenames': ('libcrypto.so.3',),
        'runtime_license': 'Apache-2.0',
        'primary_notices': (
            {'path': 'doc/libssl3/copyright',
             'sha256': '6a7da622fe0637a334d2a8fc470852d2ffb77d9a2b2f930f854e32a41ad6ef35'},
        ),
        'primary_sources': (
            'https://changelogs.ubuntu.com/changelogs/pool/main/o/openssl/openssl_3.0.2-0ubuntu1.30/copyright',
        ),
        'excluded_scopes': (
            {'scope': 'external/perl/Text-Template-1.56/*', 'license': 'Artistic or GPL-1.0-or-later'},
        ),
        'reason': 'The exact DEP-5 notice assigns Apache-2.0 to Files:* and debian/*. '
                  'The Artistic/GPL alternative is restricted to the external Perl '
                  'Text-Template build tool, which is absent from this runtime-file set.',
    },
)
