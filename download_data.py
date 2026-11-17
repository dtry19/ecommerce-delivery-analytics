"""Download the pinned original Olist archive and write verified provenance."""
import argparse
import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

URL='https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce?datasetVersionNumber=2'
ARCHIVE_SHA256='967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784'
SOURCE='https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce'

def acquire(directory,archive=None):
    payload=Path(archive).read_bytes() if archive else urllib.request.urlopen(URL,timeout=120).read()
    digest=hashlib.sha256(payload).hexdigest()
    if digest!=ARCHIVE_SHA256:
        raise ValueError('Archive differs from pinned Olist v2; inspect the source before updating the checksum')
    files={}
    with zipfile.ZipFile(io.BytesIO(payload)) as zipped:
        contents={Path(n).name:zipped.read(n) for n in zipped.namelist() if n.endswith('.csv')}
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    # Verify all existing paths before writing anything.
    for name,content in contents.items():
        destination=directory/name
        if destination.exists() and destination.read_bytes()!=content:
            raise ValueError(f'Existing file differs; use another raw directory: {destination}')
        records=csv.reader(io.StringIO(content.decode('utf-8-sig'),newline=''))
        next(records)
        files[name]={'rows':sum(1 for _ in records),'sha256':hashlib.sha256(content).hexdigest()}
    manifest={'dataset':'Brazilian E-Commerce Public Dataset by Olist','publisher':'Olist',
      'source_url':SOURCE,'download_url':URL,'version':2,'license':'CC BY-NC-SA 4.0',
      'license_url':'https://creativecommons.org/licenses/by-nc-sa/4.0/',
      'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
      'archive_sha256':digest,'files':files}
    for name,content in contents.items():
        (directory/name).write_bytes(content)
    (directory/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',type=Path,default=Path(__file__).parent/'data/raw')
    parser.add_argument('--archive',type=Path,help='Verify and use an already downloaded archive')
    args=parser.parse_args()
    print(json.dumps(acquire(args.raw_dir,args.archive),indent=2))
