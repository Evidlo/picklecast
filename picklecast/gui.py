from cli2gui import Cli2Gui

from main import run
from main import main

# The main function can be used as a CLI entrypoint
# Example: python -m mymodule:main.main
# def main():
#     print(args)
#     parser = argparse.ArgumentParser(description="this is an example parser")
#     parser.add_argument("arg", type=str, help="positional arg")

#     parser.add_subparsers()

#     # install_parser = subparsers.add_parser(
#     #     'install_service',
#     #     help="install systemd service on Linux",
#     # )

#     args = parser.parse_args()

#     # import ipdb
#     # ipdb.set_trace()

#     run(args)


decorator_function = Cli2Gui(
	run_function=run,
	auto_enable=True,
)

# The gui function can be used as a GUI entrypoint
# Example: python -m mymodule:main.gui
gui = decorator_function(main)

if __name__ == "__main__":
	# When main.py is called as script, run the GUI version
	# Example: python main.py
	# Example: ./main.py
	gui()
