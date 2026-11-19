"""Install verified, bounded GitHub release packages without Git or Node.js."""

import base64
import contextlib
import hashlib
import gzip
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

HOME = Path.home()
REPOSITORIES = {'extension': 'sing-vpn-extension', 'sing': 'sing'}
ASSETS = {'extension': 'sing-vpn-macos.tar.gz', 'sing': 'sing-macos.tar.gz'}
REQUIRED = {
    'extension': {'build/manifest.json', 'build/background.js', 'build/popup.js',
                  'build/popup.html', 'build/popup.css', 'build/release-info.json', 'src/host/sing_host.py',
                  'src/host/release_tools.py', 'install.sh'},
    'sing': {'bin/sing', 'share/select.py', 'proxychains/sing.conf', 'VERSION'},
}
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
EXTENSION_ID = 'plaaamdfdpajlgakeipabpddfkcaihpn'
MAX_PREFERENCES_BYTES = 16 * 1024 * 1024
KNOWN_BROWSER_ROOTS = (
    'Google/Chrome', 'Google/Chrome Beta', 'Google/Chrome Dev', 'Google/Chrome Canary',
    'Chromium', 'Aside', 'Dia', 'Dia/User Data', 'Arc', 'Arc/User Data',
    'BraveSoftware/Brave-Browser', 'BraveSoftware/Brave-Browser-Beta',
    'BraveSoftware/Brave-Browser-Nightly', 'Microsoft Edge', 'Microsoft Edge Beta',
    'Microsoft Edge Dev', 'Microsoft Edge Canary', 'Vivaldi', 'Vivaldi Snapshot',
    'com.operasoftware.Opera', 'com.operasoftware.OperaNext',
    'com.operasoftware.OperaDeveloper', 'com.operasoftware.OperaGX',
    'Yandex/YandexBrowser', 'YandexBrowser', 'Thorium',
)


def read_browser_state(path):
    """Read bounded local browser metadata without exposing its contents in errors or logs."""
    try:
        with path.open('rb') as source:
            contents = source.read(MAX_PREFERENCES_BYTES + 1)
        if len(contents) <= MAX_PREFERENCES_BYTES:
            data = json.loads(contents)
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def browser_user_data_dirs():
    """Find standard Chromium roots and unknown brands with real browser profile metadata."""
    support = HOME / 'Library/Application Support'
    roots = {support / name for name in KNOWN_BROWSER_ROOTS if (support / name).is_dir()}
    # Inspect only three directory levels, never browser caches or arbitrary recursive trees.
    for pattern in ('*/Local State', '*/*/Local State', '*/*/*/Local State'):
        for state_file in support.glob(pattern):
            data = read_browser_state(state_file)
            profile = data.get('profile')
            if isinstance(profile, dict) and isinstance(profile.get('info_cache'), dict):
                roots.add(state_file.parent)
                continue
    # Preferences independently identify single-profile forks even without Local State.
    for filename in ('Preferences', 'Secure Preferences'):
        for depth in range(1, 4):
            for preferences_file in support.glob('*/' * depth + filename):
                preferences = read_browser_state(preferences_file)
                extensions = preferences.get('extensions', {})
                settings = extensions.get('settings') if isinstance(extensions, dict) else None
                if isinstance(settings, dict) and EXTENSION_ID in settings:
                    roots.add(preferences_file.parent)
    return sorted(roots, key=str)


def extension_folder_id(directory):
    """Validate an unpacked manifest and derive its stable Chrome extension ID."""
    try:
        with (directory / 'manifest.json').open('rb') as source:
            contents = source.read(MAX_JSON_BYTES + 1)
        if len(contents) > MAX_JSON_BYTES:
            return None
        manifest = json.loads(contents)
        if not isinstance(manifest, dict) or manifest.get('manifest_version') != 3:
            return None
        key = manifest.get('key')
        if not isinstance(key, str):
            return None
        digest = hashlib.sha256(base64.b64decode(key, validate=True)).hexdigest()[:32]
        return ''.join(chr(97 + int(digit, 16)) for digit in digest)
    except (OSError, ValueError):
        return None


