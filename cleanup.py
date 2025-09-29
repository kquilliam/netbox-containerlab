import subprocess
import os
import shutil
import argparse

def destroy_containerlab(topology_file: str):
    """Executes the containerlab destroy command for a specific topology file."""
    print("--- Destroying Containerlab Environment ---")
    
    if not os.path.exists(topology_file):
        print(f"   -> 🟡 Topology file not found, skipping destroy: {topology_file}")
        return

    command = ["containerlab", "destroy", "-t", topology_file, "--cleanup"]
    
    print(f"   -> Running command: {' '.join(command)}")
    
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        print("   ✅ Containerlab environment destroyed successfully.")
    except FileNotFoundError:
        print("   -> ❌ Error: 'containerlab' command not found. Is it installed and in your PATH?")
    except subprocess.CalledProcessError as e:
        # Hide stdout for clean error reporting, as clab can be noisy on failure
        print(f"   -> ❌ Error during destroy: Containerlab exited with an error.")
        print(f"      STDERR: {e.stderr.strip()}")
    except Exception as e:
        print(f"   -> ❌ An unexpected error occurred: {e}")

def remove_generated_files(lab_dir: str):
    """Removes the entire lab-specific directory."""
    print("\n--- Removing Generated Lab Directory ---")
    
    if os.path.isdir(lab_dir):
        try:
            shutil.rmtree(lab_dir)
            print(f"   ✅ Successfully removed directory: {lab_dir}")
        except OSError as e:
            print(f"   -> ❌ Error removing directory {lab_dir}: {e}")
    else:
        print(f"   -> 🟡 Directory not found, skipping: {lab_dir}")

def main():
    """Main function to run the cleanup process."""
    parser = argparse.ArgumentParser(description="Destroy a Containerlab environment and remove its generated files.")
    parser.add_argument("--site", dest="site_name", help="The name of the site to clean up.", required=True)
    args = parser.parse_args()

    lab_dir = args.site_name.lower()
    topology_file = os.path.join(lab_dir, f"{lab_dir}.clab.yml")

    print(f"Starting cleanup for site: '{args.site_name}'...")
    destroy_containerlab(topology_file)
    remove_generated_files(lab_dir)
    print("\nCleanup complete.")

if __name__ == "__main__":
    main()