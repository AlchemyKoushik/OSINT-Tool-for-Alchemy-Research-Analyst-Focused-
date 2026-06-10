#!/bin/sh
set -eu

template_path="/opt/osint/index.template.html"
target_path="/usr/share/nginx/html/index.html"

api_url="${OSINT_PUBLIC_API_URL:-}"
static_version="${STATIC_ASSET_VERSION:-$(date +%s)}"

escaped_api_url=$(printf '%s' "$api_url" | sed 's/[\/&]/\\&/g')
escaped_static_version=$(printf '%s' "$static_version" | sed 's/[\/&]/\\&/g')

cp "$template_path" "$target_path"
sed -i "s|__OSINT_API_URL_META_CONTENT__|$escaped_api_url|g" "$target_path"
sed -i "s|__STATIC_ASSET_VERSION_VALUE__|$escaped_static_version|g" "$target_path"