def installed_extension_paths():
    """Read only Sing's unpacked path from local browser registrations; never log preferences."""
    paths = set()
    for root in browser_user_data_dirs():
        for filename in ('Secure Preferences', 'Preferences'):
            for preferences in [root / filename, *root.glob('*/' + filename)]:
                try:
                    stored = read_browser_state(preferences).get('extensions', {}).get('settings', {}).get(EXTENSION_ID, {})
                    registered = stored.get('path')
                    if not isinstance(registered, str) or not Path(registered).is_absolute():
                        continue
                    directory = Path(registered).resolve(strict=True)
                    if directory.is_dir() and extension_folder_id(directory) == EXTENSION_ID:
                        paths.add(directory)
                except (OSError, ValueError, AttributeError, RuntimeError):
                    continue
    return sorted(paths, key=str)


def update_installed_build(source, target):
    """Atomically update only a registered copy, keeping its prior folder as a backup."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if target not in installed_extension_paths():
        raise ValueError('extension folder is not registered in a browser')
    if extension_folder_id(source) != EXTENSION_ID:
        raise ValueError('release extension identity mismatch')
    unchanged = source == target
    if not unchanged:
        unchanged = True
        for original in source.rglob('*'):
            if not original.is_file():
                continue
            current = target / original.relative_to(source)
            if (current.is_symlink() or not current.is_file() or current.stat().st_size != original.stat().st_size
                    or hashlib.sha256(current.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest()):
                unchanged = False
                break
    if unchanged:
        return {'updated': False, 'path': str(target)}
    with tempfile.TemporaryDirectory(prefix='.sing-vpn-update-', dir=target.parent) as temporary:
        staging = Path(temporary) / 'build'
        shutil.copytree(source, staging)
        backup = activate(staging, target)
    return {'updated': True, 'path': str(target), 'backup': backup}


def version_tuple(value):
    """Accept only stable numeric three-part versions."""
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise ValueError('invalid release version')
    return tuple(int(part) for part in value.split('.'))


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Keep release downloads on GitHub HTTPS infrastructure."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        """Reject cross-service and plaintext redirects."""
        from urllib.parse import urlsplit
        parsed = urlsplit(new_url)
        if parsed.scheme != 'https' or parsed.hostname not in {
                'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}:
            raise ValueError('untrusted release redirect')
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def download(url, maximum=MAX_ARCHIVE_BYTES):
    """Fetch bounded public data without inherited proxy credentials."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'Sing-VPN-Updater', 'Accept': 'application/vnd.github+json'})
    try:
        with opener.open(request, timeout=30) as response:
            contents = response.read(maximum + 1)
    except (OSError, urllib.error.URLError):
        raise RuntimeError('release download failed; check GitHub access') from None
    if len(contents) > maximum:
        raise ValueError('release download is too large')
    return contents


def latest(component):
    """Resolve GitHub's public latest redirect without anonymous API rate limits."""
    repository = REPOSITORIES[component]
    prefix = f'https://github.com/osmawx/{repository}/releases/'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeRedirect())
    request = urllib.request.Request(prefix + 'latest', method='HEAD',
                                     headers={'User-Agent': 'Sing-VPN-Updater'})
    try:
        with opener.open(request, timeout=30) as response:
            resolved = response.geturl()
    except (OSError, urllib.error.URLError):
        raise RuntimeError('release check failed; check GitHub access') from None
    match = re.fullmatch(re.escape(prefix) + r'tag/v(\d{1,5}\.\d{1,5}\.\d{1,5})', resolved)
    if not match:
        raise ValueError('untrusted or unstable latest release URL')
    version = match.group(1)
    asset_url = prefix + 'download/v' + version + '/' + ASSETS[component]
    return {'version': version, 'url': asset_url, 'checksumUrl': asset_url + '.sha256'}


def destination(component):
    """Return a fixed managed package directory, independent of a checkout."""
    return HOME / '.local/share/sing-vpn' / ('runtime' if component == 'extension' else 'sing')


def installed_version(component):
    """Read managed version metadata; report legacy installations as unknown."""
    try:
        data = json.loads((destination(component) / 'release.json').read_text())
        version_tuple(data['version'])
        return data['version']
    except (OSError, ValueError, KeyError):
        return None


