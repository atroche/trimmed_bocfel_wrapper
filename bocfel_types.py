from pydantic import BaseModel

from remglk import UpdateMessage


class BocfelSavedGame(BaseModel):
    filename: str
    contents: bytes


class GameTurnOutput(BaseModel):
    update_message: UpdateMessage
    save_game: BocfelSavedGame | None = None

    def format_text(self) -> str:
        """Format the game turn output to plain text."""
        return self.update_message.format_text()


class BocJsonError(Exception):
    pass
