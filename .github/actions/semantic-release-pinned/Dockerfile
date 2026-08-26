# Vendored from python-semantic-release/python-semantic-release's
# src/gh_action/Dockerfile (pinned at 39dd2052, v10.6.1), unchanged except for
# the gitpython pin in requirements.txt.
#
# GitPython 3.1.60 (2026-08-25) removed Actor.name_email_regex, which
# semantic_release.cli.config reads unconditionally — every config load
# crashes. PSR requires gitpython ~= 3.0 (unpinned), and the official action
# builds this image fresh at job start, so a pinned action SHA still breaks
# the moment a new GitPython lands on PyPI. There is no action input that
# reaches into the upstream image's dependency resolution, so vendoring is
# the only lever — see python-semantic-release/python-semantic-release#1476.
# Drop this directory and point release.yml back at the upstream action once
# #1477 ships in a release — tracked in shawnoster/aya#352.
FROM python:3.14-slim-trixie
ARG WORK_DIR="/opt/psr"

WORKDIR ${WORK_DIR}

ENV PSR_DOCKER_GITHUB_ACTION=true \
    PYTHONDONTWRITEBYTECODE=1 \
    PSR_VENV_BIN="${WORK_DIR}/.venv/bin"

# Copy action utilities into container
COPY . ./

RUN \
    # Install desired packages
    apt update && apt install -y --no-install-recommends \
        # install git with git-lfs support
        git git-lfs \
        # install ssh client for git signing
        openssh-client \
        # install python cmodule / binary module build utilities
        python3-dev gcc make cmake cargo \
    # Configure global pip
    && { \
        printf '%s\n' "[global]"; \
        printf '%s\n' "disable-pip-version-check = true"; \
    } > /etc/pip.conf \
    # Create virtual environment for python-semantic-release
    && python3 -m venv "$(dirname "${PSR_VENV_BIN}")" \
    # Update core utilities in the virtual environment
    && "${PSR_VENV_BIN}/pip" install --upgrade pip setuptools wheel \
    # Install psr & its dependencies from source into virtual environment
    && "${PSR_VENV_BIN}/pip" install --pre -r requirements.txt \
    # Validate binary availability
    && bash -c "${PSR_VENV_BIN}/semantic-release --help" \
    # make action script executable
    && chmod +x "${WORK_DIR}/action.sh" \
    # Put action script in PATH
    && ln -s "${WORK_DIR}/action.sh" /usr/local/bin/action-entrypoint \
    # Clean up
    && apt clean && rm -rf /var/lib/apt/lists/* \
    && find /tmp -mindepth 1 -delete

ENTRYPOINT ["/usr/local/bin/action-entrypoint"]