def verify_directory(directory):
    """Refuse to overwrite managed files changed since installation."""
    try:
        manifest = json.loads((directory / 'release.json').read_text())
        for name, digest in manifest['files'].items():
            path = directory / name
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('managed installation has been modified')
    except (OSError, KeyError, json.JSONDecodeError):
        raise ValueError('managed installation has been modified or is not a release') from None


def unpack(contents, staging, component, version):
    """Extract only regular package files after validating every archive member."""
    with gzip.GzipFile(fileobj=io.BytesIO(contents)) as compressed:
        uncompressed = compressed.read(MAX_ARCHIVE_BYTES + 1)
    if len(uncompressed) > MAX_ARCHIVE_BYTES:
        raise ValueError('release archive is too large')
    with tarfile.open(fileobj=io.BytesIO(uncompressed), mode='r:') as archive:
        members = archive.getmembers()
        if len(members) > 100 or sum(member.size for member in members) > MAX_ARCHIVE_BYTES:
            raise ValueError('release archive is too large')
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            allowed = (member.name in REQUIRED[component] or member.name == 'release.json'
                       or (component == 'extension' and str(path).startswith('build/')))
            if (not member.isfile() or path.is_absolute() or '..' in path.parts or '\\' in member.name
                    or str(path) != member.name or member.name in names or not allowed):
                raise ValueError('unsafe release archive member')
            names.add(member.name)
        if not REQUIRED[component].issubset(names) or 'release.json' not in names:
            raise ValueError('incomplete release archive')
        for member in members:
            target = staging / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source:
                target.write_bytes(source.read())
            target.chmod(0o755 if member.name in ('bin/sing', 'install.sh') else 0o644)
    manifest = json.loads((staging / 'release.json').read_text())
    if manifest.get('version') != version or manifest.get('component') != component:
        raise ValueError('release version mismatch')
    if set(manifest.get('files', {})) != names - {'release.json'}:
        raise ValueError('incomplete release checksum manifest')
    verify_directory(staging)
    if component == 'extension' and json.loads((staging / 'build/manifest.json').read_text()).get('version') != version:
        raise ValueError('extension version mismatch')
    if component == 'extension' and json.loads((staging / 'build/release-info.json').read_text()).get('managed') is not True:
        raise ValueError('extension is not a managed release build')
    if component == 'sing' and (staging / 'VERSION').read_text().strip() != version:
        raise ValueError('sing version mismatch')


def activate(staging, target):
    """Replace one managed directory, restoring its previous release on failure."""
    backup = target.with_name(target.name + '.backup-' + uuid.uuid4().hex)
    existed = target.exists()
    if target.is_symlink():
        raise ValueError('managed installation must not be a symlink')
    if existed:
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except OSError:
        if existed:
            os.replace(backup, target)
        raise
    return str(backup) if existed else None


def deploy(component):
    """Verify and activate an official release; preserve settings and old code."""
    target = destination(component)
    if target.exists():
        verify_directory(target)
    release = latest(component)
    installed = installed_version(component)
    if installed and version_tuple(installed) >= version_tuple(release['version']):
        return {'updated': False, 'version': installed, 'path': str(target)}
    contents = download(release['url'])
    checksum = download(release['checksumUrl'], 1024).decode('ascii').split()
    if not checksum or not re.fullmatch(r'[0-9a-f]{64}', checksum[0]) or hashlib.sha256(contents).hexdigest() != checksum[0]:
        raise ValueError('release checksum mismatch')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.release-', dir=target.parent) as temporary:
        staging = Path(temporary) / 'package'
        staging.mkdir()
        try:
            unpack(contents, staging, component, release['version'])
        except (tarfile.TarError, EOFError):
            raise ValueError('invalid release archive') from None
        backup = activate(staging, target)
    return {'updated': True, 'version': release['version'], 'path': str(target), 'backup': backup}


def rollback_deployment(result):
    """Restore only a package activated by this update transaction."""
    if result['updated']:
        root = Path(result['path'])
        shutil.rmtree(root)
        if result.get('backup'):
            os.replace(result['backup'], root)


