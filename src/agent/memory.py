"""Small in-process conversation history for one ProductAgent session."""

from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage


@dataclass(frozen=True)
class ConversationTurn:
    """Only the user text and final visible assistant answer are retained."""

    question: str
    answer: str


class ConversationMemory:
    """Keep at most four completed turns; nothing is written to disk."""

    def __init__(self, max_turns: int = 4) -> None:
        if not 1 <= max_turns <= 4:
            raise ValueError("ConversationMemory最多保留4轮。")
        self._max_turns = max_turns
        self._turns: list[ConversationTurn] = []

    @property
    def turns(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._turns)

    def to_messages(self) -> list[HumanMessage | AIMessage]:
        """Return fresh messages, excluding all tool and repair messages."""
        history: list[HumanMessage | AIMessage] = []
        for turn in self._turns:
            history.extend((HumanMessage(content=turn.question),
                            AIMessage(content=turn.answer)))
        return history

    def add_turn(self, question: str, answer: str) -> None:
        """Append one completed turn and evict the oldest whole turn if needed."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Memory问题不能为空。")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Memory答案不能为空。")
        self._turns.append(ConversationTurn(question.strip(), answer.strip()))
        del self._turns[:-self._max_turns]
