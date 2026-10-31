from cli_interface.app import run

# Deliberately no logging.basicConfig here: configuring the root logger is the host's
# decision, and importing or running this demo must not change it.

if __name__ == "__main__":
    run()
