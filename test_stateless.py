from pathlib import Path

from pydantic import BaseModel

from stateless import PlayerCharInput, PlayerInput, PlayerLineInput, StatelessBocfelClient


def do_sequence_of_turns(storyfile_path: Path, player_inputs: list[PlayerInput]):
    game_client = StatelessBocfelClient()
    initial_turn_output = game_client.take_initial_turn(storyfile_path)
    initial_updated_message = initial_turn_output.update_message
    current_save_game = initial_turn_output.save_game
    print(initial_updated_message.formatted_text)
    transcript_sections = [initial_updated_message.formatted_text]
    for player_input in player_inputs:
        print(f"command: {player_input.value}")
        transcript_sections.append(f"command: {player_input.value}")
        continued_turn_output = game_client.take_continued_turn(
            storyfile_path, player_input, current_save_game
        )
        current_save_game = continued_turn_output.save_game
        continued_updated_message = continued_turn_output.update_message
        print(continued_updated_message.formatted_text)
        transcript_sections.append(continued_updated_message.formatted_text)
    return transcript_sections


class GameTestCase(BaseModel):
    """
    Can leave expected_text_in_different_outputs empty and nothing will be asserted against the game outputs.
    """

    storyfile_path: Path
    player_input_strings: list[str]
    expected_text_in_different_outputs: list[str]
    disabled: bool | None = None

    @property
    def player_inputs(self) -> list[PlayerInput]:
        values = []
        for player_input_string in self.player_input_strings:
            if len(player_input_string) == 1:
                values.append(PlayerCharInput(value=player_input_string))
            else:
                values.append(PlayerLineInput(value=player_input_string))
        return values


game_test_cases = [
    GameTestCase(
        storyfile_path=Path("./storyfiles/wishbringer-r69-s850920.z3"),
        player_input_strings=["south", "north"],
        # NOTE: that last string actually changes based on RNG. with seed fixed to 1 (-z 1 to bocfel)
        #       it's "numbskull" instead of something else like "idiot" or "knucklehead"
        expected_text_in_different_outputs=["trademark", "Your boss", "numbskull"],
    ),
    GameTestCase(
        storyfile_path=Path("./storyfiles/Tangle.z5"),
        player_input_strings=["inventory", "south", "south", " "],
        expected_text_in_different_outputs=[
            "Serial number 980226",
            "nothing of importance",
            "bicycle",
            "Hit any key",
            "sharp edges of memory",
        ],
    ),
    # storyfiles/trinity-r15-s870628.z4
    GameTestCase(
        storyfile_path=Path("./storyfiles/trinity-r15-s870628.z4"),
        player_input_strings=["j", "inventory", "south"],
        expected_text_in_different_outputs=[
            "Press any key to begin",
            "Hyde Park",
            "wristwatch",
            # note: another example of a line input that changes based on RNG.
            # sometimes see e.g. 'offended nannies', 'fat tourists'
            "A surge of gawking tourists",
        ],
    ),
]


def test_basic_stateless():
    # requires space after south south:
    # storyfile_path = Path("./storyfiles/Tangle.z5")

    # requires space to start:
    storyfile_path = Path("./storyfiles/curses.z5")

    # neither:
    # storyfile_path = Path("./storyfiles/wishbringer-r69-s850920.z3")

    commands = ["south"]
    game_client = StatelessBocfelClient()
    initial_turn_output = game_client.take_initial_turn(storyfile_path)
    initial_updated_message = initial_turn_output.update_message
    current_save_game = initial_turn_output.save_game
    print(initial_updated_message.formatted_text)
    print(initial_updated_message.input)
    spacebar = PlayerCharInput(value=" ")
    post_spacebar_update = game_client.take_continued_turn(
        storyfile_path, spacebar, current_save_game
    )
    print(post_spacebar_update.update_message.formatted_text)
    print(post_spacebar_update.update_message.input)


def test_stateless_game_client():
    for game_test_case in game_test_cases:
        if game_test_case.disabled:
            continue
        player_inputs = game_test_case.player_inputs
        storyfile_path = game_test_case.storyfile_path

        transcript_sections = do_sequence_of_turns(storyfile_path, player_inputs)
        expected_text_in_different_outputs = game_test_case.expected_text_in_different_outputs
        for i, transcript_section in enumerate(transcript_sections):
            is_game_output = i % 2 == 0
            if is_game_output:
                if expected_text_in_different_outputs:
                    expected_text_in_game_output = expected_text_in_different_outputs[i // 2]
                    assert expected_text_in_game_output in transcript_section
            assert len(transcript_sections) == 1 + (2 * len(player_inputs))
