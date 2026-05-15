#!/usr/bin/env bash
# CCCP v2 — provision/update the Azure hub and write the runtime config.
#
# Run this rarely and manually: on initial setup, or to rotate the SAS.
# It is deliberately NOT called by install.sh — install.sh must stay fast.
#
# Requires: terraform, and az (logged in via `az login`).

set -euo pipefail

cd "$(dirname "$0")"

echo "Apply Terraform"
terraform init -input=false
terraform apply   # interactive plan review + confirmation

account=$(terraform output -raw storage_account_name)
container=$(terraform output -raw container_name)
rg=$(terraform output -raw resource_group_name)

echo "Mint container SAS"
# Container-scoped SAS with the full set a comrade needs: read, write, delete,
# list, add, create. Expiry is a runtime concern, not Terraform state — re-run
# this script to rotate. 1-year window for now; lifecycle TBD (Cloud Services doc).
expiry=$(date -u -d '+1 year' '+%Y-%m-%dT%H:%MZ' 2>/dev/null \
  || date -u -v+1y '+%Y-%m-%dT%H:%MZ')
sas=$(az storage container generate-sas \
  --account-name "$account" \
  --name "$container" \
  --permissions rwdlac \
  --expiry "$expiry" \
  --https-only \
  --auth-mode key \
  --output tsv)

# Write the config into the repo (gitignored) — it is the source of truth, just
# like every other dotfile here. install.sh deploys it to ~/.config/cccp/.
repo_root="$(cd .. && pwd)"
config_dir="$repo_root/.config/cccp"
config="$config_dir/config"
mkdir -p "$config_dir"

echo "Write config (repo source of truth): $config"
umask 077
cat > "$config" <<EOF
# CCCP runtime config — written by tf/apply.sh into the repo (gitignored).
# Personal/general default; project .env files override per-CWD.
# Deployed to ~/.config/cccp/config by install.sh.
# CCCP_PREFIX is optional — cccp defaults it to __default__.
CCCP_ACCOUNT=$account
CCCP_CONTAINER=$container
CCCP_SAS=$sas
EOF

echo "Done. Hub: $account / $container (rg: $rg)"
echo "Config written to the repo — run install.sh to deploy it to ~/.config/cccp/."
