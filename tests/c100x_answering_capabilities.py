"""The answering-machine and memo capabilities the agent reports per model."""

C100X = {
    "answering_machine": {
        "supported": False, "status": False, "greeting_message": False,
        "messages": {"supported": False, "source": "local_files", "watch": False, "media": False, "delete": False},
    },
    "memos": {
        "supported": True, "text": True, "voice": False, "media": False, "source": "local_files",
        "watch": True, "delete": False, "write_text": True,
    },
}
C300X = {
    "answering_machine": {
        "supported": True, "status": True, "greeting_message": True,
        "messages": {"supported": True, "source": "local_files", "watch": True, "media": True, "delete": True},
    },
    "memos": {
        "supported": True, "text": True, "voice": True, "media": True, "source": "local_files",
        "watch": True, "delete": True, "write_text": True,
    },
}
