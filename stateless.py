import os
import tempfile
from pathlib import Path
from typing import Literal, Protocol, Union

from pydantic import BaseModel, field_validator

from bocfel_types import BocfelSavedGame, GameTurnOutput
from low_level_utils import (
    _read_and_validate_update,
    _send_command,
    _setup_interactive_game_process,
)
from remglk import SPECIAL_KEY_CODES, InputToGame, SpecialKeyCode, UpdateMessage


class StatelessGameClient(Protocol):
    def take_initial_turn(self, storyfile_contents: bytes) -> GameTurnOutput: ...
    def take_continued_turn(
        self, command: str, save_game_info: BocfelSavedGame
    ) -> GameTurnOutput: ...


class PlayerInput(BaseModel):
    type: Literal["line", "char"]
    # TODO: what should value be for different keypresses?
    # I know space is " ", but about return?
    # oh seems like it's \n
    # what about cursor keys?
    value: str

    def make_new_input_given_update_message(self, update_message: UpdateMessage) -> InputToGame:
        original_input = update_message.input[0]
        if original_input.type != self.type:
            raise WrongInputTypeGivenError(original_input.type, self.type)
        return InputToGame(
            window=original_input.id,
            gen=original_input.gen,
            type=self.type,
            value=self.value,
        )

    @staticmethod
    def from_dict(command_data: dict) -> "PlayerInput":
        """Create a PlayerInput instance from a dictionary representation.

        Args:
            command_data: Dictionary containing at least 'type' and 'value' keys

        Returns:
            A PlayerLineInput or PlayerCharInput instance depending on the type
        """
        command_type = command_data.get("type", "")
        command_value = command_data.get("value", "")

        if command_type == "line":
            return PlayerLineInput(value=command_value)
        elif command_type == "char":
            return PlayerCharInput(value=command_value)
        else:
            # Default fallback
            return PlayerLineInput(value=command_value)


class PlayerLineInput(PlayerInput):
    type: Literal["line"]
    value: str

    def __init__(self, value: str):
        super().__init__(type="line", value=value)


class PlayerCharInput(PlayerInput):
    type: Literal["char"]
    value: Union[SpecialKeyCode, str]  # Either a special key or a string

    def __init__(self, value: str):
        super().__init__(type="char", value=value)

    @field_validator("value")
    @classmethod
    def validate_char_input(cls, v: str) -> str:
        if v in SPECIAL_KEY_CODES:
            return v

        if len(v) != 1:
            raise ValueError("Character input must be a single character or a special key code")

        return v


class StatelessBocfelClientError(Exception):
    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return self.message


class WrongInputTypeGivenError(StatelessBocfelClientError):
    def __init__(
        self,
        input_type_expected_by_game: Literal["line", "char"],
        input_type_from_player: Literal["line", "char"],
        storyfile_filename: str | None = None,
    ):
        self.message = f"Wrong input type given. Expected {input_type_expected_by_game}, got {input_type_from_player}"
        if storyfile_filename:
            self.message += f" for {storyfile_filename}"


class StatelessBocfelClient(StatelessGameClient):
    def __init__(self):
        pass

    def take_initial_turn(self, storyfile_path: Path) -> GameTurnOutput:
        with tempfile.TemporaryDirectory(delete=True) as temp_folder:
            autosave_dir = Path(temp_folder) / "bocfel" / "autosave"
            master_fd, process = _setup_interactive_game_process(
                storyfile_path, Path(temp_folder), singleturn=False
            )
            update_message = _read_and_validate_update(master_fd)
            # if input is type char, we need to press keys until line input
            process.terminate()
            os.close(master_fd)
            autosave_files = list(autosave_dir.glob("*"))
            return GameTurnOutput(
                update_message=update_message,
                save_game=BocfelSavedGame(
                    filename=autosave_files[0].name, contents=autosave_files[0].read_bytes()
                ),
            )

    def take_continued_turn(
        self, storyfile_path: Path, player_input: PlayerInput, save_game_info: BocfelSavedGame
    ) -> GameTurnOutput:
        with tempfile.TemporaryDirectory(delete=True) as temp_folder:
            temp_folder_path = Path(temp_folder)
            autosave_dir = temp_folder_path / "bocfel" / "autosave"

            # write save game to temp folder
            autosave_dir.mkdir(parents=True, exist_ok=True)
            (autosave_dir / save_game_info.filename).write_bytes(save_game_info.contents)

            master_fd, process = _setup_interactive_game_process(
                storyfile_path, temp_folder_path, singleturn=False
            )
            update_message = _read_and_validate_update(master_fd)
            input_type_expected_by_game = update_message.input_type
            input_type_from_player = player_input.type

            if input_type_expected_by_game != input_type_from_player:
                raise WrongInputTypeGivenError(
                    input_type_expected_by_game, input_type_from_player, storyfile_path.name
                )

            input_to_game = player_input.make_new_input_given_update_message(update_message)
            _send_command(master_fd, input_to_game)
            update_message = _read_and_validate_update(master_fd)
            process.terminate()
            os.close(master_fd)
            autosave_files = list(autosave_dir.glob("*"))

            return GameTurnOutput(
                update_message=update_message,
                save_game=BocfelSavedGame(
                    filename=autosave_files[0].name, contents=autosave_files[0].read_bytes()
                ),
            )
