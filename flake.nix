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

          echo "🚀 Entering Zephyr development environment"

          # Prepend system paths to ensure system GCC is found first
          # This is critical for portable native_sim builds
          export PATH="/usr/bin:/usr/local/bin:$PATH"

          # Check for system GCC (required for portable native_sim builds)
          if ! command -v gcc &> /dev/null; then
            echo "❌ Error: System GCC not found in PATH"
            echo "   For portable native_sim builds, you need system GCC installed."
            echo "   Install with: sudo apt install gcc gcc-multilib g++-multilib"
            exit 1
          fi

          SYSTEM_GCC=$(which gcc)
          if [[ "$SYSTEM_GCC" == *"/nix/store"* ]]; then
            echo "❌ Error: GCC is still pointing to Nix store: $SYSTEM_GCC"
            echo "   System GCC should be in /usr/bin, not Nix store"
            exit 1
          fi
          echo "✓ Host GCC: $SYSTEM_GCC ($(gcc --version | head -1))"

          # Ensure we're in a west workspace
          if [ ! -d "../.west" ]; then
            echo "❌ Error: Not in a west workspace root. Directory ../.west not found."
            echo "   Please run 'west init' first or ensure you're in the correct directory."
            exit 1
          fi

          # Set up ccache with absolute path
          export CCACHE_DIR="$(realpath ../.ccache)"
          export CCACHE_MAXSIZE="2G"
          # Ignore -specs compiler flag variations for cross-compilation caching
          export CCACHE_IGNOREOPTIONS="-specs=* --specs=*"
          # Note: Don't set USE_CCACHE - Zephyr will auto-detect ccache if it's in PATH
          mkdir -p "$CCACHE_DIR" || { echo "❌ Failed to create ccache directory"; exit 1; }
          echo "✓ ccache directory: $CCACHE_DIR"

          # Set up Python virtual environment with uv
          VENV_DIR="$(realpath ../.venv)"
          if [ ! -d "$VENV_DIR" ]; then
            echo "📦 Creating Python 3.13 virtual environment with uv..."
            cd .. || exit 1
            uv venv --python 3.13 --seed || { echo "❌ Failed to create venv"; exit 1; }
            cd - > /dev/null || exit 1
          fi

          # Activate the virtual environment
          if [ -f "$VENV_DIR/bin/activate" ]; then
            source "$VENV_DIR/bin/activate" || { echo "❌ Failed to activate venv"; exit 1; }
            echo "✓ Python venv: $VENV_DIR ($(python --version))"
          else
            echo "❌ Error: Virtual environment not found at $VENV_DIR"
            exit 1
          fi

          echo "📦 Installing west..."
          pip install west || { echo "❌ Failed to install west"; exit 1; }

          # Run west update to sync dependencies
          echo "🔄 Running west update..."
          west update || { echo "❌ west update failed"; exit 1; }

          # Install Python dependencies from committed pylock.toml if it exists
          # Otherwise fall back to west packages pip --install
          if [ -f "pylock.toml" ]; then
            echo "📦 Installing Python dependencies from pylock.toml..."
            uv pip install --requirement pylock.toml || { echo "❌ Failed to install from pylock.toml"; exit 1; }
          fi

          echo "📦 Installing Python dependencies via west..."
          west zephyr-export || { echo "❌ west zephyr-export failed"; exit 1; }
          west packages pip --install || { echo "❌ west packages pip --install failed"; exit 1; }


          # Always regenerate pylock.toml to keep it up-to-date
          echo "📝 Regenerating pylock.toml..."
          uv pip freeze > requirements.tmp.in
          uv pip compile requirements.tmp.in --format pylock.toml -o pylock.toml || { echo "❌ Failed to generate pylock.toml"; exit 1; }
          rm requirements.tmp.in
          echo "✓ pylock.toml regenerated"

          echo "🔧 Installing Zephyr SDK (arm-zephyr-eabi toolchain)..."
          west sdk install -t arm-zephyr-eabi || { echo "❌ Zephyr SDK installation failed"; exit 1; }

          # Set Zephyr environment variables with absolute paths
          export ZEPHYR_BASE="$(realpath ../zephyr)"
          echo "✓ ZEPHYR_BASE set to: $ZEPHYR_BASE"

          set +e  # Restore normal error handling for interactive shell
        '';

      in
      {
        devShells.default = pkgs.mkShell {
          inherit buildInputs shellHook;

          # Environment variables are set in shellHook to use absolute paths
        };
      }
    );
}
