# Parse KEY=VALUE env files without `source`.
# `source` breaks on unquoted apostrophes such as:
#   DEFAULT_FROM_EMAIL=Nordin's AI <info@thenordins.org>
#
# Usage (from repo scripts):
#   # shellcheck source=/dev/null
#   source "$WS/scripts/load_env.sh"
#   pastor_load_env_file "$WS/config.env"

pastor_load_env_file() {
  local file="${1:-}"
  local line key val
  [[ -n "$file" && -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    val="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    key="${key#"${key%%[![:space:]]*}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ ${#val} -ge 2 ]]; then
      if [[ "$val" == \"*\" ]]; then
        val="${val:1:${#val}-2}"
        val="${val//\\\"/\"}"
      elif [[ "$val" == \'*\' ]]; then
        val="${val:1:${#val}-2}"
      fi
    fi
    export "${key}=${val}"
  done < "$file"
}

# Print KEY="escaped value" so the line can be sourced by bash.
pastor_env_quoted_assignment() {
  local key="${1:-}"
  local val="${2-}"
  local escaped
  [[ -n "$key" ]] || return 1
  escaped="$(printf '%s' "$val" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\$/\\$/g' -e 's/`/\\`/g')"
  printf '%s="%s"' "$key" "$escaped"
}

# Escape a value so it is safe inside single quotes in a generated script.
pastor_escape_sq() {
  local s="${1-}"
  s="${s//\'/\'\\\'\'}"
  printf '%s' "$s"
}
