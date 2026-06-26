#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${URBAN_AGENT_REPO_URL:-https://github.com/xuanniao57/UrbanAgents.git}"
URBAN_AGENT_HOME="${URBAN_AGENT_HOME:-$PWD/.urban-agent}"
INSTALL_DIR="${URBAN_AGENT_INSTALL_DIR:-$URBAN_AGENT_HOME/urban-agent}"
BRANCH="main"
USE_VENV=true
RUN_SETUP=true

usage() {
    cat <<'EOF'
UrbanAgent Installer

Usage: install.sh [OPTIONS]

Options:
  --dir PATH          Code checkout/install directory
                      default: $URBAN_AGENT_HOME/urban-agent
  --urban-home PATH   User data directory for .env, config.yaml, runs, logs
                      default: ./.urban-agent
  --branch NAME       Git branch to install (default: main)
  --repo URL          Git repository URL
  --no-venv           Install into the current Python environment
  --skip-setup        Skip first-time setup wizard
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --urban-home)
            URBAN_AGENT_HOME="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --repo)
            REPO_URL="$2"
            shift 2
            ;;
        --no-venv)
            USE_VENV=false
            shift
            ;;
        --skip-setup)
            RUN_SETUP=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 2
            ;;
    esac
done

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

PYTHON_BIN="${PYTHON:-python3}"
if ! command_exists git; then
    echo "git is required to install UrbanAgent." >&2
    exit 2
fi
if ! command_exists "$PYTHON_BIN"; then
    echo "python3 is required to install UrbanAgent." >&2
    exit 2
fi

mkdir -p "$URBAN_AGENT_HOME"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "Updating UrbanAgent at $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --all --prune
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "Cloning UrbanAgent into $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

if [[ "$USE_VENV" == true ]]; then
    if command_exists uv; then
        uv venv .venv --python 3.10
        PYTHON_BIN="$INSTALL_DIR/.venv/bin/python"
        uv pip install --python "$PYTHON_BIN" -e "$INSTALL_DIR"
    else
        "$PYTHON_BIN" -m venv .venv
        PYTHON_BIN="$INSTALL_DIR/.venv/bin/python"
        "$PYTHON_BIN" -m pip install --upgrade pip
        "$PYTHON_BIN" -m pip install -e "$INSTALL_DIR"
    fi
else
    "$PYTHON_BIN" -m pip install -e "$INSTALL_DIR"
fi

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/urban-agent" <<EOF
#!/usr/bin/env bash
export URBAN_AGENT_HOME="$URBAN_AGENT_HOME"
export URBAN_AGENT_INSTALL_DIR="$INSTALL_DIR"
exec "$PYTHON_BIN" -m urban_agent "\$@"
EOF
chmod +x "$HOME/.local/bin/urban-agent"

URBAN_AGENT_HOME="$URBAN_AGENT_HOME" URBAN_AGENT_INSTALL_DIR="$INSTALL_DIR" "$PYTHON_BIN" -m urban_agent init

if [[ "$RUN_SETUP" == true ]]; then
    if [[ -t 0 ]]; then
        URBAN_AGENT_HOME="$URBAN_AGENT_HOME" URBAN_AGENT_INSTALL_DIR="$INSTALL_DIR" "$PYTHON_BIN" -m urban_agent setup
    else
        echo "Setup wizard skipped because stdin is not interactive. Run 'urban-agent setup' later."
    fi
fi

echo ""
echo "UrbanAgent installed"
echo "  Code:      $INSTALL_DIR"
echo "  User data: $URBAN_AGENT_HOME"
echo "  Command:   $HOME/.local/bin/urban-agent"
echo ""
echo "Add ~/.local/bin to PATH if 'urban-agent' is not found."
