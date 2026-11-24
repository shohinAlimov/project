"""Print a Railway start command for an immutable, checksummed public pilot release."""

import argparse
import hashlib
import re
import shlex
from textwrap import dedent
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit", help="full commit SHA from shohinAlimov/project")
    sha = parser.parse_args().commit
    if not re.fullmatch("[0-9a-f]{40}", sha):
        parser.error("full lower-case Git SHA required")
    url = f"https://codeload.github.com/shohinAlimov/project/zip/{sha}"
    with urlopen(url, timeout=30) as source:
        digest = hashlib.sha256(source.read()).hexdigest()
    script = dedent(f"""
        import hashlib, io, os, pathlib, subprocess, sys, tempfile, urllib.request, zipfile
        if os.geteuid() == 0:
            os.setgroups([])
            os.setgid(65532)
            os.setuid(65532)
        os.chdir(tempfile.mkdtemp(prefix='growth-release-'))
        with urllib.request.urlopen({url!r},timeout=45) as source:
            data=source.read()
        if hashlib.sha256(data).hexdigest()!={digest!r}:
            raise RuntimeError('release archive checksum mismatch')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                path=pathlib.PurePosixPath(name)
                parts=path.parts[1:]
                if not parts or '..' in parts or path.is_absolute() or name.endswith('/'):
                    continue
                if parts[0] not in ('growth','static','requirements.txt','bot.py','dashboard.py','db.py','text_parser.py','texts.py'):
                    continue
                target=pathlib.Path(*parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(name))
        deps=os.path.abspath('dependencies')
        subprocess.run([sys.executable,'-m','pip','install','--no-cache-dir','--disable-pip-version-check','--quiet','--target',deps,'-r','requirements.txt'],check=True)
        os.environ['PYTHONPATH']=deps
        os.environ['PYTHONDONTWRITEBYTECODE']='1'
        os.execv(sys.executable,[sys.executable,'dashboard.py'])
    """).strip()
    print("python -c " + shlex.quote(script))


if __name__ == "__main__":
    main()
