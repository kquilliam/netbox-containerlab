# NetBox to Containerlab Digital Twin Generator

This project provides a Python script that fully automates the creation and deployment of a Containerlab digital twin. In a single command, it discovers network devices from NetBox, pulls their live configurations and hardware details, builds a topology, and deploys the lab. It is currently only setup to support Arista devices(and far too many device roles in Netbox).


## Workflow

The script automates the following end-to-end process:
1.  **Query NetBox**: Fetches all active Arista devices with specific roles from a user-provided site name.
2.  **Pre-flight Check (Optional)**: Runs a concurrent connectivity test to all devices to identify unreachable nodes before proceeding.
3.  **Provision Node Files**: Concurrently connects to all reachable devices to fetch and save:
    * Running configuration (to `lab_name/nodes/configs/hostname.cfg`).
    * Serial number and system MAC address (to `lab_name/nodes/sn/hostname.txt`).
4.  **Poll for LLDP**: Concurrently gathers live LLDP neighbor data from each device to discover the physical topology.
5.  **Render Topology**: Uses a Jinja2 template (`topology.j2`) to generate a site-specific `lab_name.clab.yml` file.
6.  **Deploy & Secure**: Automatically executes `containerlab deploy` and then fixes the generated SSH config file permissions to prevent disrupting other users on the system.
7.  **Summarize**: Provides a final report detailing which devices were reachable and included in the lab.

---
## Prerequisites 🔧

* Python 3.8+
* Containerlab
* Access to a populated NetBox instance with an API token.
* SSH connectivity from the machine running the script to the network devices.
* **Important**: Your local user account must be a member of the `docker` group.

---
## File Structure 📂

Your project directory should contain the following files:
```
.
├── clab_generator.py   # The main deployment script
├── cleanup.py          # A script to destroy the lab and remove files
├── requirements.txt    # Python dependencies
├── templates.yml       # Containerlab node kind definitions
└── topology.j2         # Jinja2 template for the output file
```
---
---
## Setup Instructions

1.  **Create a Project Directory**
    Create a directory and place the four files listed above inside it.

2.  **Create and Activate a Virtual Environment**
    ```bash
    cd /path/to/your/project
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Environment Variables**
    The script uses environment variables for configuration.
    ```bash
    # Required: Your NetBox instance URL and API token
    export NETBOX_URL='[https://netbox.example.com](https://netbox.example.com)'
    export NETBOX_TOKEN='YOUR_SUPER_SECRET_API_TOKEN'

    # Optional: Device credentials (if not set, you will be prompted)
    export DEVICE_USERNAME='your-ssh-user'
    export DEVICE_PASSWORD='your-ssh-password'
    ```

---
## Usage 🚀

The entire process is now executed with a single command. Run the script from your project directory, providing the NetBox site name as a required argument.

```bash
python clab_generator.py --site "your-site-name"
```

---
The script will then perform all workflow steps, including the final containerlab deploy.

## Deployment without Pre-flight Check:
To speed things up, you can skip the initial connectivity test. The script will discover unreachable devices during the data gathering stages instead.

```
python clab_generator.py --site "your-site-name" --skip-connectivity-test
```

## Cleaning Up the Lab 🧹
The cleanup.py script destroys the Containerlab environment and removes the entire generated lab directory. It does not require sudo.

```
python cleanup.py --site "your-site-name"
```

## Performance Configuration
You can tune the performance of the script by editing the MAX_WORKERS variable inside the Config class in clab_generator.py. This controls how many devices the script will connect to simultaneously.

## Generated Artifacts
After running the generator script for a site named "test-site", a new directory test-site/ will be created with the following structure:
```
test-site/
├── nodes/
│   ├── configs/
│   │   └── test-site-leaf01.cfg
│   └── sn/
│       └── test--leaf01.txt
└── test-site.clab.yml
```
