import os
import pty
import select
import subprocess
import termios
from pathlib import Path
from typing import Optional, Tuple

from pydantic import ValidationError

from bocfel_types import UpdateMessage
from remglk import InputToGame

STORYFILES_DIR = "./storyfiles"
DEFAULT_GAME_FILENAME = f"{STORYFILES_DIR}/curses.z5"

bocfel_path_from_env = os.getenv("BOCFEL_PATH") or "./bocfel-json-autosave"
ZMACHINE_INTERPRETER_BINARY_PATH = Path(bocfel_path_from_env)
ZMACHINE_INTERPRETER_BINARY_PATH_WITHOUT_AUTOSAVE = Path(
    bocfel_path_from_env.replace("-autosave", "")
)


def read_json_from_fd(
    fd: int,
    timeout: float = 0.01,
    max_attempts: int = 10,
) -> Optional[UpdateMessage]:
    """
    Read data from a file descriptor until a valid JSON object can be parsed.

    Args:
        fd: File descriptor to read from
        timeout: Timeout for select in seconds
        max_attempts: Maximum number of read attempts before giving up
        skip_echo: If True, skip echoed input and return the next JSON object
        last_input: The last input sent, used to identify echoes

    Returns:
        Parsed JSON object, or None if no valid JSON could be parsed
    """
    buffer = b""
    attempts = 0

    while attempts < max_attempts:
        # Wait for data with timeout
        rlist, _, _ = select.select([fd], [], [], timeout)
        if not rlist:
            print(f"No data available (attempt {attempts + 1}/{max_attempts})")
            attempts += 1
            continue

        try:
            # Read available data
            data = os.read(fd, 40960)
            if not data:
                print("EOF reached")
                break

            print(f"Read {len(data)} bytes from fd")
            buffer += data

            # Log buffer preview for debugging
            preview = buffer[-1000:] if len(buffer) > 1000 else buffer
            print(f"Buffer preview: {preview.decode('utf-8', errors='replace')}")

            # Only try to decode if we have update message markers
            decoded = buffer.decode("utf-8", errors="replace")
            # print(f"decoded: {decoded}")

            try:
                update_message = UpdateMessage.model_validate_json(decoded)
            except ValidationError as e:
                attempts += 1
                if attempts >= max_attempts:
                    print(f"Failed to parse JSON after max attempts: {decoded} {e}")
                    break
                continue

            if update_message:
                print("Found complete UpdateMessage")
                return update_message

            # Continue reading if we haven't found a valid message
            attempts += 1

        except OSError as e:
            print(f"OS error reading from fd: {e}")
            break

    # Report results if we failed to find a message
    if buffer:
        print(
            f"Failed to parse JSON after {max_attempts} attempts. Buffer size: {len(buffer)} bytes"
        )
    else:
        print(f"No data received after {max_attempts} attempts")

    return None


def write_text_to_fd(fd: int, text: str) -> None:
    """
    Write text to a file descriptor.

    Args:
        fd: File descriptor to write to
        text: Text to write
    """
    if not text.endswith("\n"):
        text += "\n"
    try:
        bytes_written = os.write(fd, text.encode("utf-8"))
        print(f"Wrote {bytes_written} bytes to FD: {text.strip()}")
        # Flush after writing to ensure the data is sent immediately
        os.fsync(fd)
        print("Flushed FD")
    except OSError as e:
        print(f"Error writing to FD: {e}")


def _setup_interactive_game_process(
    story_filepath: Path, xdg_data_home: Optional[Path] = None, singleturn: bool = False
) -> Tuple[int, subprocess.Popen]:
    """
    Setup a pseudo-terminal and start the game process.

    Args:
        story_filepath: Path to the story file
        xdg_data_home: Optional path to set as XDG_DATA_HOME environment variable

    Returns:
        Tuple of (master_fd, process)
    """
    # Choose the appropriate binary based on whether we're using autosave
    binary_path = (
        ZMACHINE_INTERPRETER_BINARY_PATH
        if xdg_data_home
        else ZMACHINE_INTERPRETER_BINARY_PATH_WITHOUT_AUTOSAVE
    )

    command = [
        str(binary_path),
        "-fm",
        "-width",
        "120",
        "-height",
        "50",
        "-z",
        "1",
        str(story_filepath),
    ]
    if singleturn:
        command.append("-singleturn")
    print(f"command: {command}")

    # Create a pseudo-terminal
    master_fd, slave_fd = pty.openpty()

    # Get current attributes
    attrs = termios.tcgetattr(master_fd)
    # Turn off ECHO flag
    attrs[3] = attrs[3] & ~termios.ECHO
    # Set the modified attributes
    termios.tcsetattr(master_fd, termios.TCSANOW, attrs)

    # Prepare environment with XDG_DATA_HOME if specified
    env = os.environ.copy()
    if xdg_data_home:
        env["XDG_DATA_HOME"] = str(xdg_data_home)
        print(f"Setting XDG_DATA_HOME to {xdg_data_home}")

    # Start the subprocess with the slave end of the PTY as its stdio
    process = subprocess.Popen(
        command,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        env=env,
    )

    # Close the slave end in the parent process
    os.close(slave_fd)

    return master_fd, process


def _send_command(master_fd: int, input_to_game: InputToGame) -> None:
    """
    Send a command to the game process.

    Args:
        master_fd: File descriptor to write to
        input_to_game: InputToGame object
    """
    to_send = input_to_game.model_dump_json()
    print(f"Sending input: {to_send}")
    write_text_to_fd(master_fd, to_send)
    print(f"Sent input: {to_send}")


def _read_and_validate_update(
    master_fd: int,
    timeout: float = 0.01,
    max_attempts: int = 10,
) -> Optional[UpdateMessage]:
    """
    Read and validate an update message from the game process.

    Args:
        master_fd: File descriptor to read from
        timeout: Timeout for select in seconds
        max_attempts: Maximum number of read attempts before giving up

    Returns:
        Validated UpdateMessage or None if not found
    """
    json_obj = read_json_from_fd(
        master_fd,
        timeout=timeout,
        max_attempts=max_attempts,
    )

    if not json_obj:
        return None

    try:
        message = UpdateMessage.model_validate(json_obj)
        return message
    except Exception as e:
        print(f"json_obj: {json_obj}")
        print(f"Error validating update message: {e} {json_obj}")
        return None


# def _press_keys_until_line_input(master_fd: int, story_filepath: Path, original_input: Input) -> UpdateMessage:
#     print("Pressing keys until line input")
#     attempts = 0
#     _send_command(master_fd, input.id, input.gen, input.type, " ")
#     while attempts < 4:
#         print(f"(attempt {attempts + 1}/4)")
#         update_message = _read_and_validate_update(master_fd)
#         print(f"update_message: {update_message}")
#         if update_message is None:
#             attempts += 1
#             continue

#         input = update_message.input[0]  # We know this exists because of the validator
#         if input.type == "line":
#             print(f"Line input found: {update_message}")
#             return update_message
#         else:
#             # TODO: try other keys if space isn't working
#             print(f"Sending space: {input}")
#             _send_command(master_fd, input.id, input.gen, input.type, " ")
#         attempts += 1
#     raise BocJsonError(f"No line input found after pressing keys for {story_filepath}")
