import copy
from ctf_agent.llm.message_types import Message, ImageContent, TextContent


class ConversationContext:
    """
    Manages conversation history with token-aware image pruning.
    Keeps full text history but limits retained screenshots to avoid
    exceeding context windows.
    """

    def __init__(self, max_images: int = 10, max_messages: int = 200):
        self._messages: list[Message] = []
        self._max_images = max_images
        self._max_messages = max_messages

    @property
    def messages(self) -> list[Message]:
        return self._messages

    def add_message(self, message: Message) -> None:
        self._messages.append(message)
        self._prune_if_needed()

    def get_messages_for_api(self) -> list[Message]:
        """
        Return messages with only the N most recent images retained.
        Older images are replaced with a text placeholder.
        """
        msgs = copy.deepcopy(self._messages)
        image_count = 0
        for msg in reversed(msgs):
            new_content = []
            for block in reversed(msg.content):
                if isinstance(block, ImageContent):
                    image_count += 1
                    if image_count <= self._max_images:
                        new_content.insert(0, block)
                    else:
                        new_content.insert(
                            0,
                            TextContent(
                                text="[Screenshot omitted to save context space]"
                            ),
                        )
                else:
                    new_content.insert(0, block)
            msg.content = new_content
        return msgs

    def _prune_if_needed(self) -> None:
        if len(self._messages) > self._max_messages:
            keep_first = 1
            overflow = len(self._messages) - self._max_messages
            self._messages = (
                self._messages[:keep_first]
                + self._messages[keep_first + overflow :]
            )

    def clear(self) -> None:
        self._messages.clear()

    def get_summary(self) -> dict:
        image_count = sum(
            1
            for m in self._messages
            for b in m.content
            if isinstance(b, ImageContent)
        )
        return {
            "message_count": len(self._messages),
            "image_count": image_count,
        }