def install_sing():
    """Install CLI code and replace only its fixed links, keeping unique backups."""
    result = deploy('sing')
    root = Path(result['path'])
    targets = {
        HOME / '.local/bin/sing': root / 'bin/sing',
        HOME / '.local/share/sing/select.py': root / 'share/select.py',
        HOME / '.local/share/sing/VERSION': root / 'VERSION',
        HOME / '.proxychains/sing.conf': root / 'proxychains/sing.conf',
    }
    changes = []
    migrations = []
    try:
        configuration = HOME / '.config/sing-box'
        if configuration.is_symlink():
            raise ValueError('sing configuration directory must not be a symlink')
        configuration.mkdir(parents=True, exist_ok=True, mode=0o700)
        for suffix in ('sub', 'json', 'current', 'pid'):
            previous = configuration / ('blanc.' + suffix)
            current = configuration / ('sing.' + suffix)
            if previous.is_file() and not previous.is_symlink() and not os.path.lexists(current):
                os.replace(previous, current)
                migrations.append((previous, current))
        for target, source in targets.items():
            if target.is_dir() and not target.is_symlink():
                raise ValueError('cannot replace a directory with a sing file')
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = target.with_name(target.name + '.backup-' + uuid.uuid4().hex) if os.path.lexists(target) else None
            if backup:
                os.replace(target, backup)
            changes.append((target, backup))
            target.symlink_to(source)
    except (OSError, ValueError):
        for previous, current in reversed(migrations):
            os.replace(current, previous)
        for target, backup in reversed(changes):
            with contextlib.suppress(FileNotFoundError):
                target.unlink()
            if backup:
                os.replace(backup, target)
        rollback_deployment(result)
        raise
    return result


def install_local_extension(source):
    """Activate an already downloaded release package without copying user files."""
    source = Path(source)
    manifest = json.loads((source / 'release.json').read_text())
    version_tuple(manifest.get('version'))
    if manifest.get('component') != 'extension':
        raise ValueError('not an extension release')
    verify_directory(source)
    target = destination('extension')
    if source.resolve() == target.resolve():
        return str(target)
    if target.exists():
        verify_directory(target)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.install-', dir=target.parent) as temporary:
        staging = Path(temporary) / 'package'
        staging.mkdir()
        for name in [*manifest['files'], 'release.json']:
            relative = PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or '\\' in name:
                raise ValueError('unsafe release file')
            output = staging / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, output)
            output.chmod(0o755 if name == 'install.sh' else 0o644)
        verify_directory(staging)
        activate(staging, target)
    return str(target)


def register_host():
    """Point the existing native messaging registration at managed release code."""
    import shlex
    import sys
    wrapper = HOME / '.local/share/sing-vpn/host.sh'
    contents = '#!/bin/bash\nexec ' + shlex.quote(sys.executable) + ' -I ' + shlex.quote(
        str(destination('extension') / 'src/host/sing_host.py')) + '\n'
    if wrapper.is_file() and not wrapper.is_symlink() and wrapper.read_text() == contents:
        return
    descriptor, temporary = tempfile.mkstemp(dir=wrapper.parent)
    backup = None
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(contents)
        os.chmod(temporary, 0o700)
        if wrapper.is_dir():
            raise ValueError('native host wrapper must not be a directory')
        if os.path.lexists(wrapper):
            backup = wrapper.with_name(wrapper.name + '.backup-' + uuid.uuid4().hex)
            os.replace(wrapper, backup)
        try:
            os.replace(temporary, wrapper)
        except OSError:
            if backup:
                os.replace(backup, wrapper)
            raise
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['install-sing']:
        print(install_sing()['path'])
    elif len(sys.argv) == 3 and sys.argv[1] == 'install-extension-from':
        print(install_local_extension(sys.argv[2]))
    elif sys.argv[1:] == ['browser-host-dirs']:
        for directory in browser_user_data_dirs():
            sys.stdout.buffer.write(os.fsencode(str(directory / 'NativeMessagingHosts')) + b'\0')
    else:
        raise SystemExit('unsupported release action')
