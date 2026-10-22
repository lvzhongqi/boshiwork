# Orrery in a container

[中文说明](README.zh-CN.md)

One image carries everything Orrery needs to run: the Python dependencies at
the exact versions `pyproject.toml` pins, ProVerif 2.05 compiled from its
official source (the release tarball's checksum is verified at build time), and
the web console. A user needs Docker and an API key of their own, nothing else.

Three things are deliberately **not** in the image. All of them live in the
workspace mounted into the container:

- **Corpus text.** ISO standards are copyrighted; a public image cannot carry
  them.
- **Recorded runs.** Put them into the workspace to replay them.
- **Any key.** A key belongs to its owner and is written only into that
  person's `config.yaml`.

## The workspace

Everything the container produces lands in one directory, mounted at `/work`.
It is the only directory to keep and back up; removing the container or
upgrading the image leaves it alone.

```
orrery-work/              mounted at /work
├── config.yaml           written on first start; the key typed on the settings panel is saved here
├── docs/                 your own protocol documents, one directory per protocol
│   └── MyProtocol/
│       ├── spec.md       the main document: .md / .txt / .pdf / .docx / .doc
│       └── refs/         optional: documents the main one cites
├── runs/                 everything each run produced: runs/<protocol>/<run>/
├── recordings/           optional: runs to replay, laid out like runs/
└── corpus/               optional: the VerdictBench corpus, scanned by the launch panel
```

`config.yaml` holds the key, so never share the whole workspace. To share a
result, share one run directory under `runs/`.

## Using it

1. Install Docker: Docker Desktop on macOS and Windows, Docker Engine on Linux.
2. Put the `compose.yaml` you were given into an empty directory. On Linux,
   create `orrery-work` inside it first; if `id -u` is not 1000, also create a
   `.env` file there with two lines, `ORRERY_UID=` and `ORRERY_GID=`, set to
   your own `id -u` and `id -g`.
3. Start it from that directory:

   ```bash
   docker compose up -d
   ```

4. Open <http://127.0.0.1:8000>. The console starts in recorded mode, which
   needs no key.
5. Switch to live at the top left, then pick a model backend and enter your key
   on the Config panel.
6. Put a protocol document into `orrery-work/docs/<protocol>/`, browse to
   `/work/docs/<protocol>` in the launch panel, pick the document and start.
7. Stop it:

   ```bash
   docker compose down
   ```

   A run in flight stops at its next safe point and keeps what it has; the page
   can re-enter it at any step later.

From the command line instead of the page:

```bash
docker compose run --rm orrery run --name MyProtocol --dir /work/docs/MyProtocol
```

## Handing in and replaying runs

- **What to hand in:** the one directory `orrery-work/runs/<protocol>/<run>/`,
  zipped. Not `latest`, which is a link to the newest run. A run directory's
  config is redacted and holds no key.
- **How to read one:** unzip it into your own workspace as
  `recordings/<protocol>/<run>/` and open the console; it is in the recorded
  mode's list. How the model was extracted, what each round said and where
  every verdict came from all replay in full.

## Building and publishing

Run these from the repository root. `.dockerignore` is an allowlist, so only
the source reaches the build context: `config.yaml`, `runs/`, `tests/` and
`experiments/` never leave the machine.

```bash
docker build -t orrery:1.0.1 .
```

Both architectures, pushed to a registry. With one only, machines of the other
kind run ProVerif under emulation, which is much slower:

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/orrery:1.0.1 --push .
```

Set the default `image:` in the `compose.yaml` you hand out to the address you
pushed to. Where Docker Hub is unreliable for the recipients, push to a
registry they can reach, or hand the image out as a file they `docker load`:

```bash
docker save orrery:1.0.1 | gzip > orrery-1.0.1.tar.gz
```

Conventions:

- **The image version** follows `PROJECT_VERSION` in `orrery/version.py`.
- **Upgrading ProVerif** means changing both build arguments,
  `PROVERIF_VERSION` and `PROVERIF_SHA256`. A new version with the old checksum
  fails the build on purpose: another release can reach different verdicts.
- **Upgrading the Python base** means changing its tag and its digest together.
- **Locked knobs** are named by the image's `ORRERY_READ_ONLY`: the solver path
  and the run directory, which are facts of the image. They can be changed in
  `config.yaml`, not from the page.
- **Licenses:** ProVerif is GPL-2.0. Its license and the exact source tarball
  the binary was built from are in the image under
  `/usr/local/share/doc/proverif/`.

The image installs Orrery the ordinary way into a virtual environment at
`/opt/venv`, with no source tree. `ORRERY_HOME=/work` tells the installed copy
where its data lives: the default `config.yaml`, and the anchor for any
relative path in it.

## Troubleshooting

- **The port is taken:** put `ORRERY_PORT=8001` in `.env` and open port 8001.
- **On Linux, the workspace is not writable:** create the directory yourself
  and set `ORRERY_UID` and `ORRERY_GID` as in step 2. A directory Docker
  creates for you belongs to root, and the container's user cannot write it.
- **A large protocol's solve is judged out of memory:** one ProVerif process
  may use at most 90% of the memory the container has. Raise the memory in
  Docker Desktop's resource settings.
- **Never open the port to other machines:** the console has no login, so
  anyone who can reach the port can start runs on your key. Keep the
  `127.0.0.1` in `compose.yaml`.
