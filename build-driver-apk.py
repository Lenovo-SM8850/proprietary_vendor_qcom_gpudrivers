# SPDX-License-Identifier: Apache-2.0
import argparse
import re
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Build an updatable Adreno driver APK')
    parser.add_argument('--aapt2', required=True)
    parser.add_argument('--zipalign', required=True)
    parser.add_argument('--android-jar', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('inputs', nargs='+')
    args = parser.parse_args()
    libs = sorted((Path(p) for p in args.inputs if p.endswith('.so')), key=lambda p: p.name)
    assert len({p.name for p in libs}) == len(libs), 'Duplicate library names'
    assert all(p.stat().st_size < 100_000_000 for p in libs), 'Library exceeds 100 MB'
    gl = next(p for p in libs if p.name == 'libGLESv2_adreno.so')
    match = re.search(rb'V@(\d{4}\.[0-9.]+[a-z]?) \(GIT@\w+, I\w+, (\d+)\)', gl.read_bytes())
    if match is None:
        raise ValueError('Missing driver version')
    version = match[1].decode().lstrip('0')
    epoch = match[2].decode()
    nums = [int(x) for x in re.findall(r'\d+', version)] + [0, 0]
    code = nums[0] * 10000 + nums[1] * 100 + nums[2]
    package = 'io.github.miner7222.gpudrivers.a840.v' + args.version.replace('.', '_')
    sphal = next(Path(p) for p in args.inputs if p.endswith('sphal_libraries.txt'))
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        manifest = work / 'AndroidManifest.xml'
        manifest.write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<!-- SPDX-License-Identifier: Apache-2.0 -->
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{package}"
    android:versionCode="{code}" android:versionName="{version}">
    <uses-sdk android:minSdkVersion="36" android:targetSdkVersion="36" />
    <application android:label="Adreno {args.version}" android:hasCode="false"
        android:extractNativeLibs="false" android:allowBackup="false" android:forceQueryable="true">
        <meta-data android:name="com.android.graphics.driver.build_time" android:value="L{epoch}" />
        <meta-data android:name="io.github.miner7222.gpudrivers" android:value="@string/driver_version" />
    </application>
</manifest>
''', encoding='utf-8')
        values = work / 'res' / 'values'
        values.mkdir(parents=True)
        (values / 'strings.xml').write_text(
            '<!-- SPDX-License-Identifier: Apache-2.0 -->\n'
            f'<resources><string name="driver_version">{version}</string></resources>\n',
            encoding='utf-8')
        resources = work / 'resources.zip'
        subprocess.run([args.aapt2, 'compile', '--dir', str(work / 'res'),
                        '-o', str(resources)], check=True)
        base = work / 'base.apk'
        subprocess.run([args.aapt2, 'link', '-o', str(base), '-I', args.android_jar,
                        '--manifest', str(manifest), str(resources)], check=True)
        with zipfile.ZipFile(base, 'a') as apk:
            for lib in libs:
                apk.write(lib, 'lib/arm64-v8a/' + lib.name, compress_type=zipfile.ZIP_STORED)
            apk.write(sphal, 'assets/sphal_libraries.txt', compress_type=zipfile.ZIP_STORED)
        subprocess.run([args.zipalign, '-f', '-P', '16', '4', str(base), args.output], check=True)
    with zipfile.ZipFile(args.output) as apk, open(args.output, 'rb') as raw:
        for entry in apk.infolist():
            if not entry.filename.endswith('.so'):
                continue
            raw.seek(entry.header_offset + 26)
            name_len, extra_len = struct.unpack('<HH', raw.read(4))
            assert entry.compress_type == zipfile.ZIP_STORED
            assert (entry.header_offset + 30 + name_len + extra_len) % 16384 == 0
    print(f'{package}: {version}, L{epoch}, {len(libs)} stored, 16K-aligned libraries')


if __name__ == '__main__':
    main()
