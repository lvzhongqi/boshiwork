# The Orrery console as one image: the Python environment pyproject.toml pins,
# ProVerif built from its official source, and the console, installed the
# standard way into a virtual environment. Nothing a person brings is baked
# in: no corpus text, no recorded runs, no API key. All of that lives in the
# workspace mounted at /work (docker/README.md).
#
#   docker build -t orrery:1.0.1 .
#   docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/orrery:1.0.1 --push .

# Pinned by digest as well as tag: the tag names the Python release, the digest
# the exact bytes, so a rebuild a year from now starts from the same system.
# Bumping it is a deliberate edit of both.
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2


# ── ProVerif, compiled from the official source ──────────────────────────
# Built on the same base image, so the binary links against exactly the C
# library the final image carries. The checksum is of the release tarball:
# changing the version without it fails the build, which is the point, since
# the published runs used 2.05 and another release can answer differently.
# -nointeract skips the interactive simulator, which needs GTK. ProVerif is
# GPL-2.0, so its license and the exact source the binary was built from ship
# beside the binary, which is what the license asks of a binary copy.
FROM ${PYTHON_IMAGE} AS proverif

ARG PROVERIF_VERSION=2.05
ARG PROVERIF_SHA256=4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4

RUN apt-get update \
 && apt-get install -y --no-install-recommends ocaml-nox curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -fsSL -o "proverif${PROVERIF_VERSION}.tar.gz" \
        "https://bblanche.gitlabpages.inria.fr/proverif/proverif${PROVERIF_VERSION}.tar.gz" \
 && echo "${PROVERIF_SHA256}  proverif${PROVERIF_VERSION}.tar.gz" | sha256sum -c - \
 && tar -xzf "proverif${PROVERIF_VERSION}.tar.gz" \
 && cd "proverif${PROVERIF_VERSION}" \
 && ./build -nointeract \
 && mkdir -p /out/doc \
 && install -m 0755 proverif /out/proverif \
 && install -m 0644 LICENSE /out/doc/LICENSE \
 && install -m 0644 "../proverif${PROVERIF_VERSION}.tar.gz" /out/doc/

# The binary has to parse a model before it is shipped.
RUN printf 'free c: channel.\nprocess 0\n' > /tmp/smoke.pv \
 && /out/proverif -parse-only /tmp/smoke.pv


# ── Orrery, installed into a virtual environment ─────────────────────────
# The dependency closure first, read out of pyproject.toml, so a code change
# rebuilds only the layer after it; pyproject pins every version exactly. Then
# the package itself, as an ordinary (non-editable) install: the source tree
# stays in this stage and never reaches the final image.
FROM ${PYTHON_IMAGE} AS python

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH
RUN python -m venv /opt/venv

WORKDIR /src
COPY pyproject.toml README.md ./
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb')); print('\n'.join(d['project']['dependencies']))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt
COPY orrery ./orrery
RUN pip install --no-deps .


# ── The console ──────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE}

LABEL org.opencontainers.image.title="Orrery" \
      org.opencontainers.image.description="Protocol documents to ProVerif models, with a web console"

# ORRERY_HOME is where an installed copy keeps its data, so the default config
# and every relative path resolve inside the workspace. HOME is the workspace
# too: the launch panel's file browser opens there, and a uid with no passwd
# entry still has a home. ORRERY_READ_ONLY locks the two knobs this image
# fixes, the solver it ships and the run directory on the volume.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/work \
    ORRERY_HOME=/work \
    ORRERY_READ_ONLY=proverif.executable,paths.work_root

COPY --from=proverif /out/proverif /usr/local/bin/proverif
COPY --from=proverif /out/doc/ /usr/local/share/doc/proverif/
COPY --from=python /opt/venv /opt/venv
COPY docker/config.docker.yaml /usr/local/share/orrery/config.docker.yaml
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/orrery-entrypoint

RUN useradd --uid 1000 --home-dir /work --no-create-home --shell /usr/sbin/nologin orrery \
 && mkdir -p /work \
 && chown orrery:orrery /work

USER orrery
WORKDIR /work
VOLUME ["/work"]
EXPOSE 8000

# Answers only while the console is up; a one-off subcommand container reads
# as unhealthy, which is harmless. A static route, so a large work root does
# not make the check slow.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta/event-types', timeout=4)"]

ENTRYPOINT ["orrery-entrypoint"]
