#!/usr/bin/env bash
# Grant the opencode sandbox write access to the Android toolchain directories,
# so an agent can run the emulator and talk to adb without the sandbox blocking
# writes to $HOME/.android and $HOME/Android/Sdk.
#
#   scripts/grant_sandbox_access.sh
#
# It edits the opencode permission config (adds two "external_directory: allow"
# rules) and prints the result. It backs up the config first. Idempotent: it
# won't add a rule that is already present.
set -euo pipefail

HOME_DIR="${HOME:-$HOME}"
CONFIG_CANDIDATES=(
  "${XDG_CONFIG_HOME:-$HOME_DIR/.config}/opencode/opencode.json"
  "$HOME_DIR/.config/opencode/config.json"
  "$HOME_DIR/.opencode/opencode.json"
)
CONFIG=""
for c in "${CONFIG_CANDIDATES[@]}"; do
  if [ -f "$c" ]; then CONFIG="$c"; break; fi
done
if [ -z "$CONFIG" ]; then
  echo "Could not find an opencode config. Looked in:"
  printf '  %s\n' "${CONFIG_CANDIDATES[@]}"
  echo
  echo "Create one at ~/.config/opencode/opencode.json and re-run, or add these"
  echo "rules by hand (this is what the script would add):"
  echo '  {"permission":"external_directory","pattern":"'"$HOME_DIR"'/.android/*","action":"allow"}'
  echo '  {"permission":"external_directory","pattern":"'"$HOME_DIR"'/Android/Sdk/*","action":"allow"}'
  exit 1
fi

echo "Found config: $CONFIG"
cp "$CONFIG" "$CONFIG.bak"
echo "Backed up to $CONFIG.bak"

python3 - "$CONFIG" "$HOME_DIR" <<'PY'
import json, sys
path, home = sys.argv[1], sys.argv[2]
rules = [
    {"permission": "external_directory", "pattern": f"{home}/.android/*", "action": "allow"},
    {"permission": "external_directory", "pattern": f"{home}/Android/Sdk/*", "action": "allow"},
]
data = json.load(open(path))

# The permissions live under a "permissions" key (list), or the whole file is a
# list. We insert the allow rules just before a trailing deny, so a broad
# "deny *" at the end does not override them.
perms = data.get("permissions") if isinstance(data, dict) else data
if not isinstance(perms, list):
    print("Could not find a permissions array in the config; nothing changed.")
    sys.exit(1)

def present(r):
    return any(isinstance(p, dict) and p.get("permission") == r["permission"]
               and p.get("pattern") == r["pattern"] and p.get("action") == "allow"
               for p in perms)

added = []
for r in rules:
    if present(r):
        continue
    # Insert before the last entry if it is a broad deny; else append.
    idx = len(perms)
    for i in range(len(perms) - 1, -1, -1):
        if isinstance(perms[i], dict) and perms[i].get("permission") == "*" \
           and perms[i].get("action") == "deny":
            idx = i
            break
    perms.insert(idx, r)
    added.append(r)

if isinstance(data, dict):
    data["permissions"] = perms

json.dump(data, open(path, "w"), indent=2)
print("Added rules:")
for r in added:
    print("  ", json.dumps(r))
if not added:
    print("  (all rules already present)")
print("Wrote", path)
PY

echo
echo "Done. Restart the opencode session for the new permissions to take effect."
