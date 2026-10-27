"""The closed, non-revealing simulated-user channel."""

ASK_REPLY = "I can't help with that right now."


def ask_user(question: str) -> str:
    if type(question) is not str:
        raise ValueError("question must be a string")
    return ASK_REPLY
