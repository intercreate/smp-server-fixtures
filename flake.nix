{
  description = "Zephyr RTOS development environment for smp-server-fixtures";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        # These packages match the apt requirements:
        # git cmake ninja-build gperf ccache dfu-util device-tree-compiler wget
        # python3-dev python3-venv python3-tk xz-utils file make gcc gcc-multilib
        # g++-multilib libsdl2-dev libmagic1
        buildInputs =
          with pkgs;
          [
            git
            cmake
            ninja
            gperf
            ccache
            gnumake
            file
            wget
            xz
            dtc
            # NOTE: We intentionally do NOT include gcc/stdenv.cc from Nix
            # For native_sim builds, we need to use the system's GCC to produce
            # portable binaries that can run on standard Ubuntu systems
            uv
            pkg-config
            nixfmt-rfc-style
          ]
          ++ pkgs.lib.optionals pkgs.stdenv.isLinux [
          ];

        # Shell hook that sets up the environment
        shellHook = ''
          set -e  # Exit on any error

          # Set up logging
          # Log file is created in the flake directory (not checked in)
          # We'll determine the log path after finding FLAKE_DIR

          # Prepend system paths to ensure system GCC is found first
          # This is critical for portable native_sim builds
          export PATH="/usr/bin:/usr/local/bin:$PATH"

          # Check for system GCC (required for portable native_sim builds)
          if ! command -v gcc &> /dev/null; then
            echo "❌ Error: System GCC not found in PATH"
            echo "   Install with: sudo apt install gcc gcc-multilib g++-multilib"
            exit 1
          fi

          SYSTEM_GCC=$(which gcc)
          if [[ "$SYSTEM_GCC" == *"/nix/store"* ]]; then
            echo "❌ Error: GCC is still pointing to Nix store: $SYSTEM_GCC"
            exit 1
          fi

          # Find the flake directory
          # First check if NIX_FLAKE_DIR is set (for CI/automated use)
          if [ -n "$NIX_FLAKE_DIR" ] && [ -f "$NIX_FLAKE_DIR/flake.nix" ]; then
            FLAKE_DIR="$NIX_FLAKE_DIR"
          else
            # Search upward from PWD
            FLAKE_DIR="$PWD"
            while [ ! -f "$FLAKE_DIR/flake.nix" ] && [ "$FLAKE_DIR" != "/" ]; do
              FLAKE_DIR="$(dirname "$FLAKE_DIR")"
            done

            if [ ! -f "$FLAKE_DIR/flake.nix" ]; then
              echo "❌ Error: Could not find flake.nix"
              echo "   Set NIX_FLAKE_DIR=/path/to/flake or run from within the flake directory"
              exit 1
            fi
          fi

          # Workspace root is parent of flake directory
          WORKSPACE_ROOT="$(dirname "$FLAKE_DIR")"

          # Set up log file for verbose output
          INIT_LOG="$FLAKE_DIR/nix-develop-init.log"
          echo "=== Nix develop shell initialization: $(date) ===" > "$INIT_LOG"
          echo "Workspace root: $WORKSPACE_ROOT" >> "$INIT_LOG"

          echo "🚀 Zephyr environment (log: $INIT_LOG)"

          # Ensure we're in a west workspace
          if [ ! -d "$WORKSPACE_ROOT/.west" ]; then
            echo "❌ Error: Not in a west workspace root. Directory $WORKSPACE_ROOT/.west not found."
            echo "   Please run 'west init' first or ensure you're in the correct directory."
            exit 1
          fi

          # Set up ccache with absolute path
          export CCACHE_DIR="$WORKSPACE_ROOT/.ccache"
          export CCACHE_MAXSIZE="2G"
          # Ignore -specs compiler flag variations for cross-compilation caching
          export CCACHE_IGNOREOPTIONS="-specs=* --specs=*"
          # Note: Don't set USE_CCACHE - Zephyr will auto-detect ccache if it's in PATH
          mkdir -p "$CCACHE_DIR" || { echo "❌ Failed to create ccache directory"; exit 1; }

          # Set up Python virtual environment with uv
          VENV_DIR="$WORKSPACE_ROOT/.venv"
          if [ ! -d "$VENV_DIR" ]; then
            echo "📦 Creating Python 3.13 virtual environment with uv..."
            uv venv --python 3.13 --seed "$VENV_DIR" || { echo "❌ Failed to create venv"; exit 1; }
          fi

          # Activate the virtual environment
          if [ -f "$VENV_DIR/bin/activate" ]; then
            source "$VENV_DIR/bin/activate" || { echo "❌ Failed to activate venv"; exit 1; }
          else
            echo "❌ Error: Virtual environment not found at $VENV_DIR"
            exit 1
          fi

          pip install west >> "$INIT_LOG" 2>&1 || { echo "❌ Failed to install west (see $INIT_LOG)"; exit 1; }
          west update >> "$INIT_LOG" 2>&1 || { echo "❌ west update failed (see $INIT_LOG)"; exit 1; }

          # Install Python dependencies from committed pylock.toml if it exists
          if [ -f "$FLAKE_DIR/pylock.toml" ]; then
            uv pip install --requirement "$FLAKE_DIR/pylock.toml" >> "$INIT_LOG" 2>&1 || { echo "❌ Failed to install from pylock.toml (see $INIT_LOG)"; exit 1; }
          fi

          west zephyr-export >> "$INIT_LOG" 2>&1 || { echo "❌ west zephyr-export failed (see $INIT_LOG)"; exit 1; }
          west packages pip --install >> "$INIT_LOG" 2>&1 || { echo "❌ west packages pip --install failed (see $INIT_LOG)"; exit 1; }

          # Always regenerate pylock.toml to keep it up-to-date
          uv pip freeze > "$FLAKE_DIR/requirements.tmp.in" 2>> "$INIT_LOG"
          uv pip compile "$FLAKE_DIR/requirements.tmp.in" --format pylock.toml -o "$FLAKE_DIR/pylock.toml" \
            --custom-compile-command "nix develop" >> "$INIT_LOG" 2>&1 || { echo "❌ Failed to generate pylock.toml (see $INIT_LOG)"; exit 1; }
          rm "$FLAKE_DIR/requirements.tmp.in"

          west sdk install -t arm-zephyr-eabi >> "$INIT_LOG" 2>&1 || { echo "❌ Zephyr SDK installation failed (see $INIT_LOG)"; exit 1; }

          # Set Zephyr environment variables with absolute paths
          export ZEPHYR_BASE="$WORKSPACE_ROOT/zephyr"

          set +e  # Restore normal error handling for interactive shell
        '';

      in
      {
        devShells.default = pkgs.mkShell {
          inherit buildInputs shellHook;
        };
      }
    );
}
