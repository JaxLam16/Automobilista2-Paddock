"""On-demand verified voice assets. No startup network calls or speech-model imports."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid
import zipfile

from .voice import VoiceCache, voice_identity


MAX_ARCHIVE = 256 << 20
MAX_UNPACKED = 512 << 20
OWNER = 'paddock-voice-packs-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def asset_url(url, *, redirect=False):
    p = urlsplit(url)
    if (p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.fragment
            or p.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com')):
        raise ValueError('Expected an HTTPS GitHub Release asset.')
    if not redirect and (p.query or not re.fullmatch(
            r'/JaxLam16/Automobilista2-Paddock/releases/download/[A-Za-z0-9_-][A-Za-z0-9._-]*/[A-Za-z0-9_-][A-Za-z0-9._-]*\.zip',p.path)):
        raise ValueError('Voice downloads must use a pinned Paddock GitHub Release ZIP.')
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        asset_url(newurl,redirect=True)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


@dataclass(frozen=True)
class Pack:
    voice_id: str
    name: str
    version: str
    archive_sha256: str
    archive_bytes: int
    url: str | None = None
    distribution_approved: bool = False

    def __post_init__(self):
        voice_identity(self.voice_id)
        if (not isinstance(self.version,str) or not re.fullmatch(r'[0-9][a-z0-9.-]{0,31}',self.version)
                or not isinstance(self.archive_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',self.archive_sha256)
                or type(self.archive_bytes) is not int or not 1<=self.archive_bytes<=MAX_ARCHIVE
                or type(self.distribution_approved) is not bool
                or not isinstance(self.name,str) or not 1<=len(self.name)<=100
                or any(ord(c)<32 for c in self.name)):
            raise ValueError('Invalid voice pack metadata.')
        if self.url:
            asset_url(self.url)

    @property
    def key(self):
        return f'{self.voice_id}--{self.version}--{self.archive_sha256[:16]}'


def member_path(name):
    p = PurePosixPath(name)
    if (not isinstance(name,str) or '\\' in name or p.is_absolute() or not p.parts
            or any(not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9._-]*',part) for part in p.parts)
            or str(p)!=name):
        raise ValueError('Unsafe voice pack path.')
    return p


IMPORT_NAME = re.compile(r'([A-Za-z0-9_-][A-Za-z0-9._-]{0,100})\.zip(?:\.(\d{3}))?')


class PackStore:
    def __init__(self, root, *, opener=None):
        self.root = Path(root).resolve()
        self.base = self.root/'private_coach'/'voice-packs'
        self.imports = self.root/'private_coach'/'voice-imports'
        self.opener = opener or build_opener(SafeRedirect())
        self.lock = threading.Lock()

    @staticmethod
    def catalogue():
        path=Path(__file__).resolve().parents[1]/'assets'/'coach_voice_packs.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('packs'),list):
            raise ValueError('Unsupported voice catalogue.')
        packs=[Pack(**item) for item in data['packs']]
        if len({p.key for p in packs})!=len(packs):raise ValueError('Duplicate voice catalogue entry.')
        return packs

    def installed(self):
        result=[]
        for path in self.base.glob('*/managed.json'):
            # Status polling must not open a staging receipt while its directory
            # is being promoted. Windows read handles can deny that rename.
            if path.parent.name.startswith('.'):
                continue
            try:
                data=json.loads(path.read_text())
                if not isinstance(data,dict) or data.get('owner')!=OWNER or self._directory(data['key'])!=path.parent:continue
                result.append({key:data[key] for key in ('key','voice_id','name','version','bytes')})
            except (OSError,ValueError,KeyError,TypeError):
                continue
        return result

    def importable(self):
        """Voice pack archives placed on this PC (private_coach/voice-imports): one .zip, or a .zip
        split into numbered parts (.zip.001, .zip.002, ...) to be joined in order."""
        found = {}
        if not self.imports.is_dir():
            return []
        for path in self.imports.iterdir():
            match = IMPORT_NAME.fullmatch(path.name)
            if not match or not path.is_file() or path.is_symlink():
                continue
            entry = found.setdefault(match[1], {'name': match[1], 'parts': [], 'bytes': 0})
            entry['parts'].append((int(match[2]) if match[2] else 0, path))
            entry['bytes'] += path.stat().st_size
        result = []
        for entry in found.values():
            numbers = sorted(n for n, _ in entry['parts'])
            if numbers != [0] and numbers != list(range(1, len(numbers) + 1)):
                continue                       # a missing or mixed part: not offered
            result.append({'name': entry['name'], 'parts': len(numbers), 'bytes': entry['bytes'],
                           'paths': [p for _, p in sorted(entry['parts'], key=lambda x: x[0])]})
        return sorted(result, key=lambda e: e['name'])

    def import_local(self, name, *, cancel=None):
        """Join the parts, check the archive and install it exactly like a downloaded pack."""
        entry = next((e for e in self.importable() if e['name'] == name), None)
        if entry is None:
            raise ValueError('That voice pack is not in the voice-imports folder (or a part is missing).')
        self.base.mkdir(parents=True, exist_ok=True)
        archive = self.base/('.import-'+uuid.uuid4().hex+'.zip')
        try:
            digest, total = hashlib.sha256(), 0
            with archive.open('xb') as target:
                for path in entry['paths']:
                    with path.open('rb') as source:
                        for block in iter(lambda: source.read(1 << 20), b''):
                            if cancel and cancel.is_set():
                                raise InterruptedError('Voice installation cancelled.')
                            total += len(block)
                            if total > MAX_ARCHIVE:
                                raise ValueError('Voice archive exceeds its size budget.')
                            digest.update(block)
                            target.write(block)
            with zipfile.ZipFile(archive) as package:
                with package.open('pack.json') as source:
                    raw = source.read((4 << 20) + 1)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('Voice archive has no valid pack.json.')
            spec = Pack(voice_id=data.get('voice_id'), name=data.get('voice_name'), version=data.get('version'),
                        archive_sha256=digest.hexdigest(), archive_bytes=total)
            return self.install(archive, spec, cancel=cancel), spec
        finally:
            archive.unlink(missing_ok=True)

    def _promote(self, stage, destination, cancel):
        # Antivirus/indexing can briefly hold a just-verified file too. Retry only
        # Windows sharing/access errors; never overwrite a competing destination.
        for delay in (.05,.1,.2,.4,None):
            if cancel and cancel.is_set():
                raise InterruptedError('Voice installation cancelled.')
            if (stage.is_symlink() or stage.resolve().parent!=self.base.resolve()
                    or destination.resolve().parent!=self.base.resolve() or destination.exists()):
                raise ValueError('Voice installation destination changed; previous voice kept.')
            try:
                stage.rename(destination)
                return
            except PermissionError as exc:
                if delay is None or getattr(exc,'winerror',None) not in (5,32,33):
                    raise
                if cancel:
                    if cancel.wait(delay):
                        raise InterruptedError('Voice installation cancelled.')
                else:
                    time.sleep(delay)

    def _directory(self, key):
        if not isinstance(key,str) or not re.fullmatch(r'[a-z0-9.-]+--[a-z0-9.-]+--[a-f0-9]{16}',key):
            raise ValueError('Invalid managed voice pack key.')
        path = self.base/key
        if path.resolve().parent!=self.base.resolve() or path.is_symlink():
            raise ValueError('Managed voice pack is outside its cache.')
        return path

    def cache(self, key):
        directory = self._directory(key)
        receipt = json.loads((directory/'managed.json').read_text(encoding='utf-8'))
        if not isinstance(receipt,dict) or receipt.get('owner')!=OWNER or receipt.get('key')!=key:
            raise ValueError('This voice folder is not managed by Paddock.')
        cache = VoiceCache(self.root,voice_id=receipt['voice_id'],pack_directory=directory)
        if cache.errors or not cache.index:
            raise ValueError('Installed voice pack verification failed: '+'; '.join(cache.errors))
        return cache

    def _remove(self, directory, files):
        """Delete only an exact, hashed, owned file set; preserve unexpected additions."""
        if directory.is_symlink() or directory.resolve().parent!=self.base.resolve():
            return False
        entries = list(directory.rglob('*'))
        if any(p.is_symlink() for p in entries):
            return False
        actual = {p.relative_to(directory).as_posix():p for p in entries if p.is_file()}
        if set(actual)!=set(files) or any(sha(actual[n].read_bytes())!=digest for n,digest in files.items()):
            return False
        for path in actual.values():
            path.unlink()
        for path in sorted((p for p in entries if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
            path.rmdir()
        directory.rmdir()
        return True

    def cleanup_except(self, selected):
        """Call only after a new selection is saved; never touch legacy private work."""
        warnings = []
        if not self.base.exists():
            return warnings
        if selected!='jim-private':
            self.cache(selected)  # no pruning around an invalid active selection
        elif not VoiceCache(self.root).index:
            raise ValueError('The private Jim pilot is not available; previous packs were preserved.')
        for directory in self.base.iterdir():
            if directory.name==selected or not directory.is_dir() or directory.name.startswith('.'):
                continue
            try:
                receipt_path=directory/'managed.json'
                if not receipt_path.is_file():
                    continue
                receipt=json.loads(receipt_path.read_text())
                if not isinstance(receipt,dict) or receipt.get('owner')!=OWNER or receipt.get('key')!=directory.name:
                    continue
                self._directory(directory.name)
                files={**receipt['files'],'managed.json':sha(receipt_path.read_bytes())}
                if not self._remove(directory,files):
                    warnings.append('Kept modified voice pack '+directory.name)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                warnings.append('Kept voice pack '+directory.name+': '+str(exc))
        return warnings

    def download(self, spec, *, cancel=None, progress=None):
        if not spec.url or not spec.distribution_approved:
            raise ValueError('This voice has no approved downloadable pack yet.')
        if cancel and cancel.is_set():raise InterruptedError('Voice download cancelled.')
        self.base.mkdir(parents=True,exist_ok=True)
        archive=self.base/('.download-'+uuid.uuid4().hex+'.zip')
        try:
            request=Request(asset_url(spec.url),headers={'User-Agent':'AMS2-Paddock-private-coach','Accept':'application/octet-stream'})
            with self.opener.open(request,timeout=15) as response, archive.open('xb') as target:
                if response.headers.get('Content-Length') and int(response.headers['Content-Length'])!=spec.archive_bytes:
                    raise ValueError('Voice download size differs from its pinned catalogue.')
                total=0
                while True:
                    if cancel and cancel.is_set():raise InterruptedError('Voice download cancelled.')
                    block=response.read(1<<16)
                    if not block:break
                    total+=len(block)
                    if total>spec.archive_bytes:raise ValueError('Voice download exceeded its pinned size.')
                    target.write(block)
                    if progress:progress(total,spec.archive_bytes)
            return self.install(archive,spec,cancel=cancel)
        finally:
            archive.unlink(missing_ok=True)

    def install(self, archive, spec, *, cancel=None):
        """Install immutable assets; activation and previous-pack pruning are separate."""
        with self.lock:
            if cancel and cancel.is_set():raise InterruptedError('Voice installation cancelled.')
            archive=Path(archive)
            if archive.stat().st_size!=spec.archive_bytes:
                raise ValueError('Voice archive size mismatch.')
            digest=hashlib.sha256()
            with archive.open('rb') as source:
                for block in iter(lambda:source.read(1<<20),b''):
                    if cancel and cancel.is_set():raise InterruptedError('Voice installation cancelled.')
                    digest.update(block)
            if digest.hexdigest()!=spec.archive_sha256:raise ValueError('Voice archive checksum mismatch.')
            destination=self._directory(spec.key)
            if destination.exists():
                self.cache(spec.key)
                return spec.key
            self.base.mkdir(parents=True,exist_ok=True)
            stage=self.base/('.stage-'+uuid.uuid4().hex);stage.mkdir()
            created={}
            try:
                with zipfile.ZipFile(archive) as package:
                    members=package.infolist()
                    if not 1<=len(members)<=10001 or sum(m.file_size for m in members)>MAX_UNPACKED:
                        raise ValueError('Voice archive exceeds its file or unpacked-size budget.')
                    names=set()
                    for member in members:
                        member_path(member.filename)
                        if (member.filename.casefold() in names or member.is_dir() or member.flag_bits&1
                                or stat.S_ISLNK(member.external_attr>>16)
                                or member.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)
                                or member.file_size>(4<<20 if member.filename=='pack.json' else 2<<20)):
                            raise ValueError('Unsupported voice archive member.')
                        names.add(member.filename.casefold())
                    with package.open('pack.json') as source:raw=source.read((4<<20)+1)
                    if len(raw)>4<<20:raise ValueError('Voice manifest exceeds its size budget.')
                    data=json.loads(raw)
                    if (not isinstance(data,dict) or data.get('format')!='paddock-voice-pack' or data.get('schema')!=1
                            or data.get('voice_id')!=spec.voice_id or data.get('voice_name')!=spec.name
                            or data.get('version')!=spec.version or not isinstance(data.get('clips'),list)
                            or not 1<=len(data['clips'])<=10000
                            or (spec.distribution_approved and (not isinstance(data.get('rights'),dict)
                                                               or data['rights'].get('status')!='cleared'))):
                        raise ValueError('Voice archive identity/version/rights metadata mismatch.')
                    files={'pack.json'}
                    for clip in data['clips']:
                        member_path(clip['radio'])
                        if not clip['radio'].endswith('.wav') or clip['radio'] in files:
                            raise ValueError('Voice archive has duplicate or non-WAV clips.')
                        files.add(clip['radio'])
                    if {m.filename for m in members}!=files:raise ValueError('Voice archive contains unlisted files.')
                    for name in files:
                        if cancel and cancel.is_set():raise InterruptedError('Voice installation cancelled.')
                        path=stage.joinpath(*member_path(name).parts);path.parent.mkdir(parents=True,exist_ok=True)
                        limit=4<<20 if name=='pack.json' else 2<<20
                        digest=hashlib.sha256();total=0
                        try:
                            with package.open(name) as source,path.open('xb') as target:
                                while True:
                                    if cancel and cancel.is_set():raise InterruptedError('Voice installation cancelled.')
                                    block=source.read(1<<16)
                                    if not block:break
                                    total+=len(block)
                                    if total>limit:raise ValueError('Voice member exceeds its size budget.')
                                    digest.update(block);target.write(block)
                        finally:
                            if path.is_file():created[name]=sha(path.read_bytes())
                manifest={'private':True,'publish_allowed':False,'voice_id':spec.voice_id,'voice_name':spec.name,
                          'version':spec.version,'clips':data['clips']}
                content=json.dumps(manifest,ensure_ascii=False,allow_nan=False).encode('utf-8')
                (stage/'manifest.json').write_bytes(content);created['manifest.json']=sha(content)
                cache=VoiceCache(self.root,voice_id=spec.voice_id,pack_directory=stage)
                if cache.errors or not cache.index:raise ValueError('Voice clip verification failed: '+'; '.join(cache.errors))
                receipt={'owner':OWNER,'key':spec.key,'voice_id':spec.voice_id,'name':spec.name,'version':spec.version,
                         'bytes':sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()),
                         'archive_sha256':spec.archive_sha256,'files':dict(created)}
                content=json.dumps(receipt,indent=2).encode()
                (stage/'managed.json').write_bytes(content);created['managed.json']=sha(content)
                if cancel and cancel.is_set():raise InterruptedError('Voice installation cancelled.')
                self._promote(stage,destination,cancel)
                return spec.key
            finally:
                if stage.exists():self._remove(stage,created)
