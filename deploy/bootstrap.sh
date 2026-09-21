#!/usr/bin/env bash
# Run as root on the dedicated Ubuntu 24.04 ARM host after copying a release to /tmp/harbor-release.tar.gz.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git python3-venv caddy xz-utils
test "$(uname -m)" = aarch64
NODE_VERSION=22.22.0
mkdir -p /opt/harbor-review/releases /var/lib/harbor-review/reference
cd /tmp
curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-arm64.tar.xz"
curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt"
grep " node-v${NODE_VERSION}-linux-arm64.tar.xz$" SHASUMS256.txt | sha256sum -c -
tar -xJf "node-v${NODE_VERSION}-linux-arm64.tar.xz" -C /opt
ln -sfn "/opt/node-v${NODE_VERSION}-linux-arm64/bin/node" /usr/bin/node
ln -sfn "/opt/node-v${NODE_VERSION}-linux-arm64/bin/npm" /usr/bin/npm
id harbor >/dev/null 2>&1 || useradd --system --home-dir /var/lib/harbor-review --shell /usr/sbin/nologin harbor
RELEASE="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "/opt/harbor-review/releases/$RELEASE"
tar -xzf /tmp/harbor-release.tar.gz -C "/opt/harbor-review/releases/$RELEASE"
cd "/opt/harbor-review/releases/$RELEASE"
npm ci --no-audit --no-fund
npm run build
ln -sfn "/opt/harbor-review/releases/$RELEASE" /opt/harbor-review/current
if [ ! -d /opt/hermes-agent/.git ]; then
  git init /opt/hermes-agent
  git -C /opt/hermes-agent remote add origin https://github.com/NousResearch/hermes-agent
fi
PIN=44945d224c2ccd6e0a55f16223c7ab0dd39331bf
git -C /opt/hermes-agent fetch --depth=1 origin "$PIN"
git -C /opt/hermes-agent checkout --detach "$PIN"
test "$(git -C /opt/hermes-agent rev-parse HEAD)" = "$PIN"
python3 -m venv /opt/harbor-uv
/opt/harbor-uv/bin/pip install uv
cd /opt/hermes-agent
/opt/harbor-uv/bin/uv sync --frozen --no-dev --python /usr/bin/python3
/opt/harbor-uv/bin/uv pip install --python .venv/bin/python 'python-telegram-bot[webhooks]==22.8' 'aiohttp==3.14.3'
mkdir -p /var/lib/harbor-review/hermes/plugins
cp -r /opt/harbor-review/current/hermes/shipping-review /var/lib/harbor-review/hermes/plugins/
cp /opt/harbor-review/current/deploy/hermes-config.yaml /var/lib/harbor-review/hermes/config.yaml
cp /tmp/harbor-emails.json /var/lib/harbor-review/reference/emails.json
install -m 0600 /tmp/harbor-review.env /etc/harbor-review.env
sed -i 's/\r$//' /etc/harbor-review.env
chown -R harbor:harbor /var/lib/harbor-review
chmod 0700 /var/lib/harbor-review
cp /opt/harbor-review/current/deploy/harbor-*.service /etc/systemd/system/
install -m 0644 /opt/harbor-review/current/deploy/deallocate.py /usr/local/lib/harbor-deallocate.py
cp /opt/harbor-review/current/deploy/harbor-deallocate.timer /etc/systemd/system/
cp /tmp/harbor-Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
caddy validate --config /etc/caddy/Caddyfile
systemctl enable harbor-web harbor-hermes harbor-interaction caddy
# Start explicitly only after stopping the corresponding laptop polling consumer.
printf 'Installed release %s. Services are not started by this script.\n' "$RELEASE"
